@echo off
chcp 65001 >nul
title FRP Manager
echo ================================================
echo          FRP Manager - 跨平台版
echo ================================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 请先安装Python 3.7+ && pause && exit /b 1
)

:: 检查依赖
python -c "import flask; import requests; import psutil" 2>nul
if errorlevel 1 (
    echo [信息] 正在安装依赖...
    python -m pip install flask requests psutil -i https://pypi.tuna.tsinghua.edu.cn/simple
)

:: 启动
echo [信息] 启动FRP Manager...
python main.py
pause
