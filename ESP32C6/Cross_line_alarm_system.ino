#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include <esp_sleep.h>
#include <esp_wifi.h>

// ==================== 配置参数 ====================
// WiFi配置 - 请根据实际网络环境修改
const char* ssid = "ZNBC";         // WiFi名称 - 修改为您的WiFi名称
const char* password = "znbc1234"; // WiFi密码 - 修改为您的WiFi密码

// 广播设置
const int broadcastPort = 5439;              // 广播端口 - 与中间件保持一致

// AP模式设置（WiFi连接失败时的备用方案）
const char* apSSID = "ADC_Alarm_Device";     // AP热点名称
const char* apPassword = "12345678";         // AP热点密码
IPAddress apIP(192, 168, 4, 1);              // AP模式IP地址
IPAddress apGateway(192, 168, 4, 1);         // AP模式网关
IPAddress apSubnet(255, 255, 255, 0);        // AP模式子网掩码

// 引脚定义
const int resetButtonPin = D3;  // 重置按钮连接到D3引脚
const int adcInputPin = D0;    // ADC输入引脚
const int voltageOutputPin = D4; // 3.3V输出控制引脚
const int ledPin = LED_BUILTIN;  // 板载LED用于指示状态

// 协议帧定义
const uint8_t FRAME_HEAD = 0xAA;
const uint8_t FRAME_TAIL = 0x55;
const uint8_t FRAME_LENGTH = 6;

// 上行指令定义
const uint8_t CMD_ONLINE = 0x00;     // 上线
const uint8_t CMD_ALARM = 0x01;      // 报警
const uint8_t CMD_RECOVER = 0x02;    // 恢复
const uint8_t CMD_HEARTBEAT = 0x03;  // 心跳包

// 下行指令定义
const uint8_t CMD_MODIFY_ID = 0x04;      // 修改设备ID
const uint8_t CMD_IMMEDIATE_REPORT = 0x05; // 立即上报

// 设备ID定义
const uint8_t ID_BROADCAST = 0xFF;  // 广播ID

// 状态定义
const uint8_t STATUS_NORMAL = 0x00;  // 正常状态
const uint8_t STATUS_ALARM = 0x01;   // 报警状态
const uint8_t STATUS_RECOVER = 0x02; // 恢复状态

// 报警触发源定义
const int ALARM_SOURCE_ADC = 2;  // ADC信号触发
const int ALARM_SOURCE_WAKEUP = 3; // 低功耗唤醒触发

// WiFi状态定义
const int WIFI_DISCONNECTED = 0;
const int WIFI_CONNECTING = 1;
const int WIFI_CONNECTED = 2;
const int WIFI_FAILED = 3;
const int WIFI_RECONNECTING = 4;
const int WIFI_AP_MODE = 5;        // AP热点模式

// LED状态定义
const int LED_OFF = 0;
const int LED_SLOW_BLINK = 1;   // 慢速闪烁
const int LED_FAST_BLINK = 2;   // 快速闪烁
const int LED_SOLID = 3;        // 常亮
const int LED_DOUBLE_BLINK = 4; // 双闪

// 时间常量
const unsigned long debounceDelay = 50;        // 按钮去抖动延迟（毫秒）
const unsigned long wifiRetryInterval = 30000; // WiFi重连间隔（毫秒）
const unsigned long wifiConnectTimeout = 20000; // WiFi连接超时时间（毫秒）
const unsigned long wifiQuickRetryInterval = 5000; // 快速重连间隔（毫秒）
const unsigned long heartbeatInterval = 60000; // 心跳包间隔（1分钟）
const unsigned long ledBlinkInterval = 500;    // LED闪烁间隔（毫秒）
const unsigned long ledSlowBlinkInterval = 1000; // LED慢速闪烁间隔（毫秒）
const unsigned long idleTimeBeforeSleep = 300000; // 闲置5分钟后进入睡眠模式
const unsigned long sleepCheckInterval = 60000; // 睡眠检查间隔（1分钟）
const unsigned long alarmRetryInterval = 5000; // 报警重试间隔（5秒）
const unsigned long maxAlarmRetryInterval = 60000; // 最大报警重试间隔（1分钟）
const unsigned long wifiWaitAfterWakeup = 10000; // 唤醒后等待WiFi连接的时间（10秒）

// ADC配置参数
const int adcThreshold = 1000;    // ADC触发阈值（0-4095）
const unsigned long adcSampleInterval = 100; // ADC采样间隔（毫秒）
const unsigned long voltageOutputDuration = 5000; // 3.3V输出持续时间（毫秒）
const unsigned long adcWakeUpInterval = 2000; // ADC唤醒检查间隔（毫秒）

// ==================== 全局变量 ====================
// 状态变量
int wifiStatus = WIFI_DISCONNECTED;
int wifiReconnectAttempts = 0;
const int maxWifiReconnectAttempts = 5;
bool apModeActive = false;         // AP模式是否激活
bool forceBroadcast = true;        // 强制广播模式
bool systemReady = false;
bool adcTriggered = false;     // ADC信号触发状态
bool alarmActive = false;      // 总报警状态
bool voltageOutputActive = false;
bool sleepMode = false;
bool lowPowerMode = false;
bool pendingAlarmFromWakeup = false;
int pendingAlarmAdcValue = 0;
int pendingAlarmSource = 0;    // 待处理报警来源
int currentLedMode = LED_OFF;

// 设备配置
uint8_t deviceId = 1;  // 固定设备ID
uint8_t currentHeartbeatStatus = STATUS_NORMAL; // 当前心跳包状态

// 时间变量
unsigned long lastDebounceTime = 0;
unsigned long lastWifiRetry = 0;
unsigned long wifiConnectStartTime = 0;
unsigned long lastHeartbeat = 0;
unsigned long lastLedBlink = 0;
unsigned long lastLedSlowBlink = 0;
unsigned long lastAdcSample = 0;
unsigned long lastActivity = 0;
unsigned long voltageOutputStartTime = 0;
unsigned long lastSleepCheck = 0;
unsigned long lastAlarmRetry = 0;
unsigned long wakeupTime = 0;
unsigned long currentRetryInterval = alarmRetryInterval;

