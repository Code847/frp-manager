#!/bin/bash
# FRP Manager Linux 打包脚本

echo "================================================"
echo "       FRP Manager - Linux Build Script"
echo "================================================"
echo

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python not found"
    exit 1
fi

echo "[INFO] Installing dependencies..."
pip3 install pyinstaller pystray Pillow requests psutil flask

echo "[INFO] Cleaning old builds..."
rm -rf dist build

echo "[INFO] Ensuring temp directory exists..."
mkdir -p temp

echo "[INFO] Building FRP-Manager..."
pyinstaller --name=FRP-Manager \
    --onedir \
    --console \
    --add-data "web_ui.py:." \
    --add-data "frp_manager.py:." \
    --add-data "system_tray.py:." \
    --add-data "configs:configs" \
    --add-data "static:static" \
    --add-data "bin:bin" \
    --add-data "temp:temp" \
    --hidden-import=requests \
    --hidden-import=psutil \
    --hidden-import=flask \
    --hidden-import=markupsafe \
    --hidden-import=jinja2 \
    --hidden-import=werkzeug \
    --hidden-import=click \
    --hidden-import=itsdangerous \
    --hidden-import=blinker \
    --hidden-import=pystray \
    --hidden-import=PIL \
    --hidden-import=Pillow \
    --noconfirm \
    main.py

if [ -f "dist/FRP-Manager/FRP-Manager" ]; then
    echo
    echo "[INFO] Creating temp directory in package..."
    mkdir -p "dist/FRP-Manager/_internal/temp"
    
    echo
    echo "================================================"
    echo "[SUCCESS] Build complete!"
    echo "[FILE] dist/FRP-Manager/FRP-Manager"
    echo "================================================"
else
    echo "[ERROR] Build failed"
fi
