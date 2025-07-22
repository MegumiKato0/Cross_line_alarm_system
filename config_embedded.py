#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
嵌入式Linux环境配置文件
适用于野火鲁班猫A0开发板
"""

import os
import socket
import logging
import subprocess
import json
from pathlib import Path

# 嵌入式环境配置
EMBEDDED_CONFIG = {
    # 系统配置
    "system": {
        "platform": "lubancat_a0",
        "architecture": "aarch64",
        "os": "embedded_linux",
        "memory_limit": "512MB",  # 野火鲁班猫A0内存限制
        "storage_path": "/opt/adc_alarm_system",  # 系统安装路径
        "data_path": "/var/lib/adc_alarm_system",  # 数据存储路径
        "log_path": "/var/log/adc_alarm_system",  # 日志路径
        "pid_file": "/var/run/adc_alarm_system.pid",
        "config_file": "/etc/adc_alarm_system.conf"
    },
    
    # 网络配置
    "network": {
        "auto_detect_ip": True,
        "default_ip": "0.0.0.0",  # 绑定所有接口
        "broadcast_port": 5439,
        "listen_port": 5439,
        "web_port": 8081,
        "max_connections": 50,  # 限制并发连接数
        "socket_timeout": 30,
        "buffer_size": 1024
    },
    
    # 资源限制
    "resources": {
        "max_devices": 100,  # 最大设备数量
        "max_log_size": "10MB",  # 单个日志文件最大大小
        "max_log_files": 5,  # 最大日志文件数量
        "cache_size": 1000,  # 缓存大小
        "cleanup_interval": 300,  # 清理间隔(秒)
        "heartbeat_timeout": 180,  # 心跳超时(秒)
        "offline_timeout": 300,  # 离线超时(秒)
    },
    
    # 性能优化
    "performance": {
        "thread_pool_size": 4,  # 线程池大小
        "queue_size": 1000,  # 队列大小
        "batch_size": 10,  # 批处理大小
        "flush_interval": 5,  # 刷新间隔(秒)
        "compression": True,  # 启用压缩
        "async_logging": True,  # 异步日志
    },
    
    # 硬件接口配置
    "hardware": {
        "gpio_available": True,
        "uart_ports": ["/dev/ttyS0", "/dev/ttyS1", "/dev/ttyS2"],
        "i2c_buses": ["/dev/i2c-0", "/dev/i2c-1"],
        "spi_devices": ["/dev/spidev0.0", "/dev/spidev0.1"],
        "led_gpio": 18,  # 状态LED GPIO
        "button_gpio": 19,  # 按钮GPIO
    },
    
    # 存储配置
    "storage": {
        "database_type": "sqlite",  # 使用SQLite减少资源消耗
        "database_path": "/var/lib/adc_alarm_system/devices.db",
        "backup_enabled": True,
        "backup_interval": 3600,  # 1小时备份一次
        "backup_retention": 7,  # 保留7天备份
        "sync_interval": 60,  # 同步间隔(秒)
    }
}

class EmbeddedConfig:
    """嵌入式环境配置管理器"""
    
    def __init__(self):
        self.config = EMBEDDED_CONFIG.copy()
        self.logger = self._setup_logging()
        
    def _setup_logging(self):
        """设置日志配置"""
        log_dir = Path(self.config["system"]["log_path"])
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置日志轮转
        from logging.handlers import RotatingFileHandler
        
        logger = logging.getLogger("adc_alarm_system")
        logger.setLevel(logging.INFO)
        
        # 文件处理器
        file_handler = RotatingFileHandler(
            log_dir / "middleware.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        logger.addHandler(file_handler)
        
        # 控制台处理器（仅错误级别）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(
            logging.Formatter('%(levelname)s: %(message)s')
        )
        logger.addHandler(console_handler)
        
        return logger
    
    def get_local_ip(self):
        """获取本地IP地址"""
        try:
            # 尝试多种方法获取IP
            methods = [
                self._get_ip_from_route,
                self._get_ip_from_interface,
                self._get_ip_from_socket
            ]
            
            for method in methods:
                try:
                    ip = method()
                    if ip and ip != "127.0.0.1":
                        return ip
                except Exception:
                    continue
                    
            return self.config["network"]["default_ip"]
            
        except Exception as e:
            self.logger.warning(f"获取IP地址失败: {e}")
            return self.config["network"]["default_ip"]
    
    def _get_ip_from_route(self):
        """从路由表获取IP"""
        result = subprocess.run(
            ["ip", "route", "get", "8.8.8.8"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'src' in line:
                    return line.split('src')[1].split()[0]
        return None
    
    def _get_ip_from_interface(self):
        """从网络接口获取IP"""
        result = subprocess.run(
            ["ip", "addr", "show"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for line in lines:
                if 'inet ' in line and '127.0.0.1' not in line:
                    return line.split('inet ')[1].split('/')[0]
        return None
    
    def _get_ip_from_socket(self):
        """通过socket获取IP"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    
    def check_system_requirements(self):
        """检查系统要求"""
        checks = {
            "python_version": self._check_python_version(),
            "memory": self._check_memory(),
            "storage": self._check_storage(),
            "network": self._check_network(),
            "permissions": self._check_permissions()
        }
        
        all_passed = all(checks.values())
        
        if not all_passed:
            self.logger.error("系统要求检查失败:")
            for check, result in checks.items():
                if not result:
                    self.logger.error(f"  - {check}: 失败")
        
        return all_passed, checks
    
    def _check_python_version(self):
        """检查Python版本"""
        import sys
        return sys.version_info >= (3, 6)
    
    def _check_memory(self):
        """检查内存"""
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        mem_kb = int(line.split()[1])
                        mem_mb = mem_kb / 1024
                        return mem_mb >= 256  # 至少256MB
        except:
            return True  # 无法检查时假设通过
    
    def _check_storage(self):
        """检查存储空间"""
        try:
            import shutil
            total, used, free = shutil.disk_usage('/')
            free_mb = free / (1024 * 1024)
            return free_mb >= 100  # 至少100MB空闲空间
        except:
            return True
    
    def _check_network(self):
        """检查网络"""
        try:
            # 检查网络接口
            result = subprocess.run(
                ["ip", "link", "show"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except:
            return True
    
    def _check_permissions(self):
        """检查权限"""
        try:
            # 检查是否可以创建必要目录
            test_dirs = [
                self.config["system"]["data_path"],
                self.config["system"]["log_path"]
            ]
            
            for dir_path in test_dirs:
                Path(dir_path).mkdir(parents=True, exist_ok=True)
            
            return True
        except PermissionError:
            return False
        except:
            return True
    
    def create_directories(self):
        """创建必要的目录"""
        dirs = [
            self.config["system"]["storage_path"],
            self.config["system"]["data_path"],
            self.config["system"]["log_path"],
            Path(self.config["system"]["config_file"]).parent
        ]
        
        for dir_path in dirs:
            try:
                Path(dir_path).mkdir(parents=True, exist_ok=True)
                self.logger.info(f"创建目录: {dir_path}")
            except Exception as e:
                self.logger.error(f"创建目录失败 {dir_path}: {e}")
                raise
    
    def save_config(self):
        """保存配置到文件"""
        config_file = self.config["system"]["config_file"]
        try:
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.logger.info(f"配置已保存到: {config_file}")
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
            raise
    
    def load_config(self):
        """从文件加载配置"""
        config_file = self.config["system"]["config_file"]
        try:
            if Path(config_file).exists():
                with open(config_file, 'r') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
                self.logger.info(f"配置已从文件加载: {config_file}")
        except Exception as e:
            self.logger.warning(f"加载配置失败，使用默认配置: {e}")
    
    def get_config(self, section=None, key=None):
        """获取配置值"""
        if section is None:
            return self.config
        
        if section not in self.config:
            return None
        
        if key is None:
            return self.config[section]
        
        return self.config[section].get(key)
    
    def update_config(self, section, key, value):
        """更新配置值"""
        if section not in self.config:
            self.config[section] = {}
        
        self.config[section][key] = value
        self.save_config()
    
    def optimize_for_embedded(self):
        """为嵌入式环境优化配置"""
        # 减少内存使用
        self.config["resources"]["max_devices"] = 50
        self.config["resources"]["cache_size"] = 500
        self.config["performance"]["thread_pool_size"] = 2
        self.config["performance"]["queue_size"] = 500
        
        # 优化存储
        self.config["storage"]["sync_interval"] = 300  # 5分钟同步一次
        self.config["resources"]["max_log_size"] = "5MB"
        self.config["resources"]["max_log_files"] = 3
        
        # 优化网络
        self.config["network"]["max_connections"] = 20
        self.config["network"]["socket_timeout"] = 15
        
        self.logger.info("配置已针对嵌入式环境优化")

# 全局配置实例
embedded_config = EmbeddedConfig()

def get_embedded_config():
    """获取嵌入式配置实例"""
    return embedded_config

def init_embedded_environment():
    """初始化嵌入式环境"""
    config = get_embedded_config()
    
    # 加载配置
    config.load_config()
    
    # 检查系统要求
    passed, checks = config.check_system_requirements()
    if not passed:
        raise RuntimeError("系统要求检查失败")
    
    # 创建目录
    config.create_directories()
    
    # 针对嵌入式环境优化
    config.optimize_for_embedded()
    
    # 保存配置
    config.save_config()
    
    return config

if __name__ == "__main__":
    # 测试配置
    try:
        config = init_embedded_environment()
        print("嵌入式环境初始化成功")
        print(f"本地IP: {config.get_local_ip()}")
        print(f"配置文件: {config.config['system']['config_file']}")
    except Exception as e:
        print(f"初始化失败: {e}") 