// 按钮状态
bool lastButtonState = HIGH;
bool buttonState = HIGH;

// LED状态
bool ledState = false;
bool ledSlowState = false;

// 存储对象
Preferences preferences;

// UDP广播客户端
WiFiUDP udpClient;

// UDP服务器（监听下行帧）
WiFiUDP udpServer;
const int listenPort = 5439;  // 监听端口（和广播端口统一）

// 协议帧结构体
struct ProtocolFrame {
  uint8_t head;     // 帧头 0x55
  uint8_t cmd;      // 指令类型
  uint8_t id;       // 设备ID
  uint8_t status;   // 状态字段
  uint8_t wifi;     // WiFi状态/RSSI
  uint8_t tail;     // 帧尾 0xAA
};

// 报警队列结构
struct AlarmRecord {
  uint8_t cmd;
  uint8_t status;
  unsigned long timestamp;
  int adcValue;
  int alarmSource;
  bool sent;
  int retryCount;
  unsigned long lastRetryTime;
};

// 报警队列
const int MAX_ALARM_QUEUE = 10;
AlarmRecord alarmQueue[MAX_ALARM_QUEUE];
int alarmQueueHead = 0;
int alarmQueueTail = 0;
int alarmQueueSize = 0;

// ==================== 系统初始化 ====================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== ADC检测广播系统 ===");
  Serial.println("版本: 3.6 (自动恢复版)");
  Serial.println("特性: ADC触发报警，自动检测恢复，下行帧支持");
  
  // 初始化存储
  preferences.begin("alarm_system", false);
  
  // 恢复设备ID
  deviceId = preferences.getUChar("device_id", 1);
  Serial.println("设备ID: " + String(deviceId));
  
  // 初始化引脚
  initializePins();
  
  // 初始化报警队列
  initializeAlarmQueue();
  
  // 系统自检
  systemSelfTest();
  
  // 连接WiFi
  startWiFiConnection();
  
  // 等待WiFi连接完成
  waitForWiFiConnection();
  
  // 如果WiFi连接失败且强制广播模式开启，启动AP模式
  if (wifiStatus != WIFI_CONNECTED && forceBroadcast) {
    Serial.println("WiFi连接失败，启动AP模式进行广播");
    startAPMode();
  }
  
  // 发送上线广播（无论WiFi状态如何）
  sendOnlineBroadcast();
  lastHeartbeat = millis();
  
  // 启动UDP监听服务器
  initializeUDPServer();
  
  // 设置ADC唤醒源
  setupADCWakeUp();
  
  // 尝试发送存储的报警
  processPendingAlarms();
  
  systemReady = true;
  lastActivity = millis();
  Serial.println("系统初始化完成");
}

// ==================== 主循环 ====================
void loop() {
  // 更新WiFi状态
  updateWiFiStatus();
  
  // 处理唤醒后的延迟报警
  handleWakeupPendingAlarm();
  
  // 检查是否需要进入睡眠模式
  checkSleepMode();
  
  // 处理ADC信号
  handleADCInput();
  
  // 处理3.3V输出控制
  handleVoltageOutput();
  
  // 处理重置按钮
  handleResetButton();
  
  // 处理下行帧
  handleDownlinkFrames();
  
  // 处理待发送的报警
  processPendingAlarms();
  
  // 发送心跳包
  sendHeartbeat();
  
  // 更新LED状态
  updateLEDStatus();
  
  // 短暂延迟，避免CPU过载
  delay(10);
}

// ==================== 初始化函数 ====================
void initializePins() {
  pinMode(resetButtonPin, INPUT_PULLUP); // 重置按钮（上拉输入）
  pinMode(adcInputPin, INPUT);           // ADC输入引脚
  pinMode(voltageOutputPin, OUTPUT);     // 3.3V输出控制引脚
  pinMode(ledPin, OUTPUT);               // 状态LED
  
  // 初始化输出状态
  digitalWrite(voltageOutputPin, LOW);
  digitalWrite(ledPin, LOW);
  
  Serial.println("引脚初始化完成");
}

void initializeAlarmQueue() {
  // 从存储中恢复未发送的报警
  alarmQueueSize = preferences.getInt("queue_size", 0);
  alarmQueueHead = preferences.getInt("queue_head", 0);
  alarmQueueTail = preferences.getInt("queue_tail", 0);
  
  if (alarmQueueSize > 0) {
    Serial.println("恢复 " + String(alarmQueueSize) + " 个待发送报警");
    for (int i = 0; i < alarmQueueSize && i < MAX_ALARM_QUEUE; i++) {
      String key = "alarm_" + String(i);
      size_t len = preferences.getBytesLength(key.c_str());
      if (len == sizeof(AlarmRecord)) {
        preferences.getBytes(key.c_str(), &alarmQueue[i], len);
      }
    }
  }
}

void systemSelfTest() {
  Serial.println("正在进行系统自检...");
  
  // 测试3.3V输出
  Serial.println("测试3.3V输出...");
  digitalWrite(voltageOutputPin, HIGH);
  delay(200);
  digitalWrite(voltageOutputPin, LOW);
  delay(200);
  
  // 测试LED - 显示不同模式
  Serial.println("测试LED指示...");
  for (int mode = 1; mode <= 4; mode++) {
    setLEDMode(mode);
    delay(400);
  }
  setLEDMode(LED_OFF);
  
  // 测试ADC读取
  int adcValue = analogRead(adcInputPin);
  Serial.println("D0引脚ADC初始值: " + String(adcValue));
  Serial.println("ADC触发阈值: " + String(adcThreshold));
  Serial.println("ADC恢复阈值: " + String(adcThreshold - 100));
  
  // 检查初始ADC状态
  if (adcValue > adcThreshold) {
    Serial.println("警告: ADC初始值超过触发阈值，可能立即触发报警");
  } else if (adcValue < (adcThreshold - 100)) {
    Serial.println("正常: ADC初始值处于恢复状态");
  } else {
    Serial.println("注意: ADC初始值在触发阈值附近");
  }
  
  Serial.println("系统自检完成 - 支持ADC自动恢复");
}

