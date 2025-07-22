#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ADC报警系统中间件服务器 - 嵌入式版本
专门适配野火鲁班猫A0开发板
"""

import socket
import threading
import time
import json
import logging
import os
import signal
import sys
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response
from queue import Queue, Empty
import struct
import sqlite3
from pathlib import Path
import gc

# 嵌入式环境默认配置
DEFAULT_CONFIG = {
    "network": {
        "broadcast_port": 5439,
        "listen_port": 5439,
        "web_port": 8081,
        "max_connections": 50,
        "socket_timeout": 30,
        "buffer_size": 1024
    },
    "resources": {
        "max_devices": 50,
        "max_log_size": "5MB",
        "max_log_files": 3,
        "cache_size": 500,
        "cleanup_interval": 300,
        "heartbeat_timeout": 180,
        "offline_timeout": 300,
    },
    "performance": {
        "thread_pool_size": 2,
        "queue_size": 500,
        "batch_size": 10,
        "flush_interval": 5,
    },
    "storage": {
        "database_path": "/var/lib/adc_alarm_system/devices.db",
        "backup_enabled": True,
        "backup_interval": 3600,
        "sync_interval": 60,
    },
    "system": {
        "log_path": "/var/log/adc_alarm_system",
        "data_path": "/var/lib/adc_alarm_system",
        "platform": "lubancat_a0"
    }
}

# 设置日志
def setup_logging():
    log_dir = Path(DEFAULT_CONFIG["system"]["log_path"])
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / "middleware.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# 获取本地IP地址
def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except Exception:
        return '0.0.0.0'

# 配置参数
SERVER_IP = get_local_ip()
BROADCAST_PORT = DEFAULT_CONFIG["network"]["broadcast_port"]
LISTEN_PORT = DEFAULT_CONFIG["network"]["listen_port"]
WEB_PORT = DEFAULT_CONFIG["network"]["web_port"]
SOCKET_TIMEOUT = DEFAULT_CONFIG["network"]["socket_timeout"]

# 协议帧定义
FRAME_HEAD = 0xAA
FRAME_TAIL = 0x55
FRAME_LENGTH = 6

# 系统配置
SERVER_ID = 0  # 服务器ID设为0，忽略此ID的设备信息

# Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'embedded_adc_alarm_system'

# 全局变量
device_manager = None
udp_server = None
udp_client = None
sse_queue = Queue(maxsize=DEFAULT_CONFIG["performance"]["queue_size"])
shutdown_event = threading.Event()

def check_server_initialized():
    """检查服务器是否已初始化"""
    if device_manager is None or udp_client is None:
        return False
    return True

class EmbeddedDeviceManager:
    """嵌入式环境优化的设备管理器"""
    
    def __init__(self, sse_queue=None):
        self.devices = {}
        self.sse_queue = sse_queue
        self.lock = threading.RLock()
        self.db_path = DEFAULT_CONFIG["storage"]["database_path"]
        self.max_devices = DEFAULT_CONFIG["resources"]["max_devices"]
        self.cache_size = DEFAULT_CONFIG["resources"]["cache_size"]
        self.cleanup_interval = DEFAULT_CONFIG["resources"]["cleanup_interval"]
        
        # 初始化数据库
        self._init_database()
        
        # 加载设备数据
        self._load_devices_from_db()
        
        # 启动清理线程
        self._start_cleanup_thread()
    
    def _init_database(self):
        """初始化SQLite数据库"""
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS devices (
                        id INTEGER PRIMARY KEY,
                        cmd INTEGER,
                        status INTEGER,
                        wifi_rssi INTEGER,
                        source_ip TEXT,
                        last_seen TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS device_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id INTEGER,
                        cmd INTEGER,
                        status INTEGER,
                        wifi_rssi INTEGER,
                        source_ip TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (device_id) REFERENCES devices (id)
                    )
                ''')
                
                conn.commit()
                logger.info("数据库初始化完成")
                
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
    
    def _load_devices_from_db(self):
        """从数据库加载设备数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM devices 
                    ORDER BY last_seen DESC 
                    LIMIT ?
                ''', (self.max_devices,))
                
                for row in cursor:
                    device_data = {
                        'cmd': row['cmd'],
                        'status': row['status'],
                        'wifi_rssi': row['wifi_rssi'],
                        'source_ip': row['source_ip'],
                        'last_seen': row['last_seen'],
                        'created_at': row['created_at'],
                        'updated_at': row['updated_at']
                    }
                    self.devices[row['id']] = device_data
                
                logger.info(f"从数据库加载了 {len(self.devices)} 个设备")
                
        except Exception as e:
            logger.error(f"从数据库加载设备失败: {e}")
    
    def _save_device_to_db(self, device_id, device_data):
        """保存设备到数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO devices 
                    (id, cmd, status, wifi_rssi, source_ip, last_seen, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    device_id,
                    device_data['cmd'],
                    device_data['status'],
                    device_data['wifi_rssi'],
                    device_data['source_ip'],
                    device_data['last_seen']
                ))
                
                conn.execute('''
                    INSERT INTO device_logs 
                    (device_id, cmd, status, wifi_rssi, source_ip)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    device_id,
                    device_data['cmd'],
                    device_data['status'],
                    device_data['wifi_rssi'],
                    device_data['source_ip']
                ))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"保存设备到数据库失败: {e}")
    
    def _start_cleanup_thread(self):
        """启动清理线程"""
        def cleanup_worker():
            while not shutdown_event.is_set():
                try:
                    self._cleanup_expired_devices()
                    self._cleanup_old_logs()
                    gc.collect()  # 垃圾回收
                    
                    shutdown_event.wait(self.cleanup_interval)
                    
                except Exception as e:
                    logger.error(f"清理线程错误: {e}")
                    time.sleep(60)
        
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()
        logger.info("清理线程已启动")
    
    def _cleanup_expired_devices(self):
        """清理过期设备"""
        try:
            offline_timeout = DEFAULT_CONFIG["resources"]["offline_timeout"]
            current_time = time.time()
            
            with self.lock:
                expired_devices = []
                for device_id, device_data in self.devices.items():
                    last_seen = datetime.fromisoformat(device_data['last_seen']).timestamp()
                    if current_time - last_seen > offline_timeout:
                        expired_devices.append(device_id)
                
                for device_id in expired_devices:
                    del self.devices[device_id]
                    logger.info(f"清理过期设备: {device_id}")
                
        except Exception as e:
            logger.error(f"清理过期设备失败: {e}")
    
    def _cleanup_old_logs(self):
        """清理旧日志"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    DELETE FROM device_logs 
                    WHERE timestamp < datetime('now', '-7 days')
                ''')
                conn.commit()
                
        except Exception as e:
            logger.error(f"清理旧日志失败: {e}")
    
    def update_device(self, device_id, cmd, status, wifi_rssi, source_ip):
        """更新设备信息"""
        if device_id < 1 or device_id > 254:
            logger.warning(f"无效的设备ID: {device_id}")
            return
        
        # 忽略服务器ID(0)的设备信息
        if device_id == SERVER_ID:
            logger.debug(f"忽略服务器ID({SERVER_ID})的设备信息")
            return
        
        current_time = datetime.now().isoformat()
        
        with self.lock:
            if device_id not in self.devices and len(self.devices) >= self.max_devices:
                logger.warning(f"设备数量已达上限 ({self.max_devices})")
                return
            
            device_data = {
                'cmd': cmd,
                'status': status,
                'wifi_rssi': wifi_rssi,
                'source_ip': source_ip,
                'last_seen': current_time,
                'updated_at': current_time
            }
            
            if device_id not in self.devices:
                device_data['created_at'] = current_time
            
            self.devices[device_id] = device_data
            
            # 异步保存到数据库
            threading.Thread(
                target=self._save_device_to_db,
                args=(device_id, device_data),
                daemon=True
            ).start()
            
            # 发送SSE事件
            self._send_sse_event({
                'type': 'device_update',
                'device_id': device_id,
                'data': device_data
            })
            
            logger.info(f"设备更新: ID={device_id}, CMD={cmd}, IP={source_ip}")
    
    def _send_sse_event(self, event_data):
        """发送SSE事件"""
        if self.sse_queue:
            try:
                self.sse_queue.put_nowait(event_data)
            except:
                pass
    
    def get_device(self, device_id):
        """获取设备信息"""
        with self.lock:
            return self.devices.get(device_id)
    
    def get_all_devices(self):
        """获取所有设备"""
        with self.lock:
            return self.devices.copy()
    
    def is_device_online(self, device_id, timeout=None):
        """检查设备是否在线"""
        if timeout is None:
            timeout = DEFAULT_CONFIG["resources"]["heartbeat_timeout"]
        
        device = self.get_device(device_id)
        if not device:
            return False
        
        last_seen = datetime.fromisoformat(device['last_seen'])
        time_diff = (datetime.now() - last_seen).total_seconds()
        return time_diff <= timeout

class EmbeddedUDPServer:
    """嵌入式优化的UDP服务器"""
    
    def __init__(self, device_manager, sse_queue):
        self.device_manager = device_manager
        self.sse_queue = sse_queue
        self.socket = None
        self.running = False
        self.thread = None
        self.buffer_size = DEFAULT_CONFIG["network"]["buffer_size"]
    
    def start(self):
        """启动UDP服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.settimeout(SOCKET_TIMEOUT)
            self.socket.bind((SERVER_IP, LISTEN_PORT))
            
            self.running = True
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            
            logger.info(f"UDP服务器启动: {SERVER_IP}:{LISTEN_PORT}")
            
        except Exception as e:
            logger.error(f"UDP服务器启动失败: {e}")
            raise
    
    def _listen_loop(self):
        """监听循环"""
        while self.running and not shutdown_event.is_set():
            try:
                if not self.socket:
                    break
                    
                data, addr = self.socket.recvfrom(self.buffer_size)
                if data:
                    threading.Thread(
                        target=self._handle_frame,
                        args=(data, addr),
                        daemon=True
                    ).start()
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"UDP接收错误: {e}")
                    time.sleep(1)
    
    def _handle_frame(self, data, addr):
        """处理接收到的帧"""
        try:
            if len(data) != FRAME_LENGTH:
                logger.warning(f"无效帧长度: {len(data)} from {addr}")
                return
            
            frame = struct.unpack('BBBBBB', data)
            head, cmd, device_id, status, wifi, tail = frame
            
            if head != FRAME_HEAD or tail != FRAME_TAIL:
                logger.warning(f"无效帧头尾: {head:02X}, {tail:02X} from {addr}")
                return
            
            self.device_manager.update_device(
                device_id, cmd, status, wifi, addr[0]
            )
            
        except Exception as e:
            logger.error(f"处理帧错误: {e}")
    
    def stop(self):
        """停止UDP服务器"""
        self.running = False
        if self.socket:
            self.socket.close()
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("UDP服务器已停止")

