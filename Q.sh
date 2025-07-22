#!/bin/bash

# ADC报警系统 - 一键安装启动脚本
# 适用于鲁班猫A0等嵌入式设备

echo "=== ADC报警系统 - 一键安装启动脚本 ==="

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}请使用sudo运行此脚本${NC}"
    echo "使用方法: sudo $0"
    exit 1
fi

echo -e "${BLUE}开始一键安装和启动...${NC}"

# 显示当前工作目录
echo -e "${BLUE}当前工作目录: $(pwd)${NC}"

# 步骤1: 安装系统依赖
echo -e "${YELLOW}步骤1: 安装系统依赖...${NC}"
apt-get update

# 检查Python版本
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
echo -e "${BLUE}检测到Python版本: $PYTHON_VERSION${NC}"

# 安装Python3和虚拟环境支持
apt-get install -y python3 python3-pip

# 根据Python版本安装对应的venv包
if [[ "$PYTHON_VERSION" == "3.10" ]]; then
    echo -e "${YELLOW}安装python3.10-venv...${NC}"
    apt-get install -y python3.10-venv
elif [[ "$PYTHON_VERSION" == "3.9" ]]; then
    echo -e "${YELLOW}安装python3.9-venv...${NC}"
    apt-get install -y python3.9-venv
elif [[ "$PYTHON_VERSION" == "3.8" ]]; then
    echo -e "${YELLOW}安装python3.8-venv...${NC}"
    apt-get install -y python3.8-venv
elif [[ "$PYTHON_VERSION" == "3.7" ]]; then
    echo -e "${YELLOW}安装python3.7-venv...${NC}"
    apt-get install -y python3.7-venv
else
    echo -e "${YELLOW}尝试安装通用python3-venv...${NC}"
    apt-get install -y python3-venv
fi

# 安装其他可能需要的包
apt-get install -y curl wget git

# 检查Python3安装
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: Python3 安装失败${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 系统依赖安装完成${NC}"

# 步骤2: 创建虚拟环境
echo -e "${YELLOW}步骤2: 创建虚拟环境...${NC}"

# 删除旧的虚拟环境（如果存在）
if [ -d "venv" ]; then
    echo "删除旧的虚拟环境..."
    rm -rf venv
fi

# 创建新的虚拟环境
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo -e "${RED}虚拟环境创建失败，尝试安装ensurepip...${NC}"
    python3 -m ensurepip --upgrade
    if [ $? -eq 0 ]; then
        echo -e "${YELLOW}ensurepip安装成功，再次尝试创建虚拟环境...${NC}"
        python3 -m venv venv
        if [ $? -ne 0 ]; then
            echo -e "${RED}错误: 虚拟环境创建仍然失败${NC}"
            echo -e "${YELLOW}请手动运行: sudo apt-get install python3.${PYTHON_VERSION}-venv${NC}"
            exit 1
        fi
    else
        echo -e "${RED}错误: ensurepip安装失败${NC}"
        echo -e "${YELLOW}请手动运行: sudo apt-get install python3.${PYTHON_VERSION}-venv${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓ 虚拟环境创建完成${NC}"

# 步骤3: 激活虚拟环境并安装Python依赖
echo -e "${YELLOW}步骤3: 安装Python依赖...${NC}"
source venv/bin/activate

# 升级pip
pip install --upgrade pip

# 安装Flask和其他依赖
pip install Flask==2.3.3 Werkzeug==2.3.7

if [ $? -ne 0 ]; then
    echo -e "${RED}错误: Python依赖安装失败${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python依赖安装完成${NC}"

# 步骤4: 创建必要目录
echo -e "${YELLOW}步骤4: 创建必要目录...${NC}"
mkdir -p templates

# 步骤5: 检查必要文件
echo -e "${YELLOW}步骤5: 检查必要文件...${NC}"

# 显示当前目录的文件列表
echo -e "${BLUE}当前目录文件列表:${NC}"
ls -la

# 检查middleware_server.py
if [ ! -f "middleware_server.py" ]; then
    echo -e "${RED}错误: middleware_server.py 文件不存在${NC}"
    echo -e "${YELLOW}请确保在正确的目录中运行此脚本${NC}"
    echo -e "${YELLOW}当前目录: $(pwd)${NC}"
    echo -e "${YELLOW}请切换到包含middleware_server.py的目录${NC}"
    exit 1
else
    echo -e "${GREEN}✓ middleware_server.py 文件存在${NC}"
fi

# 检查templates/index.html
if [ ! -f "templates/index.html" ]; then
    echo -e "${RED}错误: templates/index.html 文件不存在${NC}"
    echo -e "${YELLOW}请确保templates目录中有index.html文件${NC}"
    exit 1
else
    echo -e "${GREEN}✓ templates/index.html 文件存在${NC}"
fi

echo -e "${GREEN}✓ 所有必要文件检查通过${NC}"

# 步骤6: 设置权限
echo -e "${YELLOW}步骤6: 设置权限...${NC}"
chown -R $SUDO_USER:$SUDO_USER .
chmod +x *.sh

echo -e "${GREEN}✓ 权限设置完成${NC}"

# 步骤7: 显示系统信息
echo "===================="
echo "系统信息:"
echo "Python版本: $(python --version)"
echo "Pip版本: $(pip --version)"
echo "工作目录: $(pwd)"
echo "用户: $SUDO_USER"
echo "===================="

# 步骤8: 启动服务器
echo -e "${GREEN}=== 开始启动服务器 ===${NC}"
echo "服务器地址: http://192.168.0.25:8081"
echo "按 Ctrl+C 停止服务器"
echo "===================="

# 切换到普通用户运行服务器
su -c "cd $(pwd) && source venv/bin/activate && python middleware_server.py" $SUDO_USER 