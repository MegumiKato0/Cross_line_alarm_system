#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import time
import json
import logging
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response
from queue import Queue
import struct
from device_logs import DeviceLogManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('middleware.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_local_ip():
    """自动获取本机IP地址"""
    try:
        # 创建一个UDP socket连接外部地址来获取本机IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 连接到一个外部地址（不会实际发送数据）
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            return local_ip
    except Exception as e:
        logger.warning(f"自动获取IP地址失败: {e}, 使用默认IP 0.0.0.0")
        return '0.0.0.0'  # 绑定到所有网络接口

def check_network_connectivity():
    """检查网络连接性"""
    logger.info("=== 网络连接性检查 ===")
    
    # 检查本机网络接口
    try:
        import subprocess
        result = subprocess.run(['ip', 'addr', 'show'], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("本机网络接口信息:")
            for line in result.stdout.split('\n'):
                if 'inet ' in line and '192.168' in line:
                    logger.info(f"  {line.strip()}")
    except Exception as e:
        logger.warning(f"无法获取网络接口信息: {e}")
    
    # 检查到设备IP的连通性
    device_ip = "192.168.0.228"
    try:
        import subprocess
        result = subprocess.run(['ping', '-c', '3', device_ip], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info(f"✓ 到设备 {device_ip} 的网络连通性正常")
        else:
            logger.warning(f"✗ 到设备 {device_ip} 的网络连通性异常")
            logger.warning(f"Ping输出: {result.stderr}")
    except Exception as e:
        logger.warning(f"无法测试到设备 {device_ip} 的连通性: {e}")
    
    # 检查UDP端口监听状态
    try:
        import subprocess
        result = subprocess.run(['netstat', '-tulpn'], capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if f':{LISTEN_PORT}' in line and 'UDP' in line:
                    logger.info(f"UDP端口监听状态: {line.strip()}")
    except Exception as e:
        logger.warning(f"无法检查端口监听状态: {e}")
    
    logger.info("=== 网络检查完成 ===")

# 配置参数
SERVER_IP = "192.168.0.25"  # 手动指定本机IP地址
BROADCAST_PORT = 5439  # 发送下行帧的端口
LISTEN_PORT = 5439     # 监听上行帧的端口
WEB_PORT = 8081        # Web服务端口

# 协议帧定义
FRAME_HEAD = 0xAA
FRAME_TAIL = 0x55
FRAME_LENGTH = 6

# 上行指令定义
CMD_ONLINE = 0x00     # 上线
CMD_ALARM = 0x01      # 报警
CMD_RECOVER = 0x02    # 恢复
CMD_HEARTBEAT = 0x03  # 心跳包

# 下行指令定义
CMD_MODIFY_ID = 0x04      # 修改设备ID
CMD_IMMEDIATE_REPORT = 0x05  # 立即上报

# 状态定义
STATUS_NORMAL = 0x00  # 正常状态
STATUS_ALARM = 0x01   # 报警状态
STATUS_RECOVER = 0x02 # 恢复状态

# 设备ID定义
ID_BROADCAST = 0xFF  # 广播ID

class DeviceManager:
    def __init__(self, sse_queue=None):
        self.devices = {}  # 设备信息存储
        self.lock = threading.Lock()
        self.pending_id_changes = {}  # 跟踪正在进行的ID修改: {source_ip: {'old_id': old_id, 'new_id': new_id, 'timestamp': timestamp}}
        self.sse_queue = sse_queue  # SSE事件队列
        self.log_manager = DeviceLogManager()  # 设备日志管理器
        self.devices_file = 'device_cache.json'  # 设备信息缓存文件
        
        # 启动时加载设备信息
        self.load_devices_from_file()
        
    def update_device(self, device_id, cmd, status, wifi_rssi, source_ip):
        with self.lock:
            now = datetime.now()
            
            # 如果是上线命令，检查是否是设备ID修改的响应
            if cmd == CMD_ONLINE:
                if self._check_and_migrate_device_id_internal(device_id, source_ip):
                    # ID迁移成功，设备记录已经存在
                    device = self.devices[device_id]
                    device['last_seen'] = now
                    device['wifi_rssi'] = wifi_rssi
                    device['source_ip'] = source_ip
                    device['status'] = 'online'
                    device['is_offline'] = False
                    logger.info(f"设备ID修改响应处理完成: {device_id} (IP: {source_ip})")
                    return device.copy()
            
            # 检查ID冲突（新设备上线时）
            if cmd == CMD_ONLINE:
                conflict_detected = self._check_id_conflict(device_id, source_ip)
                if conflict_detected:
                    # 处理ID冲突 - 需要在UDPServer中调用，因为需要udp_client
                    logger.info(f"ID冲突检测：设备 {device_id} (IP: {source_ip}) 与现有设备冲突")
                    # 返回特殊标记表示需要处理ID冲突
                    return {'conflict': True, 'device_id': device_id, 'source_ip': source_ip}
            
            # 常规设备处理
            if device_id not in self.devices:
                self.devices[device_id] = {
                    'id': device_id,
                    'first_seen': now,
                    'last_seen': now,
                    'status': 'online',  # 默认设置为online而不是unknown
                    'wifi_rssi': 0,
                    'source_ip': source_ip,
                    'alarm_count': 0,
                    'recover_count': 0,
                    'heartbeat_count': 0,
                    'is_offline': False,
                    'offline_time': None
                }
            
            device = self.devices[device_id]
            
            # 如果设备之前是离线状态，现在重新上线
            was_offline = device.get('is_offline', False)
            if was_offline:
                device['is_offline'] = False
                device['offline_time'] = None
                logger.info(f"设备 {device_id} 重新上线 (IP: {source_ip})")
                
                # 添加重新上线日志
                self.log_manager.add_log_entry(device_id, 'online', '设备重新上线', wifi_rssi, source_ip)
                
                # 发送设备重新上线的SSE事件
                if self.sse_queue is not None:
                    online_message = {
                        'type': 'device_online',
                        'timestamp': now.isoformat(),
                        'device_id': device_id,
                        'source_ip': source_ip,
                        'message': f'设备 {device_id} 重新上线 (IP: {source_ip})'
                    }
                    self.sse_queue.put(online_message)
                    logger.info(f"设备重新上线SSE消息已发送: {device_id}")
            
            device['last_seen'] = now
            device['wifi_rssi'] = wifi_rssi
            device['source_ip'] = source_ip
            
            # 更新设备状态 - 确保所有命令都正确设置状态
            if cmd == CMD_ONLINE:
                device['status'] = 'online'
                self.log_manager.add_log_entry(device_id, 'online', '设备上线', wifi_rssi, source_ip)
            elif cmd == CMD_ALARM:
                device['status'] = 'alarm'
                device['alarm_count'] += 1
                self.log_manager.add_log_entry(device_id, 'alarm', '设备报警', wifi_rssi, source_ip)
            elif cmd == CMD_RECOVER:
                device['status'] = 'recover'
                device['recover_count'] += 1
                self.log_manager.add_log_entry(device_id, 'recover', '设备恢复', wifi_rssi, source_ip)
            elif cmd == CMD_HEARTBEAT:
                device['status'] = 'heartbeat'
                device['heartbeat_count'] += 1
                self.log_manager.add_log_entry(device_id, 'heartbeat', '设备心跳', wifi_rssi, source_ip)
            else:
                # 对于未知命令，保持当前状态，但更新最后在线时间
                if device['status'] == 'unknown':
                    device['status'] = 'online'  # 如果之前是unknown，改为online
                self.log_manager.add_log_entry(device_id, 'unknown', f'未知命令: {cmd:02X}', wifi_rssi, source_ip)
            
            # 设备状态发生变化时，异步保存设备信息
            threading.Thread(target=self.save_devices_to_file, daemon=True).start()
            
            return device.copy()
    
    def get_device(self, device_id):
        with self.lock:
            device = self.devices.get(device_id, None)
            if device:
                # 转换datetime对象为字符串以支持JSON序列化
                result = {
                    'id': device['id'],
                    'first_seen': device['first_seen'].isoformat(),
                    'last_seen': device['last_seen'].isoformat(),
                    'status': device['status'],
                    'wifi_rssi': device['wifi_rssi'],
                    'source_ip': device['source_ip'],
                    'alarm_count': device['alarm_count'],
                    'recover_count': device['recover_count'],
                    'heartbeat_count': device['heartbeat_count'],
                    'is_offline': device.get('is_offline', False)
                }
                # 如果设备离线，包含离线时间
                if device.get('offline_time'):
                    result['offline_time'] = device['offline_time'].isoformat()
                return result
            return None
    
    def get_all_devices(self):
        with self.lock:
            # 转换datetime对象为字符串以支持JSON序列化
            serializable_devices = []
            for device in self.devices.values():
                serializable_device = {
                    'id': device['id'],
                    'first_seen': device['first_seen'].isoformat(),
                    'last_seen': device['last_seen'].isoformat(),
                    'status': device['status'],
                    'wifi_rssi': device['wifi_rssi'],
                    'source_ip': device['source_ip'],
                    'alarm_count': device['alarm_count'],
                    'recover_count': device['recover_count'],
                    'heartbeat_count': device['heartbeat_count'],
                    'is_offline': device.get('is_offline', False)
                }
                # 如果设备离线，包含离线时间
                if device.get('offline_time'):
                    serializable_device['offline_time'] = device['offline_time'].isoformat()
                serializable_devices.append(serializable_device)
            return serializable_devices
    
    def is_device_online(self, device_id, timeout=300):
        with self.lock:
            device = self.devices.get(device_id, None)
            if not device:
                return False
            
            time_diff = (datetime.now() - device['last_seen']).total_seconds()
            return time_diff < timeout
    
    def register_id_change(self, source_ip, old_id, new_id):
        """注册设备ID修改操作"""
        with self.lock:
            self.pending_id_changes[source_ip] = {
                'old_id': old_id,
                'new_id': new_id,
                'timestamp': datetime.now()
            }
            logger.info(f"注册ID修改操作: {source_ip} 从 {old_id} 到 {new_id}")
    
    def _check_and_migrate_device_id_internal(self, device_id, source_ip):
        """内部方法：检查并执行设备ID迁移（假设已经获得锁）"""
        # 检查是否有待处理的ID修改
        if source_ip in self.pending_id_changes:
            change_info = self.pending_id_changes[source_ip]
            
            # 检查是否是预期的新ID
            if device_id == change_info['new_id']:
                old_id = change_info['old_id']
                
                # 如果原设备存在，迁移数据到新ID
                if old_id in self.devices:
                    old_device = self.devices[old_id]
                    
                    # 创建新设备记录，保留原有数据
                    self.devices[device_id] = {
                        'id': device_id,
                        'first_seen': old_device['first_seen'],
                        'last_seen': old_device['last_seen'],
                        'status': old_device['status'],
                        'wifi_rssi': old_device['wifi_rssi'],
                        'source_ip': old_device['source_ip'],
                        'alarm_count': old_device['alarm_count'],
                        'recover_count': old_device['recover_count'],
                        'heartbeat_count': old_device['heartbeat_count']
                    }
                    
                    # 删除原设备记录
                    del self.devices[old_id]
                    
                    logger.info(f"设备ID迁移成功: {old_id} -> {device_id} (IP: {source_ip})")
                    
                    # 发送设备ID修改的SSE事件通知前端移除旧设备
                    device_change_message = {
                        'type': 'device_id_change',
                        'timestamp': datetime.now().isoformat(),
                        'old_device_id': old_id,
                        'new_device_id': device_id,
                        'source_ip': source_ip,
                        'message': f'设备ID已修改: {old_id} -> {device_id}'
                    }
                    
                    # 将消息添加到SSE队列
                    if self.sse_queue is not None:
                        self.sse_queue.put(device_change_message)
                        logger.info(f"发送设备ID修改SSE事件: {old_id} -> {device_id} (IP: {source_ip})")
                
                # 清除待处理的ID修改记录
                del self.pending_id_changes[source_ip]
                return True
        
        return False
    
    def check_and_migrate_device_id(self, device_id, source_ip):
        """检查并执行设备ID迁移"""
        with self.lock:
            return self._check_and_migrate_device_id_internal(device_id, source_ip)
    
    def cleanup_expired_id_changes(self, timeout=300):
        """清理超时的ID修改记录"""
        with self.lock:
            current_time = datetime.now()
            expired_ips = []
            
            for ip, change_info in self.pending_id_changes.items():
                time_diff = (current_time - change_info['timestamp']).total_seconds()
                if time_diff > timeout:
                    expired_ips.append(ip)
            
            for ip in expired_ips:
                logger.warning(f"清理过期的ID修改记录: {ip}")
                del self.pending_id_changes[ip]
    
    def check_offline_devices(self, offline_timeout=180):
        """检查离线设备 (默认3分钟)"""
        with self.lock:
            current_time = datetime.now()
            newly_offline_devices = []
            
            for device_id, device in self.devices.items():
                if not device.get('is_offline', False):
                    time_diff = (current_time - device['last_seen']).total_seconds()
                    if time_diff > offline_timeout:
                        device['is_offline'] = True
                        device['offline_time'] = current_time
                        newly_offline_devices.append(device_id)
                        logger.info(f"设备 {device_id} 离线 (超过 {offline_timeout} 秒无响应)")
            
            # 为离线设备添加日志记录
            for device_id in newly_offline_devices:
                device = self.devices.get(device_id)
                if device:
                    self.log_manager.add_log_entry(
                        device_id, 
                        'offline', 
                        '设备离线（超时无响应）', 
                        device.get('wifi_rssi', 0), 
                        device.get('source_ip', '')
                    )
            
            # 发送离线设备的SSE事件
            if self.sse_queue is not None:
                for device_id in newly_offline_devices:
                    device = self.devices.get(device_id)
                    offline_message = {
                        'type': 'device_offline',
                        'timestamp': current_time.isoformat(),
                        'device_id': device_id,
                        'source_ip': device.get('source_ip', '') if device else '',
                        'message': f'设备 {device_id} 离线（超过 {offline_timeout} 秒无响应）'
                    }
                    self.sse_queue.put(offline_message)
                    logger.info(f"设备离线SSE消息已发送: {device_id}")
            
            return newly_offline_devices
    
    def _check_id_conflict(self, device_id: int, source_ip: str) -> bool:
        """检查设备ID是否冲突"""
        if device_id in self.devices:
            existing_device = self.devices[device_id]
            # 如果是同一个设备（相同IP），不算冲突
            if existing_device['source_ip'] == source_ip:
                return False
            # 如果现有设备已经离线超过5分钟，可以被替换
            if existing_device.get('is_offline', False):
                offline_time = existing_device.get('offline_time')
                if offline_time:
                    time_diff = (datetime.now() - offline_time).total_seconds()
                    if time_diff > 300:  # 5分钟
                        return False
            # 其他情况算作冲突
            return True
        return False
    
    def _handle_id_conflict(self, device_id: int, source_ip: str, udp_client) -> int:
        """处理ID冲突，返回新分配的ID"""
        # 生成新的ID
        new_id = self._generate_available_id()
        if new_id == 0:
            logger.error(f"无法为设备 {device_id} (IP: {source_ip}) 分配新ID：所有ID已被使用")
            return 0  # 返回0表示失败
        
        # 发送ID修改命令
        success = udp_client.modify_device_id(device_id, new_id, source_ip)
        
        if success:
            # 注册ID修改操作
            self.register_id_change(source_ip, device_id, new_id)
            
            # 发送ID冲突处理的SSE事件
            if self.sse_queue is not None:
                conflict_message = {
                    'type': 'id_conflict',
                    'timestamp': datetime.now().isoformat(),
                    'old_device_id': device_id,
                    'new_device_id': new_id,
                    'source_ip': source_ip,
                    'message': f'检测到ID冲突，设备 {device_id} 已自动修改为 {new_id}'
                }
                self.sse_queue.put(conflict_message)
            
            # 添加冲突处理日志
            self.log_manager.add_log_entry(
                new_id, 'conflict', 
                f'ID冲突自动处理：原ID {device_id} 改为 {new_id}', 
                0, source_ip
            )
            
            return new_id
        else:
            logger.error(f"发送ID修改命令失败：设备 {device_id} (IP: {source_ip}) -> {new_id}")
            return 0  # 返回0表示失败
    
    def _generate_available_id(self) -> int:
        """生成可用的设备ID"""
        # 查找1-254范围内的可用ID
        for candidate_id in range(1, 255):
            if candidate_id not in self.devices:
                return candidate_id
            # 检查是否是长期离线的设备
            device = self.devices[candidate_id]
            if device.get('is_offline', False):
                offline_time = device.get('offline_time')
                if offline_time:
                    time_diff = (datetime.now() - offline_time).total_seconds()
                    if time_diff > 3600:  # 1小时
                        return candidate_id
        return 0  # 返回0表示无可用ID
    
    def save_devices_to_file(self):
        """保存设备信息到文件"""
        try:
            with self.lock:
                # 准备序列化的设备数据
                serializable_devices = {}
                for device_id, device in self.devices.items():
                    # 只保存基本信息，不保存实时状态
                    serializable_devices[device_id] = {
                        'id': device['id'],
                        'first_seen': device['first_seen'].isoformat(),
                        'last_seen': device['last_seen'].isoformat(),
                        'source_ip': device['source_ip'],
                        'alarm_count': device['alarm_count'],
                        'recover_count': device['recover_count'],
                        'heartbeat_count': device['heartbeat_count']
                        # 不保存状态和离线信息，这些需要重新检测
                    }
                
                # 写入文件
                with open(self.devices_file, 'w', encoding='utf-8') as f:
                    json.dump(serializable_devices, f, ensure_ascii=False, indent=2)
                
                logger.info(f"设备信息已保存到文件: {len(serializable_devices)} 个设备")
        except Exception as e:
            logger.error(f"保存设备信息失败: {e}")
    
    def load_devices_from_file(self):
        """从文件加载设备信息"""
        try:
            if os.path.exists(self.devices_file):
                with open(self.devices_file, 'r', encoding='utf-8') as f:
                    devices_data = json.load(f)
                
                with self.lock:
                    for device_id_str, device_data in devices_data.items():
                        device_id = int(device_id_str)
                        
                        # 确保所有必要字段都存在
                        device = {
                            'id': device_id,
                            'first_seen': datetime.fromisoformat(device_data.get('first_seen', datetime.now().isoformat())),
                            'last_seen': datetime.fromisoformat(device_data.get('last_seen', datetime.now().isoformat())),
                            'status': device_data.get('status', 'online'),  # 默认状态为online
                            'wifi_rssi': device_data.get('wifi_rssi', 0),
                            'source_ip': device_data.get('source_ip', ''),
                            'alarm_count': device_data.get('alarm_count', 0),
                            'recover_count': device_data.get('recover_count', 0),
                            'heartbeat_count': device_data.get('heartbeat_count', 0),
                            'is_offline': device_data.get('is_offline', False)
                        }
                        
                        # 如果设备离线，包含离线时间
                        if device_data.get('offline_time'):
                            device['offline_time'] = datetime.fromisoformat(device_data['offline_time'])
                        
                        self.devices[device_id] = device
                
                logger.info(f"从缓存文件加载了 {len(self.devices)} 个设备信息")
            else:
                logger.info("设备缓存文件不存在，将创建新的缓存")
        except Exception as e:
            logger.error(f"加载设备缓存文件失败: {e}")
            # 如果加载失败，清空设备列表
            with self.lock:
                self.devices.clear()
    
    def broadcast_immediate_report(self, udp_client):
        """广播立即上报命令以重新发现设备"""
        try:
            logger.info("发送广播立即上报命令，重新发现设备...")
            
            # 发送广播立即上报命令到所有设备（ID=255为广播地址）
            success = udp_client.immediate_report(ID_BROADCAST, '255.255.255.255')
            
            if success:
                logger.info("广播立即上报命令已发送")
                
                # 如果有缓存的设备，也向它们的IP单独发送
                with self.lock:
                    unique_ips = set()
                    for device in self.devices.values():
                        if device['source_ip'] not in unique_ips:
                            unique_ips.add(device['source_ip'])
                            udp_client.immediate_report(ID_BROADCAST, device['source_ip'])
                
                if unique_ips:
                    logger.info(f"向 {len(unique_ips)} 个已知IP地址发送了立即上报命令")
            else:
                logger.error("发送广播立即上报命令失败")
        except Exception as e:
            logger.error(f"广播立即上报命令错误: {e}")
    
    def start_device_discovery(self, udp_client):
        """启动设备发现流程"""
        def discovery_worker():
            # 等待2秒让服务器完全启动
            time.sleep(2)
            
            # 第一次立即发现
            self.broadcast_immediate_report(udp_client)
            
            # 等待5秒让设备响应
            time.sleep(5)
            
            # 再次发送以确保发现所有设备
            self.broadcast_immediate_report(udp_client)
            
            # 保存当前设备状态
            self.save_devices_to_file()
            
            # 发送设备重新发现的SSE事件
            if self.sse_queue is not None:
                discovery_message = {
                    'type': 'device_discovery',
                    'timestamp': datetime.now().isoformat(),
                    'message': '设备重新发现完成，请刷新页面查看最新设备状态'
                }
                self.sse_queue.put(discovery_message)
        
        # 启动发现线程
        discovery_thread = threading.Thread(target=discovery_worker, daemon=True)
        discovery_thread.start()
        logger.info("设备发现流程已启动")
    
    def start_periodic_discovery(self, udp_client, interval=300):
        """启动定期设备发现（默认5分钟间隔）"""
        def periodic_worker():
            while True:
                time.sleep(interval)  # 等待指定间隔
                try:
                    logger.info("执行定期设备发现...")
                    self.broadcast_immediate_report(udp_client)
                    # 保存当前设备状态
                    self.save_devices_to_file()
                except Exception as e:
                    logger.error(f"定期设备发现错误: {e}")
        
        # 启动定期发现线程
        periodic_thread = threading.Thread(target=periodic_worker, daemon=True)
        periodic_thread.start()
        logger.info(f"定期设备发现已启动，间隔: {interval}秒")

class UDPServer:
    def __init__(self, device_manager, sse_queue):
        self.device_manager = device_manager
        self.sse_queue = sse_queue
        self.socket = None
        self.running = False
        
    def start(self):
        """启动UDP服务器"""
        try:
            # 创建UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # 设置socket选项，允许地址重用
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 绑定到所有网络接口，确保能接收广播
            self.socket.bind(('0.0.0.0', LISTEN_PORT))
            
            logger.info(f"UDP监听服务器启动成功，地址: 0.0.0.0:{LISTEN_PORT}")
            
            # 启动监听线程
            self.running = True
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()
            
        except Exception as e:
            logger.error(f"启动UDP服务器失败: {e}")
            raise
    
    def _listen_loop(self):
        """UDP服务器监听循环"""
        while self.running:
            try:
                if self.socket:
                    # 设置超时，避免阻塞
                    self.socket.settimeout(1.0)
                    data, addr = self.socket.recvfrom(1024)
                    logger.info(f"收到UDP数据 from {addr}: {data.hex()}")
                    self.handle_frame(data, addr)
            except socket.timeout:
                # 超时是正常的，继续循环
                continue
            except Exception as e:
                logger.error(f"UDP接收错误: {e}")
                time.sleep(1)  # 避免错误时无限循环
    
    def handle_frame(self, data, addr):
        try:
            if len(data) != FRAME_LENGTH:
                logger.warning(f"收到长度不符的数据包: {len(data)} bytes from {addr}")
                return
            
            # 解析协议帧
            frame_data = struct.unpack('BBBBBB', data)
            head, cmd, device_id, status, wifi, tail = frame_data
            
            # 验证帧头和帧尾
            if head != FRAME_HEAD or tail != FRAME_TAIL:
                logger.warning(f"收到无效的协议帧 from {addr}: {data.hex()}")
                return
            
            # 检查是否是下行命令（不应该作为上行命令处理）
            if cmd == CMD_MODIFY_ID or cmd == CMD_IMMEDIATE_REPORT:
                logger.warning(f"收到下行命令作为上行帧: {self.get_cmd_name(cmd)} from {addr}")
                return
            
            # 记录接收到的帧
            logger.info(f"收到上行帧 from {addr}: {data.hex()} - 设备ID: {device_id}, 指令: {self.get_cmd_name(cmd)}")
            
            # 更新设备信息
            device = self.device_manager.update_device(device_id, cmd, status, wifi, addr[0])
            
            # 检查是否需要处理ID冲突
            if isinstance(device, dict) and device.get('conflict'):
                # 处理ID冲突
                conflict_device_id = device['device_id']
                conflict_source_ip = device['source_ip']
                
                # 创建全局udp_client引用
                global udp_client
                new_id = self.device_manager._handle_id_conflict(conflict_device_id, conflict_source_ip, udp_client)
                
                if new_id > 0:
                    logger.info(f"ID冲突处理：设备 {conflict_device_id} (IP: {conflict_source_ip}) 被分配新ID: {new_id}")
                    
                    # 发送ID冲突SSE消息
                    conflict_message = {
                        'type': 'id_conflict',
                        'timestamp': datetime.now().isoformat(),
                        'old_device_id': conflict_device_id,
                        'new_device_id': new_id,
                        'source_ip': conflict_source_ip,
                        'message': f'设备ID冲突已自动处理: {conflict_device_id} -> {new_id}'
                    }
                    self.sse_queue.put(conflict_message)
                else:
                    logger.error(f"ID冲突处理失败：设备 {conflict_device_id} (IP: {conflict_source_ip})")
                
                # 不发送其他SSE消息，等待设备响应新ID
                return
            
            # 构造SSE消息，转换datetime对象为字符串
            device_info_serializable = None
            if device:
                device_info_serializable = {
                    'id': device['id'],
                    'first_seen': device['first_seen'].isoformat() if isinstance(device['first_seen'], datetime) else device['first_seen'],
                    'last_seen': device['last_seen'].isoformat() if isinstance(device['last_seen'], datetime) else device['last_seen'],
                    'status': device['status'],
                    'wifi_rssi': device['wifi_rssi'],
                    'source_ip': device['source_ip'],
                    'alarm_count': device['alarm_count'],
                    'recover_count': device['recover_count'],
                    'heartbeat_count': device['heartbeat_count'],
                    'is_offline': device.get('is_offline', False)
                }
                # 如果设备离线，包含离线时间
                if device.get('offline_time'):
                    device_info_serializable['offline_time'] = device['offline_time'].isoformat() if isinstance(device['offline_time'], datetime) else device['offline_time']
            
            sse_message = {
                'type': 'device_message',
                'timestamp': datetime.now().isoformat(),
                'device_id': device_id,
                'command': cmd,
                'command_name': self.get_cmd_name(cmd),
                'status': status,
                'wifi_rssi': wifi,
                'source_ip': addr[0],
                'device_info': device_info_serializable
            }
            
            # 推送到SSE队列
            self.sse_queue.put(sse_message)
            logger.info(f"SSE消息已发送: 设备 {device_id} - {self.get_cmd_name(cmd)}")
            
        except Exception as e:
            logger.error(f"处理帧数据错误: {e}")
            # 发送错误SSE消息
            error_message = {
                'type': 'error',
                'timestamp': datetime.now().isoformat(),
                'message': f'处理设备消息错误: {str(e)}',
                'device_id': device_id if 'device_id' in locals() else 'unknown',
                'source_ip': addr[0] if 'addr' in locals() else 'unknown'
            }
            self.sse_queue.put(error_message)
    
    def get_cmd_name(self, cmd):
        cmd_names = {
            CMD_ONLINE: '上线',
            CMD_ALARM: '报警',
            CMD_RECOVER: '恢复',
            CMD_HEARTBEAT: '心跳'
        }
        return cmd_names.get(cmd, f'未知({cmd:02X})')
    
    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()

class UDPClient:
    def __init__(self):
        self.socket = None
        
    def send_frame(self, cmd, device_id, status, wifi=0x00, target_ip='255.255.255.255'):
        try:
            if not self.socket:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            # 构造协议帧
            frame = struct.pack('BBBBBB', FRAME_HEAD, cmd, device_id, status, wifi, FRAME_TAIL)
            
            # 发送帧
            self.socket.sendto(frame, (target_ip, BROADCAST_PORT))
            
            logger.info(f"发送下行帧到 {target_ip}:{BROADCAST_PORT}: {frame.hex()} - 设备ID: {device_id}, 指令: {self.get_cmd_name(cmd)}")
            return True
            
        except Exception as e:
            logger.error(f"发送帧失败: {e}")
            return False
    
    def get_cmd_name(self, cmd):
        cmd_names = {
            CMD_MODIFY_ID: '修改设备ID',
            CMD_IMMEDIATE_REPORT: '立即上报'
        }
        return cmd_names.get(cmd, f'未知({cmd:02X})')
    
    def modify_device_id(self, current_id, new_id, target_ip='255.255.255.255'):
        return self.send_frame(CMD_MODIFY_ID, current_id, new_id, 0x00, target_ip)
    
    def immediate_report(self, device_id, target_ip='255.255.255.255'):
        return self.send_frame(CMD_IMMEDIATE_REPORT, device_id, 0x00, 0x00, target_ip)

# 全局对象
sse_queue = Queue()
device_manager = DeviceManager(sse_queue)
udp_client = UDPClient()

# Flask应用
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/devices')
def get_devices():
    """获取所有设备信息"""
    devices = device_manager.get_all_devices()
    return jsonify({
        'success': True,
        'devices': devices,
        'count': len(devices)
    })

@app.route('/api/device/<int:device_id>')
def get_device(device_id):
    """获取特定设备信息"""
    device = device_manager.get_device(device_id)
    if device:
        return jsonify({
            'success': True,
            'device': device
        })
    else:
        return jsonify({
            'success': False,
            'message': '设备不存在'
        }), 404

@app.route('/api/modify_device_id', methods=['POST'])
def modify_device_id():
    """修改设备ID"""
    try:
        data = request.get_json()
        current_id = data.get('current_id')
        new_id = data.get('new_id')
        target_ip = data.get('target_ip', '255.255.255.255')
        
        if not current_id or not new_id:
            return jsonify({
                'success': False,
                'message': '当前ID和新ID不能为空'
            }), 400
        
        if new_id == 0 or new_id == ID_BROADCAST:
            return jsonify({
                'success': False,
                'message': '新ID不能为0或255'
            }), 400
        
        # 检查设备是否在线
        if not device_manager.is_device_online(current_id):
            return jsonify({
                'success': False,
                'message': '设备不在线或不存在'
            }), 400
        
        # 获取设备信息（用于获取IP地址）
        old_device = device_manager.get_device(current_id)
        if not old_device:
            return jsonify({
                'success': False,
                'message': '无法获取设备信息'
            }), 400
        
        device_ip = old_device['source_ip']
        
        # 检查新ID是否与现有设备ID重复
        if device_manager._check_id_conflict(new_id, device_ip):
            return jsonify({
                'success': False,
                'message': f'新ID {new_id} 已被其他设备使用，请选择其他ID'
            }), 400
        
        # 发送修改ID命令
        success = udp_client.modify_device_id(current_id, new_id, target_ip)
        
        if success:
            # 注册ID修改操作
            device_manager.register_id_change(device_ip, current_id, new_id)
            
            logger.info(f"设备ID修改命令已发送: {current_id} -> {new_id} (IP: {device_ip})")
            
            return jsonify({
                'success': True,
                'message': f'设备ID修改命令已发送: {current_id} -> {new_id}。请等待设备响应（通常需要几秒钟）'
            })
        else:
            return jsonify({
                'success': False,
                'message': '发送修改ID命令失败'
            }), 500
            
    except Exception as e:
        logger.error(f"修改设备ID错误: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500

@app.route('/api/immediate_report', methods=['POST'])
def immediate_report():
    """立即上报"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        target_ip = data.get('target_ip', '255.255.255.255')
        
        if not device_id:
            return jsonify({
                'success': False,
                'message': '设备ID不能为空'
            }), 400
        
        # 发送立即上报命令
        success = udp_client.immediate_report(device_id, target_ip)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'立即上报命令已发送给设备 {device_id}'
            })
        else:
            return jsonify({
                'success': False,
                'message': '发送立即上报命令失败'
            }), 500
            
    except Exception as e:
        logger.error(f"立即上报错误: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500

@app.route('/api/rediscover_devices', methods=['POST'])
def rediscover_devices():
    """手动重新发现设备"""
    try:
        logger.info("接收到手动重新发现设备请求")
        
        # 启动设备发现流程
        device_manager.start_device_discovery(udp_client)
        
        return jsonify({
            'success': True,
            'message': '设备重新发现流程已启动，请等待几秒钟查看结果'
        })
        
    except Exception as e:
        logger.error(f"手动重新发现设备错误: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500

@app.route('/api/device/<int:device_id>/logs')
def get_device_logs(device_id):
    """获取设备日志"""
    try:
        limit = request.args.get('limit', 100, type=int)
        log_type = request.args.get('type', None)
        start_time = request.args.get('start_time', None)
        end_time = request.args.get('end_time', None)
        
        if log_type or start_time or end_time:
            logs = device_manager.log_manager.search_logs(
                device_id, log_type, start_time, end_time, limit
            )
        else:
            logs = device_manager.log_manager.get_device_logs(device_id, limit)
        
        return jsonify({
            'success': True,
            'logs': logs,
            'count': len(logs)
        })
    except Exception as e:
        logger.error(f"获取设备日志错误: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500

@app.route('/api/device/<int:device_id>/logs/summary')
def get_device_log_summary(device_id):
    """获取设备日志摘要"""
    try:
        summary = device_manager.log_manager.get_device_log_summary(device_id)
        return jsonify({
            'success': True,
            'summary': summary
        })
    except Exception as e:
        logger.error(f"获取设备日志摘要错误: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500

@app.route('/events')
def events():
    """SSE事件流"""
    def event_stream():
        while True:
            try:
                # 获取队列中的消息
                if not sse_queue.empty():
                    message = sse_queue.get(timeout=1)
                    # 确保消息是JSON可序列化的
                    if isinstance(message, dict):
                        # 处理datetime对象
                        for key, value in message.items():
                            if isinstance(value, datetime):
                                message[key] = value.isoformat()
                    yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
                else:
                    # 发送心跳包
                    heartbeat_message = {
                        'type': 'heartbeat', 
                        'timestamp': datetime.now().isoformat()
                    }
                    yield f"data: {json.dumps(heartbeat_message, ensure_ascii=False)}\n\n"
                    time.sleep(10)
            except Exception as e:
                logger.error(f"SSE事件流错误: {e}")
                # 发送错误消息
                error_message = {
                    'type': 'error',
                    'message': f'SSE连接错误: {str(e)}',
                    'timestamp': datetime.now().isoformat()
                }
                yield f"data: {json.dumps(error_message, ensure_ascii=False)}\n\n"
                break
    
    return Response(event_stream(), content_type='text/event-stream')

@app.route('/test_sse')
def test_sse():
    """测试SSE连接"""
    def test_event_stream():
        try:
            # 发送测试消息
            test_message = {
                'type': 'test',
                'timestamp': datetime.now().isoformat(),
                'message': 'SSE连接测试成功'
            }
            yield f"data: {json.dumps(test_message, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"SSE测试错误: {e}")
    
    return Response(test_event_stream(), content_type='text/event-stream')

def start_udp_server():
    """启动UDP服务器"""
    udp_server = UDPServer(device_manager, sse_queue)
    udp_server.start()

def cleanup_expired_records():
    """定期清理过期的ID修改记录"""
    while True:
        time.sleep(60)  # 每分钟检查一次
        device_manager.cleanup_expired_id_changes()

def check_offline_devices():
    """定期检查离线设备"""
    while True:
        time.sleep(30)  # 每30秒检查一次
        device_manager.check_offline_devices(offline_timeout=180)  # 3分钟超时

def main():
    """主函数"""
    logger.info("启动中间件服务器...")
    logger.info(f"服务器IP: {SERVER_IP}")
    logger.info(f"监听端口: {LISTEN_PORT}")
    logger.info(f"广播端口: {BROADCAST_PORT}")
    logger.info(f"Web端口: {WEB_PORT}")
    
    # 执行网络连接性检查
    check_network_connectivity()
    
    # 启动UDP服务器线程
    udp_thread = threading.Thread(target=start_udp_server, daemon=True)
    udp_thread.start()
    
    # 启动过期记录清理线程
    cleanup_thread = threading.Thread(target=cleanup_expired_records, daemon=True)
    cleanup_thread.start()
    
    # 启动离线设备检查线程
    offline_check_thread = threading.Thread(target=check_offline_devices, daemon=True)
    offline_check_thread.start()
    
    # 启动设备重新发现流程
    device_manager.start_device_discovery(udp_client)
    
    # 启动定期设备发现（每5分钟）
    device_manager.start_periodic_discovery(udp_client, 300)
    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, threaded=True)

if __name__ == '__main__':
    main() 