void setupADCWakeUp() {
  // 配置ADC引脚为唤醒源
  esp_sleep_enable_ext1_wakeup(1ULL << adcInputPin, ESP_EXT1_WAKEUP_ANY_HIGH);
  Serial.println("ADC唤醒源配置完成");
}

// ==================== UDP广播处理 ====================
bool sendBroadcastFrame(uint8_t cmd, uint8_t status, uint8_t wifi) {
  // 检查是否有可用的网络连接
  if (wifiStatus != WIFI_CONNECTED && wifiStatus != WIFI_AP_MODE) {
    // 如果强制广播模式，尝试启动AP模式
    if (forceBroadcast && !apModeActive) {
      startAPMode();
      delay(2000); // 等待AP模式启动
    }
    
    if (wifiStatus != WIFI_CONNECTED && wifiStatus != WIFI_AP_MODE) {
      Serial.println("无网络连接，尝试启动AP模式进行广播");
      return false;
    }
  }
  
  // 构建协议帧
  ProtocolFrame frame;
  frame.head = FRAME_HEAD;
  frame.cmd = cmd;
  frame.id = deviceId;
  frame.status = status;
  frame.wifi = wifi;
  frame.tail = FRAME_TAIL;
  
  // 根据当前网络模式选择广播地址
  String targetIP = (wifiStatus == WIFI_AP_MODE) ? "192.168.0.26" : "255.255.255.255";
  
  // 发送UDP广播
  udpClient.beginPacket(targetIP.c_str(), broadcastPort);
  size_t bytesWritten = udpClient.write((uint8_t*)&frame, sizeof(frame));
  bool success = udpClient.endPacket();
  
  // 打印发送的帧（HEX格式）
  Serial.print("广播帧: ");
  printFrameHex((uint8_t*)&frame, sizeof(frame));
  
  if (success && bytesWritten == sizeof(frame)) {
    Serial.println("广播发送成功 -> " + targetIP + ":" + String(broadcastPort));
    return true;
  } else {
    Serial.println("广播发送失败 -> " + targetIP + ":" + String(broadcastPort));
    return false;
  }
}

void printFrameHex(uint8_t* data, size_t length) {
  for (size_t i = 0; i < length; i++) {
    if (data[i] < 0x10) Serial.print("0");
    Serial.print(data[i], HEX);
    Serial.print(" ");
  }
  Serial.println();
}

uint8_t getRSSIValue() {
  if (wifiStatus == WIFI_CONNECTED) {
    int rssi = WiFi.RSSI();
    // 将RSSI转换为0-255范围
    return (uint8_t)constrain(abs(rssi), 0, 255);
  } else if (wifiStatus == WIFI_AP_MODE) {
    // AP模式下返回固定值表示AP模式
    return 200; // 特殊值表示AP模式
  }
  return 0; // 无网络连接
}

// ==================== 广播帧发送函数 ====================
bool sendOnlineBroadcast() {
  Serial.println("发送上线广播");
  return sendBroadcastFrame(CMD_ONLINE, STATUS_NORMAL, getRSSIValue());
}

bool sendAlarmBroadcast() {
  Serial.println("发送报警广播");
  currentHeartbeatStatus = STATUS_ALARM;
  return sendBroadcastFrame(CMD_ALARM, STATUS_NORMAL, getRSSIValue());
}

bool sendRecoverBroadcast() {
  Serial.println("发送恢复广播");
  currentHeartbeatStatus = STATUS_RECOVER;
  return sendBroadcastFrame(CMD_RECOVER, STATUS_NORMAL, getRSSIValue());
}

bool sendHeartbeatBroadcast() {
  Serial.println("发送心跳广播，状态: " + String(currentHeartbeatStatus));
  return sendBroadcastFrame(CMD_HEARTBEAT, currentHeartbeatStatus, getRSSIValue());
}

// ==================== 报警队列管理 ====================
void addAlarmToQueue(uint8_t cmd, uint8_t status, int alarmSource, int adcValue = 0) {
  if (alarmQueueSize >= MAX_ALARM_QUEUE) {
    Serial.println("报警队列已满，移除最旧的报警");
    removeOldestAlarm();
  }
  
  AlarmRecord record;
  record.cmd = cmd;
  record.status = status;
  record.timestamp = millis();
  record.adcValue = adcValue;
  record.alarmSource = alarmSource;
  record.sent = false;
  record.retryCount = 0;
  record.lastRetryTime = 0;
  
  alarmQueue[alarmQueueTail] = record;
  alarmQueueTail = (alarmQueueTail + 1) % MAX_ALARM_QUEUE;
  alarmQueueSize++;
  
  // 保存到存储
  saveAlarmQueue();
  
  Serial.println("报警已添加到队列，指令: " + String(cmd, HEX) + ", 来源: " + String(getAlarmSourceString(alarmSource)));
}

void removeOldestAlarm() {
  if (alarmQueueSize > 0) {
    alarmQueueHead = (alarmQueueHead + 1) % MAX_ALARM_QUEUE;
    alarmQueueSize--;
  }
}

void saveAlarmQueue() {
  preferences.putInt("queue_size", alarmQueueSize);
  preferences.putInt("queue_head", alarmQueueHead);
  preferences.putInt("queue_tail", alarmQueueTail);
  
  for (int i = 0; i < alarmQueueSize && i < MAX_ALARM_QUEUE; i++) {
    int index = (alarmQueueHead + i) % MAX_ALARM_QUEUE;
    String key = "alarm_" + String(i);
    preferences.putBytes(key.c_str(), &alarmQueue[index], sizeof(AlarmRecord));
  }
}

