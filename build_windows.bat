@echo off
chcp 65001 >nul
title FRP Manager 打包工具

echo ================================================
echo       FRP Manager - Windows 打包工具
echo ================================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3.7+
    pause
    exit /b 1
)

:: 检查PyInstaller
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [信息] 正在安装PyInstaller...
    python -m pip install pyinstaller
)

:: 打包
echo [信息] 开始打包...
python -m PyInstaller frp_manager.spec --noconfirm

if exist "dist\FRP-Manager.exe" (
    echo.
    echo [成功] 打包完成！
    echo [位置] dist\FRP-Manager.exe
    echo [大小] %~z0 bytes
) else (
    echo [错误] 打包失败
)

echo.
pause
