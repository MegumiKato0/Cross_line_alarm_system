#!/bin/bash

# ADC报警系统 - 系统Python启动脚本
# 适用于鲁班猫A0等无法创建虚拟环境的设备

echo "=== ADC报警系统 - 系统Python启动脚本 ==="

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查Python3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: Python3 未安装${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python3 已安装: $(python3 --version)${NC}"

# 检查Flask是否已安装
echo -e "${YELLOW}检查Flask安装状态...${NC}"
if python3 -c "import flask" 2>/dev/null; then
    echo -e "${GREEN}✓ Flask 已安装${NC}"
    FLASK_VERSION=$(python3 -c "import flask; print(flask.__version__)" 2>/dev/null)
    echo "Flask版本: $FLASK_VERSION"
else
    echo -e "${YELLOW}Flask 未安装，尝试安装...${NC}"
    
    # 尝试使用pip3安装
    if command -v pip3 &> /dev/null; then
        echo "使用pip3安装Flask..."
        pip3 install Flask==2.3.3 Werkzeug==2.3.7
    elif python3 -m pip --version &> /dev/null; then
        echo "使用python3 -m pip安装Flask..."
        python3 -m pip install Flask==2.3.3 Werkzeug==2.3.7
    else
        echo -e "${RED}错误: 无法安装Flask，pip不可用${NC}"
        echo -e "${YELLOW}请手动安装Flask:${NC}"
        echo "sudo apt-get install python3-flask"
        echo "或"
        echo "sudo apt-get install python3-pip && pip3 install Flask==2.3.3"
        exit 1
    fi
    
    # 再次检查Flask
    if python3 -c "import flask" 2>/dev/null; then
        echo -e "${GREEN}✓ Flask 安装成功${NC}"
    else
        echo -e "${RED}错误: Flask 安装失败${NC}"
        exit 1
    fi
fi

# 检查必要文件
echo -e "${YELLOW}检查必要文件...${NC}"
if [ ! -f "middleware_server.py" ]; then
    echo -e "${RED}错误: middleware_server.py 文件不存在${NC}"
    exit 1
fi

if [ ! -f "templates/index.html" ]; then
    echo -e "${RED}错误: templates/index.html 文件不存在${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 所有必要文件检查通过${NC}"

# 显示系统信息
echo "===================="
echo "系统信息:"
echo "Python版本: $(python3 --version)"
echo "工作目录: $(pwd)"
echo "用户: $(whoami)"
echo "===================="

# 步骤8: 启动服务器
echo -e "${GREEN}=== 开始启动服务器 ===${NC}"
echo "服务器地址: http://192.168.0.25:8081"
echo "按 Ctrl+C 停止服务器"
echo "===================="

# 使用系统Python运行服务器
python3 middleware_server.py 