void clearAlarmQueue() {
  alarmQueueSize = 0;
  alarmQueueHead = 0;
  alarmQueueTail = 0;
  preferences.putInt("queue_size", 0);
  preferences.putInt("queue_head", 0);
  preferences.putInt("queue_tail", 0);
}

// ==================== 省电模式管理 ====================
void checkSleepMode() {
  if (millis() - lastSleepCheck < sleepCheckInterval) return;
  
  // 检查是否长时间无活动且无待发送报警和无激活报警
  if (!lowPowerMode && (millis() - lastActivity > idleTimeBeforeSleep) && alarmQueueSize == 0 && !alarmActive) {
    Serial.println("进入低功耗模式");
    enterLowPowerMode();
  }
  
  lastSleepCheck = millis();
}

void enterLowPowerMode() {
  lowPowerMode = true;
  
  // 断开WiFi连接以节省电力
  if (wifiStatus != WIFI_DISCONNECTED) {
    WiFi.disconnect();
    esp_wifi_stop();
    wifiStatus = WIFI_DISCONNECTED;
    wifiReconnectAttempts = 0;
    Serial.println("WiFi已断开，进入省电模式");
  }
  
  // 设置LED为关闭状态
  setLEDMode(LED_OFF);
  
  // 设置定时器唤醒（每2秒检查一次ADC）
  esp_sleep_enable_timer_wakeup(adcWakeUpInterval * 1000);
  
  Serial.println("进入低功耗睡眠模式");
  Serial.flush(); // 确保所有输出都被发送
  
  // 进入睡眠模式
  esp_light_sleep_start();
  
  // 唤醒后检查传感器
  checkSensorsOnWakeUp();
}

void checkSensorsOnWakeUp() {
  int adcValue = analogRead(adcInputPin);
  
  if (adcValue > adcThreshold) {
    Serial.println("低功耗模式下ADC触发唤醒: " + String(adcValue));
    
    // 记录唤醒时间和传感器值，延迟处理报警
    wakeupTime = millis();
    pendingAlarmFromWakeup = true;
    pendingAlarmAdcValue = adcValue;
    pendingAlarmSource = ALARM_SOURCE_WAKEUP;
    
    exitLowPowerMode();
  } else if (adcValue < (adcThreshold - 100) && (adcTriggered || alarmActive)) {
    // 在低功耗模式下检测到ADC恢复
    Serial.println("低功耗模式下检测到ADC恢复: " + String(adcValue));
    
    // 直接处理恢复
    handleADCRecovery(adcValue);
    
    // 退出低功耗模式发送恢复广播
    exitLowPowerMode();
  }
}

void exitLowPowerMode() {
  if (!lowPowerMode) return;
  
  lowPowerMode = false;
  Serial.println("退出低功耗模式");
  
  // 重新初始化WiFi
  esp_wifi_start();
  startWiFiConnection();
  
  // 等待WiFi连接，然后重启UDP监听服务器
  delay(2000);
  if (wifiStatus == WIFI_CONNECTED || wifiStatus == WIFI_AP_MODE) {
    initializeUDPServer();
  }
  
  // 重新设置活动时间
  lastActivity = millis();
  
  Serial.println("已退出低功耗模式，正在重新连接WiFi...");
}

// ==================== 唤醒后延迟报警处理 ====================
void handleWakeupPendingAlarm() {
  if (!pendingAlarmFromWakeup) return;
  
  // 检查是否已等待足够长时间或WiFi已连接
  if (wifiStatus == WIFI_CONNECTED || (millis() - wakeupTime > wifiWaitAfterWakeup)) {
    Serial.println("处理唤醒后的延迟报警，来源: " + String(getAlarmSourceString(pendingAlarmSource)));
    
    // 立即输出3.3V
    triggerVoltageOutput();
    
    // 设置触发状态
    adcTriggered = true;
    alarmActive = true;
    
    // 添加报警到队列
    addAlarmToQueue(CMD_ALARM, STATUS_NORMAL, pendingAlarmSource, pendingAlarmAdcValue);
    
    // 重置待处理状态
    pendingAlarmFromWakeup = false;
    pendingAlarmAdcValue = 0;
    pendingAlarmSource = 0;
    
    Serial.println("唤醒后延迟报警处理完成");
  }
}

// ==================== WiFi管理 ====================
void startWiFiConnection() {
  if (lowPowerMode) return; // 低功耗模式下不连接WiFi
  
  if (wifiStatus == WIFI_CONNECTING || wifiStatus == WIFI_RECONNECTING) return; // 已在连接中
  
  Serial.print("开始连接WiFi: " + String(ssid));
  if (wifiReconnectAttempts > 0) {
    Serial.print(" (重连尝试 " + String(wifiReconnectAttempts) + "/" + String(maxWifiReconnectAttempts) + ")");
  }
  Serial.println();
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  wifiStatus = (wifiReconnectAttempts > 0) ? WIFI_RECONNECTING : WIFI_CONNECTING;
  wifiConnectStartTime = millis();
  lastWifiRetry = millis();
}

void waitForWiFiConnection() {
  if (lowPowerMode) return;
  
  Serial.print("等待WiFi连接");
  unsigned long startTime = millis();
  
  while ((wifiStatus == WIFI_CONNECTING || wifiStatus == WIFI_RECONNECTING) && (millis() - startTime) < wifiConnectTimeout) {
    updateWiFiStatus();
    delay(500);
    Serial.print(".");
  }
  
  if (wifiStatus == WIFI_CONNECTED) {
    Serial.println("\nWiFi连接成功");
    Serial.println("IP地址: " + WiFi.localIP().toString());
    Serial.println("信号强度: " + String(WiFi.RSSI()) + " dBm");
    wifiReconnectAttempts = 0; // 重置重连尝试次数
  } else {
    Serial.println("\nWiFi连接超时");
  }
}

