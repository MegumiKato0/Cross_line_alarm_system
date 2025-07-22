@echo off
chcp 65001 >nul
echo === ADC Alert System Middleware Startup Script ===

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if pip is installed
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: pip is not installed or not in PATH
    pause
    exit /b 1
)

REM Update pip first
echo Updating pip...
python -m pip install --upgrade pip

REM Create virtual environment (optional)
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate

REM Install dependencies
echo Installing Python dependencies...
pip install Flask==2.3.3 Werkzeug==2.3.7

REM Create templates directory
if not exist templates mkdir templates

REM Check if necessary files exist
if not exist middleware_server.py (
    echo Error: middleware_server.py file does not exist
    pause
    exit /b 1
)

if not exist templates\index.html (
    echo Error: templates\index.html file does not exist
    pause
    exit /b 1
)

REM Start server
echo Starting middleware server...
echo Server address: http://192.168.0.25:8080
echo Press Ctrl+C to stop server
echo ====================

python middleware_server.py

pause 