#!/usr/bin/env python3
import os
import sys
import platform
import threading
import subprocess
import importlib

def install_dependencies():
    """检查并安装所需依赖"""
    print(f"[INFO] 正在检查Python依赖...")
    
    required_packages = {
        'flask': 'Flask>=2.0.0',
        'requests': 'requests>=2.25.0',
        'psutil': 'psutil>=5.8.0'
    }
    
    need_install = []
    for pkg_name, pkg_requirement in required_packages.items():
        try:
            importlib.import_module(pkg_name)
            print(f"[INFO] {pkg_requirement} 已安装")
        except ImportError:
            print(f"[INFO] 缺少依赖: {pkg_requirement}")
            need_install.append(pkg_requirement)
    
    if need_install:
        print(f"[INFO] 正在安装依赖包...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', *need_install], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[INFO] 所有依赖安装成功")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] 依赖安装失败，请手动运行: pip install {' '.join(need_install)}")
            sys.exit(1)

def start_web_ui(app, frp_manager, config):
    """启动Web UI"""
    app.config['FRP_MANAGER'] = frp_manager
    app.config['CONFIG'] = config
    app.run(host='0.0.0.0', port=config['WEB_PORT'], debug=False, use_reloader=False)

def main():
    """主入口"""
    # 先安装依赖
    install_dependencies()
    
    # 导入依赖（必须在安装后）
    from web_ui import app
    from frp_manager import FRPManager
    
    # 配置
    CONFIG = {
        'WEB_PORT': 5000,
        'LOG_LEVEL': 'info',
        'FRP_BIN_DIR': os.path.join(os.path.dirname(__file__), 'bin'),
        'FRP_CONFIG_DIR': os.path.join(os.path.dirname(__file__), 'configs'),
        'FRP_LOG_DIR': os.path.join(os.path.dirname(__file__), 'logs'),
        'TEMP_DIR': os.path.join(os.path.dirname(__file__), 'temp')
    }
    
    # 创建必要的目录
    for dir_path in [CONFIG['FRP_BIN_DIR'], CONFIG['FRP_CONFIG_DIR'], CONFIG['FRP_LOG_DIR'], CONFIG['TEMP_DIR']]:
        os.makedirs(dir_path, exist_ok=True)
    
    # 初始化FRP管理器
    frp_manager = FRPManager(CONFIG)
    
    print(f"[INFO] FRP Manager 启动中...")
    print(f"[INFO] 系统平台: {platform.system()} {platform.machine()}")
    print(f"[INFO] Web UI 将在 http://localhost:{CONFIG['WEB_PORT']} 启动")
    
    # 检查FRP二进制文件
    if not frp_manager.check_frp_binary():
        print(f"[INFO] 正在下载FRP二进制文件...")
        if frp_manager.download_frp():
            print(f"[INFO] FRP二进制文件下载成功")
        else:
            print(f"[ERROR] FRP二进制文件下载失败，请手动下载")
    
    # 启动Web UI线程
    web_thread = threading.Thread(target=start_web_ui, args=(app, frp_manager, CONFIG), daemon=True)
    web_thread.start()
    
    # 保持主程序运行
    try:
        while True:
            input(f"\n按 Ctrl+C 退出，或访问 http://localhost:{CONFIG['WEB_PORT']} 进行配置\n")
    except KeyboardInterrupt:
        print(f"\n[INFO] 正在停止FRP服务...")
        frp_manager.stop_frp()
        print(f"[INFO] 已退出")
        sys.exit(0)

# 运行主函数
if __name__ == '__main__':
    main()