void updateWiFiStatus() {
  if (lowPowerMode) return; // 低功耗模式下不检查WiFi
  
  wl_status_t currentStatus = WiFi.status();
  
  switch (wifiStatus) {
    case WIFI_DISCONNECTED:
      // 决定重连策略
      if (wifiReconnectAttempts < maxWifiReconnectAttempts) {
        unsigned long retryInterval = (wifiReconnectAttempts > 0) ? wifiQuickRetryInterval : wifiRetryInterval;
        if (millis() - lastWifiRetry > retryInterval) {
          wifiReconnectAttempts++;
          startWiFiConnection();
        }
      } else {
        // 超过最大重连次数，等待更长时间
        if (millis() - lastWifiRetry > wifiRetryInterval) {
          wifiReconnectAttempts = 0; // 重置计数器
          Serial.println("重置WiFi重连尝试计数器");
        }
      }
      break;
      
    case WIFI_CONNECTING:
    case WIFI_RECONNECTING:
      if (currentStatus == WL_CONNECTED) {
        wifiStatus = WIFI_CONNECTED;
        wifiReconnectAttempts = 0;
        Serial.println("WiFi连接成功");
        
        // 重新启动UDP监听服务器
        initializeUDPServer();
      } else if (millis() - wifiConnectStartTime > wifiConnectTimeout) {
        wifiStatus = WIFI_FAILED;
        Serial.println("WiFi连接超时");
      }
      break;
      
    case WIFI_CONNECTED:
      if (currentStatus != WL_CONNECTED) {
        wifiStatus = WIFI_DISCONNECTED;
        Serial.println("WiFi连接断开，准备重连");
      }
      break;
      
           case WIFI_FAILED:
         // 等待重试间隔后重新尝试
         if (millis() - lastWifiRetry > wifiRetryInterval) {
           // 如果强制广播模式开启且AP模式未激活，启动AP模式
           if (forceBroadcast && !apModeActive) {
             startAPMode();
           } else {
             wifiStatus = WIFI_DISCONNECTED;
             Serial.println("准备重新连接WiFi");
           }
         }
         break;
         
       case WIFI_AP_MODE:
         // AP模式下定期尝试连接原WiFi网络
         if (millis() - lastWifiRetry > wifiRetryInterval * 2) {
           Serial.println("AP模式下尝试连接原WiFi网络");
           wifiStatus = WIFI_DISCONNECTED;
           apModeActive = false;
         }
         break;
  }
}

// ==================== 传感器处理 ====================
void handleADCInput() {
  // 如果有待处理的唤醒报警，且来源不是ADC，则跳过
  if (pendingAlarmFromWakeup && pendingAlarmSource != ALARM_SOURCE_WAKEUP && pendingAlarmSource != ALARM_SOURCE_ADC) return;
  
  // 定期采样ADC
  if (millis() - lastAdcSample > adcSampleInterval) {
    int adcValue = analogRead(adcInputPin);
    
    // 检查是否超过阈值
    if (adcValue > adcThreshold && !adcTriggered && !alarmActive) {
      handleADCTrigger(adcValue);
    }
    
    // 如果ADC值降低，自动发送恢复信号
    if (adcValue < (adcThreshold - 100) && adcTriggered && alarmActive) {
      handleADCRecovery(adcValue);
    }
    
    lastAdcSample = millis();
  }
}

void handleADCTrigger(int adcValue) {
  adcTriggered = true;
  alarmActive = true;
  lastActivity = millis(); // 更新活动时间
  
  Serial.println("D0引脚ADC信号触发: " + String(adcValue));
  
  // 如果在低功耗模式下，先退出
  if (lowPowerMode) {
    exitLowPowerMode();
  }
  
  // 立即输出3.3V
  triggerVoltageOutput();
  
  // 添加报警到队列
  addAlarmToQueue(CMD_ALARM, STATUS_NORMAL, ALARM_SOURCE_ADC, adcValue);
}

void handleADCRecovery(int adcValue) {
  // 重置所有触发状态
  adcTriggered = false;
  alarmActive = false;
  lastActivity = millis(); // 更新活动时间
  
  Serial.println("D0引脚ADC信号恢复正常: " + String(adcValue));
  
  // 关闭3.3V输出（如果还在输出）
  if (voltageOutputActive) {
    digitalWrite(voltageOutputPin, LOW);
    voltageOutputActive = false;
    Serial.println("ADC恢复 - 3.3V输出关闭");
  }
  
  // 重置唤醒待处理状态
  pendingAlarmFromWakeup = false;
  pendingAlarmAdcValue = 0;
  pendingAlarmSource = 0;
  
  // 如果在低功耗模式下，先退出
  if (lowPowerMode) {
    exitLowPowerMode();
  }
  
  // 添加自动恢复广播到队列
  addAlarmToQueue(CMD_RECOVER, STATUS_NORMAL, ALARM_SOURCE_ADC, adcValue);
  
  // 记录自动恢复时间
  preferences.putULong("last_auto_recover", millis());
  
  Serial.println("ADC自动恢复完成");
}

void handleVoltageOutput() {
  // 检查是否需要关闭3.3V输出
  if (voltageOutputActive && (millis() - voltageOutputStartTime > voltageOutputDuration)) {
    digitalWrite(voltageOutputPin, LOW);
    voltageOutputActive = false;
    Serial.println("3.3V输出关闭");
  }
}

void handleResetButton() {
  bool reading = digitalRead(resetButtonPin);
  
  // 按钮状态改变时重置去抖动计时器
  if (reading != lastButtonState) {
    lastDebounceTime = millis();
  }
  
  // 去抖动处理
  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != buttonState) {
      buttonState = reading;
      
      // 按钮被按下（低电平）
      if (buttonState == LOW) {
        Serial.println("重置按钮被按下");
        resetAlarm();
        lastActivity = millis(); // 更新活动时间
      }
    }
  }
  
  lastButtonState = reading;
}

