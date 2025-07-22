# ADC报警系统中间件

这是一个基于Python的中间件系统，用于管理ADC报警设备，提供实时监控和远程控制功能。

## 功能特性

- **实时监控**: 通过SSE(Server-Sent Events)实时推送设备状态
- **设备管理**: 远程修改设备ID和立即上报功能
- **Web界面**: 美观的HTML前端界面
- **UDP通信**: 支持上行和下行帧处理
- **设备状态跟踪**: 自动记录设备上线、报警、恢复和心跳信息
- **设备ID迁移**: 修改设备ID后自动迁移设备数据并删除原记录

## 系统架构

```
设备 ──UDP──> 中间件服务器 ──SSE──> Web前端
     <──UDP──          ──HTTP──>
```

## 网络配置

- **服务器IP**: 192.168.0.25
- **监听端口**: 5439 (接收设备上行帧)
- **广播端口**: 5440 (发送设备下行帧)
- **Web端口**: 8081 (Web服务和API)

## 协议格式

### 上行帧 (设备→服务器)
| 字段 | 字节 | 说明 |
|------|------|------|
| 帧头 | 1 | 0xAA |
| 指令 | 1 | 0x00=上线, 0x01=报警, 0x02=恢复, 0x03=心跳 |
| 设备ID | 1 | 1-254 |
| 状态 | 1 | 状态字段 |
| WiFi | 1 | WiFi信号强度 |
| 帧尾 | 1 | 0x55 |

### 下行帧 (服务器→设备)
| 字段 | 字节 | 说明 |
|------|------|------|
| 帧头 | 1 | 0xAA |
| 指令 | 1 | 0x04=修改ID, 0x05=立即上报 |
| 设备ID | 1 | 目标设备ID |
| 状态 | 1 | 新ID(修改ID时) |
| WiFi | 1 | 0x00 |
| 帧尾 | 1 | 0x55 |

## 安装和使用

### 1. 系统要求

- Linux系统
- Python 3.6+
- pip3

### 2. 快速启动

```bash
# 给启动脚本执行权限
chmod +x start_middleware.sh

# 启动系统
./start_middleware.sh
```

### 3. 手动安装

```bash
# 安装依赖
pip3 install -r requirements.txt

# 创建模板目录
mkdir -p templates

# 启动服务器
python3 middleware_server.py
```

### 4. 访问Web界面

启动成功后，打开浏览器访问：
```
http://192.168.0.25:8081
```

## Web界面功能

### 实时监控
- 设备状态实时更新
- 在线设备统计
- 报警设备统计
- 消息计数统计

### 设备管理
- 查看所有设备信息
- 修改设备ID
- 立即上报命令
- 设备历史记录

### 实时日志
- 设备上线/下线记录
- 报警和恢复记录
- 心跳包记录
- 系统操作日志

## API接口

### 获取设备列表
```
GET /api/devices
```

### 获取单个设备信息
```
GET /api/device/<device_id>
```

### 修改设备ID
```
POST /api/modify_device_id
Content-Type: application/json

{
    "current_id": 1,
    "new_id": 10,
    "target_ip": "192.168.1.100"
}
```

### 立即上报
```
POST /api/immediate_report
Content-Type: application/json

{
    "device_id": 1,
    "target_ip": "192.168.1.100"
}
```

### SSE事件流
```
GET /events
```

## 文件结构

```
├── middleware_server.py    # 主服务器程序
├── templates/
│   └── index.html         # Web前端界面
├── requirements.txt       # Python依赖
├── start_middleware.sh    # 启动脚本
├── README.md             # 说明文档
└── middleware.log        # 日志文件
```

## 日志文件

系统会自动生成 `middleware.log` 文件，记录所有操作和错误信息。

## 设备ID修改功能

### 工作原理
1. **注册修改操作**: 当发送设备ID修改命令时，系统会记录待处理的ID修改操作
2. **监听设备响应**: 设备收到修改命令后会用新ID发送上线广播
3. **自动迁移数据**: 系统检测到新ID的上线广播后，自动将原设备数据迁移到新ID
4. **删除原记录**: 迁移完成后，原设备ID的记录会被自动删除
5. **清理过期记录**: 系统定期清理超时的ID修改记录

### 测试ID修改功能
```bash
# 使用测试脚本
python test_id_modification.py modify

# 或者直接调用API
curl -X POST http://192.168.8.90:8081/api/modify_device_id \
  -H "Content-Type: application/json" \
  -d '{"current_id": 1, "new_id": 10, "target_ip": "255.255.255.255"}'
```

### 故障排除

#### 1. 端口占用
如果端口被占用，请检查：
```bash
# 检查端口使用情况
netstat -tulpn | grep 5439
netstat -tulpn | grep 5440
netstat -tulpn | grep 8081
```

#### 2. 权限问题
确保脚本有执行权限：
```bash
chmod +x start_middleware.sh
```

#### 3. 网络配置
确保服务器IP `192.168.8.90` 正确配置在网络接口上：
```bash
ip addr show
```

#### 4. 设备ID修改问题
- 确保原设备在线且响应正常
- 检查虚拟设备是否正确处理下行帧
- 查看中间件日志确认ID修改流程
- 使用测试脚本验证功能

## 开发说明

### 添加新功能
1. 在 `middleware_server.py` 中添加新的API端点
2. 在 `templates/index.html` 中添加前端交互
3. 更新协议定义（如需要）

### 扩展协议
在 `middleware_server.py` 中的协议定义部分添加新的命令类型。

## 许可证

MIT License

## 支持

如有问题，请查看日志文件 `middleware.log` 获取详细错误信息。 