class EmbeddedUDPClient:
    """嵌入式优化的UDP客户端"""
    
    def __init__(self):
        self.socket = None
        self.buffer_size = DEFAULT_CONFIG["network"]["buffer_size"]
    
    def _get_socket(self):
        """获取socket连接"""
        if not self.socket:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.socket.settimeout(SOCKET_TIMEOUT)
        return self.socket
    
    def send_frame(self, cmd, device_id, status, wifi=0x00, target_ip='255.255.255.255'):
        """发送帧"""
        try:
            frame = struct.pack('BBBBBB', FRAME_HEAD, cmd, device_id, status, wifi, FRAME_TAIL)
            sock = self._get_socket()
            sock.sendto(frame, (target_ip, BROADCAST_PORT))
            logger.debug(f"发送帧: CMD={cmd}, ID={device_id}, IP={target_ip}")
            return True
            
        except Exception as e:
            logger.error(f"发送帧失败: {e}")
            return False
    
    def close(self):
        """关闭客户端"""
        if self.socket:
            self.socket.close()
            self.socket = None

# Flask路由
@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/api/devices')
def get_devices():
    """获取设备列表API"""
    try:
        if not device_manager:
            return jsonify({
                'success': False, 
                'error': '设备管理器未初始化',
                'devices': {},
                'statistics': {
                    'total': 0,
                    'online': 0,
                    'alarm': 0
                }
            }), 500
            
        devices = device_manager.get_all_devices()
        
        online_count = sum(1 for device_id in devices.keys() 
                          if device_manager.is_device_online(device_id))
        alarm_count = sum(1 for device in devices.values() 
                         if device.get('cmd') == 1)
        
        return jsonify({
            'success': True,
            'devices': devices,
            'statistics': {
                'total': len(devices),
                'online': online_count,
                'alarm': alarm_count
            }
        })
        
    except Exception as e:
        logger.error(f"获取设备列表失败: {e}")
        return jsonify({
            'success': False, 
            'error': str(e),
            'devices': {},
            'statistics': {
                'total': 0,
                'online': 0,
                'alarm': 0
            }
        }), 500