// ==================== 报警控制 ====================
void resetAlarm() {
  // 检查是否已经恢复（避免重复操作）
  if (!adcTriggered && !alarmActive) {
    Serial.println("系统已处于正常状态，无需重置");
    return;
  }
  
  // 重置所有触发状态
  adcTriggered = false;
  alarmActive = false;
  
  // 重置唤醒待处理状态
  pendingAlarmFromWakeup = false;
  pendingAlarmAdcValue = 0;
  pendingAlarmSource = 0;
  
  // 关闭3.3V输出
  if (voltageOutputActive) {
    digitalWrite(voltageOutputPin, LOW);
    voltageOutputActive = false;
    Serial.println("手动重置 - 3.3V输出关闭");
  }
  
  // 如果在低功耗模式下，先退出
  if (lowPowerMode) {
    exitLowPowerMode();
  }
  
  // 添加手动恢复广播到队列
  addAlarmToQueue(CMD_RECOVER, STATUS_NORMAL, ALARM_SOURCE_ADC, 0);
  
  // 记录手动重置时间
  preferences.putULong("last_manual_reset", millis());
  
  Serial.println("手动重置完成");
}

// ==================== 电压输出控制 ====================
void triggerVoltageOutput() {
  digitalWrite(voltageOutputPin, HIGH);
  voltageOutputActive = true;
  voltageOutputStartTime = millis();
  Serial.println("3.3V输出启动，持续时间: " + String(voltageOutputDuration) + "ms");
}

// ==================== AP模式管理 ====================
void startAPMode() {
  if (apModeActive) return;
  
  Serial.println("启动AP热点模式");
  
  // 停止STA模式
  WiFi.disconnect();
  
  // 配置AP模式
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(apIP, apGateway, apSubnet);
  
  if (WiFi.softAP(apSSID, apPassword)) {
    apModeActive = true;
    wifiStatus = WIFI_AP_MODE;
    Serial.println("AP模式启动成功");
    Serial.println("AP名称: " + String(apSSID));
    Serial.println("AP密码: " + String(apPassword));
    Serial.println("AP IP: " + WiFi.softAPIP().toString());
    Serial.println("广播地址: 192.168.4.255");
    
    // 启动UDP监听服务器
    initializeUDPServer();
  } else {
    Serial.println("AP模式启动失败");
    wifiStatus = WIFI_FAILED;
  }
}

// ==================== 网络通信 ====================
void initializeUDPServer() {
  // 只在有网络连接时启动UDP监听
  if (wifiStatus == WIFI_CONNECTED || wifiStatus == WIFI_AP_MODE) {
    if (udpServer.begin(listenPort)) {
      Serial.println("UDP监听服务器启动成功，端口: " + String(listenPort));
    } else {
      Serial.println("UDP监听服务器启动失败");
    }
  } else {
    Serial.println("无网络连接，跳过UDP监听服务器启动");
  }
}

void handleDownlinkFrames() {
  // 检查网络连接状态
  if (wifiStatus != WIFI_CONNECTED && wifiStatus != WIFI_AP_MODE) {
    return;
  }
  
  // 检查是否有可用的UDP数据包
  int packetSize = udpServer.parsePacket();
  if (packetSize) {
    // 检查数据包大小是否符合协议帧长度
    if (packetSize == FRAME_LENGTH) {
      uint8_t incomingPacket[FRAME_LENGTH];
      
      // 读取数据包
      int bytesRead = udpServer.read(incomingPacket, FRAME_LENGTH);
      
      if (bytesRead == FRAME_LENGTH) {
        // 验证帧头和帧尾
        if (incomingPacket[0] == FRAME_HEAD && incomingPacket[5] == FRAME_TAIL) {
          // 解析协议帧
          ProtocolFrame frame;
          frame.head = incomingPacket[0];
          frame.cmd = incomingPacket[1];
          frame.id = incomingPacket[2];
          frame.status = incomingPacket[3];
          frame.wifi = incomingPacket[4];
          frame.tail = incomingPacket[5];
          
          // 检查是否是发送给本设备的帧（设备ID匹配或广播）
          if (frame.id == deviceId || frame.id == ID_BROADCAST) {
            Serial.print("接收到下行帧: ");
            printFrameHex(incomingPacket, FRAME_LENGTH);
            
            // 处理不同的下行命令
            switch (frame.cmd) {
              case CMD_MODIFY_ID:
                processModifyIDCommand(frame);
                break;
              case CMD_IMMEDIATE_REPORT:
                processImmediateReportCommand(frame);
                break;
              default:
                Serial.println("未知的下行指令: " + String(frame.cmd, HEX));
                break;
            }
          }
        } else {
          Serial.println("接收到无效的协议帧（帧头/帧尾错误）");
        }
      }
    } else {
      Serial.println("接收到长度不符的数据包，长度: " + String(packetSize) + "，期望: " + String(FRAME_LENGTH));
    }
  }
}

void processModifyIDCommand(ProtocolFrame frame) {
  uint8_t newID = frame.status;  // 新设备ID存储在status字段
  uint8_t oldID = deviceId;      // 保存旧ID用于日志
  
  Serial.println("=== 接收到修改设备ID命令 ===");
  Serial.println("当前设备ID: " + String(oldID));
  Serial.println("请求新设备ID: " + String(newID));
  Serial.println("来源IP: " + udpServer.remoteIP().toString());
  
  // 验证新ID的有效性
  if (newID == 0) {
    Serial.println("❌ 新设备ID无效：ID不能为0");
    return;
  }
  
  if (newID == ID_BROADCAST) {
    Serial.println("❌ 新设备ID无效：ID不能为广播ID (0xFF)");
    return;
  }
  
  
  if (newID == oldID) {
    Serial.println("⚠️ 新设备ID与当前ID相同，无需修改");
    return;
  }
  
  if (newID > 254) {
    Serial.println("❌ 新设备ID无效：ID超出范围 (1-254)");
    return;
  }
  
  // 更新设备ID
  deviceId = newID;
  
  // 保存到存储
  bool saveSuccess = preferences.putUChar("device_id", deviceId);
  
  if (saveSuccess) {
    Serial.println("✅ 设备ID已成功保存到存储");
  } else {
    Serial.println("❌ 设备ID保存到存储失败");
  }
  
  // 发送确认响应（立即上报新ID）
  Serial.println("发送ID修改确认广播...");
  bool broadcastSuccess = sendOnlineBroadcast();
  
  if (broadcastSuccess) {
    Serial.println("✅ ID修改确认广播发送成功");
  } else {
    Serial.println("❌ ID修改确认广播发送失败");
  }
  
  // 记录ID修改历史
  unsigned long currentTime = millis();
  preferences.putULong("last_id_change", currentTime);
  preferences.putUChar("previous_device_id", oldID);
  
  Serial.println("=== 设备ID修改完成 ===");
  Serial.println("旧ID: " + String(oldID) + " → 新ID: " + String(deviceId));
  Serial.println("修改时间: " + String(currentTime / 1000) + " 秒");
  Serial.println("存储状态: " + String(saveSuccess ? "成功" : "失败"));
  Serial.println("广播状态: " + String(broadcastSuccess ? "成功" : "失败"));
  Serial.println("========================\n");
}

