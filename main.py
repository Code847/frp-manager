#!/usr/bin/env python3
import os
import sys
import platform
import threading
import subprocess
import importlib
import time

# 单实例检查 - 使用文件锁
def check_single_instance():
    """检查是否已有实例在运行"""
    # 获取正确的程序目录
    if getattr(sys, 'frozen', False):
        # 打包环境：exe在根目录，_internal里面有temp
        base_dir = os.path.join(os.path.dirname(sys.executable), '_internal')
    else:
        # Python环境
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    lock_file = os.path.join(base_dir, 'temp', 'app.lock')
    pid_file = os.path.join(base_dir, 'temp', 'app.pid')
    
    # 确保temp目录存在
    os.makedirs(os.path.join(base_dir, 'temp'), exist_ok=True)
    
    # 检查锁文件
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("锁文件为空")
                old_pid = int(content)
            
            # 检查旧进程是否还在运行
            if platform.system() == 'Windows':
                result = subprocess.run(['tasklist', '/FI', f'PID eq {old_pid}'], 
                                      capture_output=True, text=True)
                if str(old_pid) in result.stdout:
                    print(f"[ERROR] 程序已在运行中 (PID: {old_pid})")
                    print(f"[ERROR] 请先关闭现有实例，或等待其退出")
                    # GUI 模式下无法使用 input，直接退出
                    if getattr(sys, 'frozen', False):
                        import ctypes
                        ctypes.windll.user32.MessageBoxW(0, f"程序已在运行中 (PID: {old_pid})\n请先关闭现有实例", "FRP Manager", 0x10)
                    else:
                        input("按回车键退出...")
                    sys.exit(1)
        except (ValueError, FileNotFoundError, subprocess.CalledProcessError, EOFError):
            pass  # 锁文件无效，继续启动
    
    # 写入当前PID
    current_pid = os.getpid()
    with open(lock_file, 'w') as f:
        f.write(str(current_pid))
    with open(pid_file, 'w') as f:
        f.write(str(current_pid))
    
    # 注册退出时清理（使用相同的base_dir）
    import atexit
    def cleanup():
        try:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.join(os.path.dirname(sys.executable), '_internal')
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            lock_file = os.path.join(base_dir, 'temp', 'app.lock')
            pid_file = os.path.join(base_dir, 'temp', 'app.pid')
            if os.path.exists(lock_file):
                os.remove(lock_file)
            if os.path.exists(pid_file):
                os.remove(pid_file)
        except:
            pass
    atexit.register(cleanup)
    
    return True

def install_dependencies():
    """检查并安装所需依赖"""
    print(f"[INFO] 正在检查Python依赖...")
    
    required_packages = {
        'flask': 'Flask>=2.0.0',
        'requests': 'requests>=2.25.0',
        'psutil': 'psutil>=5.8.0',
        'pystray': 'pystray>=0.19.5',
        'PIL': 'Pillow>=10.0.0'
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
    # 单实例检查
    check_single_instance()
    
    # 先安装依赖
    install_dependencies()
    
    # 导入依赖（必须在安装后）
    from web_ui import app
    from frp_manager import FRPManager
    
    # 配置 - 打包环境下路径需要调整
    if getattr(sys, 'frozen', False):
        base_dir = os.path.join(os.path.dirname(sys.executable), '_internal')
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    CONFIG = {
        'WEB_PORT': 5000,
        'LOG_LEVEL': 'info',
        'FRP_BIN_DIR': os.path.join(base_dir, 'bin'),
        'FRP_CONFIG_DIR': os.path.join(base_dir, 'configs'),
        'FRP_LOG_DIR': os.path.join(base_dir, 'logs'),
        'TEMP_DIR': os.path.join(base_dir, 'temp')
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
    
    # 启动系统托盘（仅Windows）
    tray = None
    stop_event = None
    
    if platform.system() == 'Windows':
        try:
            # 创建停止事件用于优雅退出
            import threading
            stop_event = threading.Event()
            
            def tray_exit_callback():
                """托盘退出时的回调"""
                if stop_event:
                    stop_event.set()
            
            from system_tray import setup_system_tray
            tray = setup_system_tray(frp_manager, CONFIG, app, tray_exit_callback)
            if tray:
                print(f"[INFO] 系统托盘已启动")
            else:
                print(f"[WARN] 系统托盘功能不可用（缺少pystray库）")
        except ImportError as e:
            print(f"[WARN] 系统托盘功能不可用: {e}")
            print(f"[WARN] 可运行: pip install pystray Pillow 来启用托盘功能")
        except Exception as e:
            print(f"[WARN] 系统托盘启动失败: {e}")
    
    # 启动Web UI线程
    web_thread = threading.Thread(target=start_web_ui, args=(app, frp_manager, CONFIG), daemon=True)
    web_thread.start()
    
    # 保持主程序运行
    
    # 优雅退出函数
    def graceful_exit(signum=None, frame=None):
        print(f"\n[INFO] 正在停止FRP服务...")
        frp_manager.stop_frp()
        print(f"[INFO] 已退出")
        sys.exit(0)
    
    # 注册信号处理（仅Windows）
    if platform.system() == 'Windows':
        try:
            import signal
            signal.signal(signal.SIGINT, graceful_exit)
            signal.signal(signal.SIGTERM, graceful_exit)
        except:
            pass
    
    # 检查是否打包运行
    if getattr(sys, 'frozen', False):
        # 打包环境：使用不依赖stdin的方式
        print(f"[INFO] FRP Manager 已启动")
        print(f"[INFO] 访问 http://localhost:{CONFIG['WEB_PORT']} 进行配置")
        print(f"[INFO] 托盘图标已显示在系统状态栏")
        print(f"[INFO] 点击托盘图标选择'退出'来关闭程序")
        
        try:
            while stop_event is None or not stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            graceful_exit()
        
        graceful_exit()
    else:
        # 正常Python环境
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