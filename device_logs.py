#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

class DeviceLogManager:
    """设备日志管理器"""
    
    def __init__(self, log_dir: str = "device_logs"):
        self.log_dir = log_dir
        self.lock = threading.Lock()
        
        # 创建日志目录
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
    
    def _get_log_file_path(self, device_id: int) -> str:
        """获取设备日志文件路径"""
        return os.path.join(self.log_dir, f"device_{device_id}.json")
    
    def _load_device_logs(self, device_id: int) -> List[Dict]:
        """加载设备日志"""
        log_file = self._get_log_file_path(device_id)
        if not os.path.exists(log_file):
            return []
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    
    def _save_device_logs(self, device_id: int, logs: List[Dict]) -> bool:
        """保存设备日志"""
        log_file = self._get_log_file_path(device_id)
        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
            return True
        except IOError:
            return False
    
    def add_log_entry(self, device_id: int, log_type: str, message: str, 
                     wifi_rssi: int = 0, source_ip: str = "", 
                     additional_data: Optional[Dict] = None) -> bool:
        """添加日志条目"""
        with self.lock:
            logs = self._load_device_logs(device_id)
            
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": log_type,
                "message": message,
                "wifi_rssi": wifi_rssi,
                "source_ip": source_ip
            }
            
            if additional_data:
                log_entry.update(additional_data)
            
            logs.append(log_entry)
            
            # 限制日志条目数量，保留最近的1000条
            if len(logs) > 1000:
                logs = logs[-1000:]
            
            return self._save_device_logs(device_id, logs)
    
    def get_device_logs(self, device_id: int, limit: int = 100) -> List[Dict]:
        """获取设备日志"""
        with self.lock:
            logs = self._load_device_logs(device_id)
            return logs[-limit:] if logs else []
    
    def get_device_log_summary(self, device_id: int) -> Dict:
        """获取设备日志摘要"""
        with self.lock:
            logs = self._load_device_logs(device_id)
            
            if not logs:
                return {
                    "total_logs": 0,
                    "first_log": None,
                    "last_log": None,
                    "log_types": {}
                }
            
            # 统计日志类型
            log_types = {}
            for log in logs:
                log_type = log.get("type", "unknown")
                log_types[log_type] = log_types.get(log_type, 0) + 1
            
            return {
                "total_logs": len(logs),
                "first_log": logs[0]["timestamp"] if logs else None,
                "last_log": logs[-1]["timestamp"] if logs else None,
                "log_types": log_types
            }
    
    def search_logs(self, device_id: int, log_type: Optional[str] = None, 
                   start_time: Optional[str] = None, end_time: Optional[str] = None,
                   limit: int = 100) -> List[Dict]:
        """搜索设备日志"""
        with self.lock:
            logs = self._load_device_logs(device_id)
            
            if not logs:
                return []
            
            # 过滤日志
            filtered_logs = []
            for log in logs:
                # 过滤日志类型
                if log_type and log.get("type") != log_type:
                    continue
                
                # 过滤时间范围
                log_time = log.get("timestamp", "")
                if start_time and log_time < start_time:
                    continue
                if end_time and log_time > end_time:
                    continue
                
                filtered_logs.append(log)
            
            return filtered_logs[-limit:] if filtered_logs else []
    
    def clear_device_logs(self, device_id: int) -> bool:
        """清空设备日志"""
        with self.lock:
            log_file = self._get_log_file_path(device_id)
            try:
                if os.path.exists(log_file):
                    os.remove(log_file)
                return True
            except OSError:
                return False
    
    def get_all_device_ids(self) -> List[int]:
        """获取所有有日志的设备ID"""
        device_ids = []
        for filename in os.listdir(self.log_dir):
            if filename.startswith("device_") and filename.endswith(".json"):
                try:
                    device_id = int(filename[7:-5])  # 提取device_XXX.json中的XXX
                    device_ids.append(device_id)
                except ValueError:
                    continue
        return sorted(device_ids)
    
    def backup_logs(self, backup_dir: str = "backup_logs") -> bool:
        """备份所有日志"""
        try:
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"device_logs_backup_{timestamp}")
            
            import shutil
            shutil.copytree(self.log_dir, backup_path)
            return True
        except Exception:
            return False 