void processImmediateReportCommand(ProtocolFrame frame) {
  Serial.println("接收到立即上报命令");
  
  // 立即发送当前状态
  if (alarmActive) {
    sendAlarmBroadcast();
  } else {
    sendOnlineBroadcast();
  }
  
  // 更新活动时间
  lastActivity = millis();
  
  Serial.println("立即上报命令执行完成");
}

void processPendingAlarms() {
  if ((wifiStatus != WIFI_CONNECTED && wifiStatus != WIFI_AP_MODE) || alarmQueueSize == 0) return;
  
  // 智能重试机制：根据失败次数调整重试间隔
  unsigned long currentTime = millis();
  
  // 尝试发送队列中的报警
  for (int i = 0; i < alarmQueueSize; i++) {
    int index = (alarmQueueHead + i) % MAX_ALARM_QUEUE;
    AlarmRecord* record = &alarmQueue[index];
    
    if (!record->sent) {
      // 检查是否到了重试时间
      unsigned long retryInterval = min(currentRetryInterval * (1 << record->retryCount), maxAlarmRetryInterval);
      
      if (record->retryCount == 0 || (currentTime - record->lastRetryTime > retryInterval)) {
        if (sendBroadcastFrame(record->cmd, record->status, (record->cmd == CMD_HEARTBEAT) ? getRSSIValue() : getRSSIValue())) {
          record->sent = true;
          saveAlarmQueue();
          Serial.println("报警广播成功，指令: " + String(record->cmd, HEX) + ", 重试次数: " + String(record->retryCount));
          
          // 重置重试间隔
          currentRetryInterval = alarmRetryInterval;
        } else {
          record->retryCount++;
          record->lastRetryTime = currentTime;
          Serial.println("报警广播失败，重试次数: " + String(record->retryCount) + ", 下次重试间隔: " + String(retryInterval) + "ms");
          
          // 增加重试间隔
          currentRetryInterval = min(currentRetryInterval * 2, maxAlarmRetryInterval);
          
          // 如果重试次数过多，记录到存储供后续分析
          if (record->retryCount > 10) {
            preferences.putInt("failed_alarms", preferences.getInt("failed_alarms", 0) + 1);
          }
          
          return; // 发送失败，处理下一个报警
        }
      }
    }
  }
  
  // 清理已发送的报警
  cleanupSentAlarms();
}

void cleanupSentAlarms() {
  while (alarmQueueSize > 0) {
    int headIndex = alarmQueueHead;
    if (alarmQueue[headIndex].sent) {
      removeOldestAlarm();
      saveAlarmQueue();
    } else {
      break;
    }
  }
}

void sendHeartbeat() {
  if ((wifiStatus != WIFI_CONNECTED && wifiStatus != WIFI_AP_MODE) || !systemReady || lowPowerMode) return;
  
  if (millis() - lastHeartbeat > heartbeatInterval) {
    Serial.println("发送心跳广播");
    addAlarmToQueue(CMD_HEARTBEAT, currentHeartbeatStatus, ALARM_SOURCE_ADC, 0);
    lastHeartbeat = millis();
  }
}

// ==================== LED状态指示 ====================
void setLEDMode(int mode) {
  currentLedMode = mode;
}

void updateLEDStatus() {
  if (lowPowerMode) {
    setLEDMode(LED_OFF);
  } else {
    // 根据系统状态设置LED模式
    if (pendingAlarmFromWakeup) {
      setLEDMode(LED_DOUBLE_BLINK); // 唤醒后待处理报警
    } else if (alarmActive) {
      setLEDMode(LED_FAST_BLINK); // 激活报警状态
    } else if (adcTriggered || alarmQueueSize > 0) {
      setLEDMode(LED_FAST_BLINK); // 有报警或待发送报警
         } else if (wifiStatus == WIFI_CONNECTING || wifiStatus == WIFI_RECONNECTING) {
       setLEDMode(LED_FAST_BLINK); // WiFi连接中
     } else if (wifiStatus == WIFI_AP_MODE) {
       setLEDMode(LED_DOUBLE_BLINK); // AP热点模式
     } else if (wifiStatus == WIFI_FAILED) {
       setLEDMode(LED_SLOW_BLINK); // WiFi连接失败
     } else if (wifiStatus != WIFI_CONNECTED) {
       setLEDMode(LED_SLOW_BLINK); // WiFi未连接
    } else {
      setLEDMode(LED_SOLID); // 正常状态
    }
  }
  
  // 执行LED控制
  switch (currentLedMode) {
    case LED_OFF:
      digitalWrite(ledPin, LOW);
      break;
      
    case LED_SOLID:
      digitalWrite(ledPin, HIGH);
      break;
      
    case LED_FAST_BLINK:
      if (millis() - lastLedBlink > ledBlinkInterval) {
        ledState = !ledState;
        digitalWrite(ledPin, ledState);
        lastLedBlink = millis();
      }
      break;
      
    case LED_SLOW_BLINK:
      if (millis() - lastLedSlowBlink > ledSlowBlinkInterval) {
        ledSlowState = !ledSlowState;
        digitalWrite(ledPin, ledSlowState);
        lastLedSlowBlink = millis();
      }
      break;
      
    case LED_DOUBLE_BLINK:
      // 双闪模式：快速闪烁两次，然后暂停
      if (millis() - lastLedBlink > ledBlinkInterval) {
        static int blinkCount = 0;
        ledState = !ledState;
        digitalWrite(ledPin, ledState);
        
        if (!ledState) {
          blinkCount++;
          if (blinkCount >= 2) {
            blinkCount = 0;
            delay(500); // 暂停500ms
          }
        }
        
        lastLedBlink = millis();
      }
      break;
  }
}