@app.route('/api/device/<int:device_id>')
def get_device(device_id):
    """获取单个设备信息"""
    try:
        if not device_manager:
            return jsonify({'success': False, 'error': '设备管理器未初始化'}), 500
        
        # 忽略服务器ID(0)的设备信息
        if device_id == SERVER_ID:
            return jsonify({'success': False, 'error': '不能获取服务器ID的设备信息'}), 400
        
        device = device_manager.get_device(device_id)
        if device:
            return jsonify({
                'success': True,
                'device': device,
                'online': device_manager.is_device_online(device_id)
            })
        else:
            return jsonify({'success': False, 'error': '设备不存在'}), 404
            
    except Exception as e:
        logger.error(f"获取设备信息失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/modify_device_id', methods=['POST'])
def modify_device_id():
    """修改设备ID"""
    try:
        if not udp_client:
            return jsonify({'success': False, 'error': 'UDP客户端未初始化'}), 500
        
        data = request.get_json()
        current_id = data.get('current_id')
        new_id = data.get('new_id')
        target_ip = data.get('target_ip', '255.255.255.255')
        
        if not all([current_id, new_id]):
            return jsonify({'success': False, 'error': '参数不完整'}), 400
        
        # 不能修改服务器ID(0)的设备
        if current_id == SERVER_ID or new_id == SERVER_ID:
            return jsonify({'success': False, 'error': '不能修改服务器ID'}), 400
        
        success = udp_client.send_frame(0x04, current_id, new_id, 0x00, target_ip)
        
        if success:
            return jsonify({'success': True, 'message': 'ID修改命令已发送'})
        else:
            return jsonify({'success': False, 'error': '命令发送失败'}), 500
            
    except Exception as e:
        logger.error(f"修改设备ID失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/immediate_report', methods=['POST'])
def immediate_report():
    """立即上报"""
    try:
        if not udp_client:
            return jsonify({'success': False, 'error': 'UDP客户端未初始化'}), 500
        
        data = request.get_json()
        device_id = data.get('device_id')
        target_ip = data.get('target_ip', '255.255.255.255')
        
        if not device_id:
            return jsonify({'success': False, 'error': '设备ID不能为空'}), 400
        
        # 不能对服务器ID(0)执行立即上报
        if device_id == SERVER_ID:
            return jsonify({'success': False, 'error': '不能对服务器ID执行立即上报'}), 400
        
        success = udp_client.send_frame(0x05, device_id, 0x00, 0x00, target_ip)
        
        if success:
            return jsonify({'success': True, 'message': '立即上报命令已发送'})
        else:
            return jsonify({'success': False, 'error': '命令发送失败'}), 500
            
    except Exception as e:
        logger.error(f"立即上报失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/events')
def events():
    """SSE事件流"""
    def event_stream():
        while not shutdown_event.is_set():
            try:
                event = sse_queue.get(timeout=30)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Empty:
                yield "data: {\"type\": \"heartbeat\"}\n\n"
            except Exception as e:
                logger.error(f"SSE事件流错误: {e}")
                break
    
    return Response(event_stream(), mimetype='text/plain')

def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"接收到信号 {signum}，正在关闭...")
    shutdown_event.set()
    
    if udp_server:
        udp_server.stop()
    if udp_client:
        udp_client.close()
    
    sys.exit(0)

def main():
    """主函数"""
    global device_manager, udp_server, udp_client
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info("=== ADC报警系统中间件 - 嵌入式版本 ===")
        logger.info(f"平台: {DEFAULT_CONFIG['system']['platform']}")
        logger.info(f"服务器IP: {SERVER_IP}")
        logger.info(f"监听端口: {LISTEN_PORT}")
        logger.info(f"Web端口: {WEB_PORT}")
        
        device_manager = EmbeddedDeviceManager(sse_queue)
        udp_client = EmbeddedUDPClient()
        udp_server = EmbeddedUDPServer(device_manager, sse_queue)
        
        udp_server.start()
        
        logger.info("启动Web服务器...")
        app.run(
            host=SERVER_IP,
            port=WEB_PORT,
            debug=False,
            threaded=True,
            use_reloader=False
        )
        
    except Exception as e:
        logger.error(f"服务器启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 