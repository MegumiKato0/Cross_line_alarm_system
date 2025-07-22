#!/bin/bash

# 网络诊断脚本
# 用于诊断中间件与设备之间的网络连接问题

echo "=== ADC报警系统 - 网络诊断脚本 ==="

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}开始网络诊断...${NC}"

# 1. 检查网络接口
echo -e "${YELLOW}1. 检查网络接口...${NC}"
ip addr show | grep -E "inet.*192\.168" || echo -e "${RED}未找到192.168网段的网络接口${NC}"

# 2. 检查路由表
echo -e "${YELLOW}2. 检查路由表...${NC}"
ip route show | grep "192.168" || echo -e "${RED}未找到192.168网段的路由${NC}"

# 3. 检查UDP端口监听
echo -e "${YELLOW}3. 检查UDP端口监听...${NC}"
netstat -tulpn | grep ":5439" || echo -e "${RED}端口5439未被监听${NC}"

# 4. 测试到设备的连通性
echo -e "${YELLOW}4. 测试到设备的连通性...${NC}"
if ping -c 3 192.168.0.228 &> /dev/null; then
    echo -e "${GREEN}✓ 到设备192.168.0.228的连通性正常${NC}"
else
    echo -e "${RED}✗ 到设备192.168.0.228的连通性异常${NC}"
fi

# 5. 测试UDP广播
echo -e "${YELLOW}5. 测试UDP广播...${NC}"
echo "发送UDP广播测试包..."
echo -n -e "\xAA\x05\xFF\x00\x00\x55" | nc -u -w1 255.255.255.255 5439 2>/dev/null && echo -e "${GREEN}✓ UDP广播发送成功${NC}" || echo -e "${RED}✗ UDP广播发送失败${NC}"

# 6. 检查防火墙状态
echo -e "${YELLOW}6. 检查防火墙状态...${NC}"
if command -v ufw &> /dev/null; then
    ufw status | grep -q "inactive" && echo -e "${GREEN}✓ UFW防火墙已禁用${NC}" || echo -e "${YELLOW}⚠ UFW防火墙已启用${NC}"
elif command -v iptables &> /dev/null; then
    iptables -L | grep -q "ACCEPT" && echo -e "${GREEN}✓ iptables规则正常${NC}" || echo -e "${YELLOW}⚠ iptables规则可能阻止UDP${NC}"
else
    echo -e "${YELLOW}⚠ 未检测到防火墙管理工具${NC}"
fi

# 7. 检查网络配置
echo -e "${YELLOW}7. 检查网络配置...${NC}"
echo "本机IP地址:"
hostname -I | tr ' ' '\n' | grep "192.168" || echo -e "${RED}未找到192.168网段的IP地址${NC}"

# 8. 测试UDP监听
echo -e "${YELLOW}8. 测试UDP监听...${NC}"
echo "启动临时UDP监听器测试..."
timeout 5 bash -c 'nc -ul 5439 & sleep 1; echo -n -e "\xAA\x00\x01\x00\x24\x55" | nc -u -w1 127.0.0.1 5439; kill %1 2>/dev/null' && echo -e "${GREEN}✓ UDP监听测试成功${NC}" || echo -e "${RED}✗ UDP监听测试失败${NC}"

echo -e "${BLUE}=== 网络诊断完成 ===${NC}"

# 9. 建议
echo -e "${YELLOW}=== 故障排除建议 ===${NC}"
echo "1. 确保中间件服务器和设备在同一网段"
echo "2. 检查防火墙是否阻止UDP端口5439"
echo "3. 确保网络接口配置正确"
echo "4. 尝试重启网络服务"
echo "5. 检查路由器配置"

echo -e "${BLUE}=== 诊断完成 ===${NC}" 