// ==================== 辅助函数 ====================
String getAlarmSourceString(int source) {
  switch (source) {
    case ALARM_SOURCE_ADC: return "ADC信号";
    case ALARM_SOURCE_WAKEUP: return "低功耗唤醒";
    default: return "未知";
  }
}

String getWiFiStatusString() {
  switch (wifiStatus) {
    case WIFI_DISCONNECTED: return "未连接";
    case WIFI_CONNECTING: return "连接中";
    case WIFI_CONNECTED: return "已连接";
    case WIFI_FAILED: return "连接失败";
    case WIFI_RECONNECTING: return "重连中";
    case WIFI_AP_MODE: return "AP热点模式";
    default: return "未知";
  }
}

String getLEDModeString() {
  switch (currentLedMode) {
    case LED_OFF: return "关闭";
    case LED_SLOW_BLINK: return "慢速闪烁";
    case LED_FAST_BLINK: return "快速闪烁";
    case LED_SOLID: return "常亮";
    case LED_DOUBLE_BLINK: return "双闪";
    default: return "未知";
  }
}

String getCmdString(uint8_t cmd) {
  switch (cmd) {
    case CMD_ONLINE: return "上线";
    case CMD_ALARM: return "报警";
    case CMD_RECOVER: return "恢复";
    case CMD_HEARTBEAT: return "心跳";
    case CMD_MODIFY_ID: return "修改设备ID";
    case CMD_IMMEDIATE_REPORT: return "立即上报";
    default: return "未知";
  }
}

// ==================== 调试和监控 ====================
void printSystemStatus() {
  Serial.println("\n=== 系统状态 ===");
  Serial.println("设备ID: " + String(deviceId));
  
  // 显示ID修改历史
  unsigned long lastIdChange = preferences.getULong("last_id_change", 0);
  uint8_t previousDeviceId = preferences.getUChar("previous_device_id", 0);
  if (lastIdChange > 0) {
    Serial.println("上次ID修改: " + String(previousDeviceId) + " → " + String(deviceId));
    Serial.println("修改时间: " + String((millis() - lastIdChange) / 1000) + " 秒前");
  }
  
  Serial.println("WiFi状态: " + String(getWiFiStatusString()));
  Serial.println("WiFi重连尝试: " + String(wifiReconnectAttempts) + "/" + String(maxWifiReconnectAttempts));
  Serial.println("AP模式: " + String(apModeActive ? "激活" : "未激活"));
  Serial.println("强制广播: " + String(forceBroadcast ? "开启" : "关闭"));
  Serial.println("ADC状态: " + String(adcTriggered ? "触发" : "正常"));
  Serial.println("总报警状态: " + String(alarmActive ? "激活" : "正常"));
  Serial.println("心跳包状态: " + String(currentHeartbeatStatus));
  Serial.println("3.3V输出: " + String(voltageOutputActive ? "开启" : "关闭"));
  Serial.println("省电模式: " + String(lowPowerMode ? "开启" : "关闭"));
  Serial.println("唤醒待处理报警: " + String(pendingAlarmFromWakeup ? "是" : "否"));
  Serial.println("报警队列大小: " + String(alarmQueueSize));
  Serial.println("当前LED模式: " + String(getLEDModeString()));
  Serial.println("当前重试间隔: " + String(currentRetryInterval) + "ms");
  Serial.println("当前D0引脚ADC值: " + String(analogRead(adcInputPin)));
  Serial.println("运行时间: " + String(millis() / 1000) + " 秒");
  Serial.println("可用内存: " + String(ESP.getFreeHeap()) + " 字节");
  Serial.println("历史发送失败次数: " + String(preferences.getInt("failed_alarms", 0)));
  
  // UDP监听服务器状态
  if (wifiStatus == WIFI_CONNECTED || wifiStatus == WIFI_AP_MODE) {
    Serial.println("UDP监听端口: " + String(listenPort));
  }
  
  // 恢复历史信息
  unsigned long lastAutoRecover = preferences.getULong("last_auto_recover", 0);
  unsigned long lastManualReset = preferences.getULong("last_manual_reset", 0);
  if (lastAutoRecover > 0) {
    Serial.println("最后自动恢复: " + String((millis() - lastAutoRecover) / 1000) + " 秒前");
  }
  if (lastManualReset > 0) {
    Serial.println("最后手动重置: " + String((millis() - lastManualReset) / 1000) + " 秒前");
  }
  
  if (!lowPowerMode) {
    Serial.println("距离进入睡眠模式: " + String((idleTimeBeforeSleep - (millis() - lastActivity)) / 1000) + " 秒");
  }
  
  if (wifiStatus == WIFI_CONNECTED) {
    Serial.println("WiFi信号: " + String(WiFi.RSSI()) + " dBm");
    Serial.println("RSSI值: " + String(getRSSIValue()));
    Serial.println("本地IP: " + WiFi.localIP().toString());
    Serial.println("广播地址: 255.255.255.255:" + String(broadcastPort));
  } else if (wifiStatus == WIFI_AP_MODE) {
    Serial.println("AP模式IP: " + WiFi.softAPIP().toString());
    Serial.println("AP广播地址: 192.168.4.255:" + String(broadcastPort));
    Serial.println("连接的客户端数量: " + String(WiFi.softAPgetStationNum()));
  }
  
  Serial.println("================\n");
}
