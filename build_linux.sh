#!/bin/bash
# FRP Manager Linux 打包脚本
# 在Linux系统上运行此脚本生成可执行文件

echo "开始打包FRP Manager for Linux..."

# 安装依赖
pip install pyinstaller

# 打包
pyinstaller --name=frp-manager \
    --onedir \
    --console=False \
    --add-data "web_ui.py:." \
    --add-data "frp_manager.py:." \
    --add-data "configs:configs" \
    --add-data "static:static" \
    --add-data "bin:bin" \
    --hidden-import=requests \
    --hidden-import=psutil \
    --hidden-import=flask \
    --hidden-import=gevent \
    --hidden-import=markupsafe \
    --hidden-import=jinja2 \
    --hidden-import=werkzeug \
    --hidden-import=click \
    --hidden-import=itsdangerous \
    --hidden-import=blinker \
    main.py

echo "打包完成！"
echo "可执行文件位置: dist/frp-manager/frp-manager"
