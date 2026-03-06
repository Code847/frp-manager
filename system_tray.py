# -*- coding: utf-8 -*-
"""
Windows系统托盘模块
提供托盘图标、右键菜单（启动/停止/退出）
"""
import os
import sys
import threading
import time
import subprocess
import platform

# 尝试导入pystray，处理可能的导入错误
PYSTRAY_AVAILABLE = False
pystray = None
Image = None
ImageDraw = None

# 日志函数 - 输出到文件
import os as _os
import sys

# 确定日志目录
if getattr(sys, 'frozen', False):
    # 打包环境
    _log_dir = _os.path.join(_os.path.dirname(sys.executable), 'logs')
else:
    # Python环境
    _os.makedirs(_os.path.join(_os.path.dirname(__file__), 'logs'), exist_ok=True)
    _log_dir = _os.path.join(_os.path.dirname(__file__), 'logs')

_log_file = _os.path.join(_log_dir, 'tray_debug.log')

def _log(msg):
    try:
        import time
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"[{timestamp}] {msg}\n"
        with open(_log_file, 'a', encoding='utf-8') as f:
            f.write(log_msg)
    except:
        pass

try:
    import pystray
    PYSTRAY_AVAILABLE = True
    _log("pystray导入成功")
except ImportError as e:
    _log(f"pystray导入失败: {e}")

try:
    from PIL import Image, ImageDraw
    _log("PIL导入成功")
except ImportError as e:
    _log(f"PIL导入失败: {e}")


class SystemTray:
    """系统托盘管理类"""
    
    def __init__(self, frp_manager, config, app, exit_callback=None):
        self.frp_manager = frp_manager
        self.config = config
        self.app = app
        self.icon = None
        self.running = True
        self.frp_status = "已停止"
        self.exit_callback = exit_callback  # 退出回调函数
        
    def create_icon_image(self):
        """创建托盘图标图像"""
        global Image, ImageDraw
        
        _log("[DEBUG] create_icon_image 被调用")
        
        # 动态导入
        if Image is None:
            try:
                from PIL import Image, ImageDraw
                _log("[DEBUG] PIL导入成功 in create_icon_image")
            except ImportError as e:
                _log(f"[ERROR] 无法导入PIL: {e}")
                return None
        
        # 创建一个简单的图标图像
        _log("[DEBUG] 正在创建64x64图像...")
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), color='#667eea')
        draw = ImageDraw.Draw(image)
        _log("[DEBUG] 图像创建完成")
        
        # 绘制一个简单的网络图标形状
        # 圆形背景
        draw.ellipse([8, 8, 56, 56], fill='#764ba2', outline='white', width=2)
        # 内部线条 (类似网络连接)
        draw.line([20, 32, 44, 32], fill='white', width=3)
        draw.line([20, 24, 28, 32], fill='white', width=2)
        draw.line([36, 32, 44, 24], fill='white', width=2)
        draw.line([20, 40, 28, 32], fill='white', width=2)
        draw.line([36, 32, 44, 40], fill='white', width=2)
        
        return image
    
    def create_menu(self):
        """创建右键菜单"""
        # 获取当前FRP状态
        status = self.get_frp_status_text()
        
        menu_items = [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                f"FRP状态: {status}",
                self.do_nothing,
                enabled=False
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "启动FRP",
                self.start_frp,
                enabled=(status == "已停止")
            ),
            pystray.MenuItem(
                "停止FRP",
                self.stop_frp,
                enabled=(status == "运行中")
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "打开Web界面",
                self.open_web_ui
            ),
            pystray.MenuItem(
                "刷新状态",
                self.refresh_status
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "退出",
                self.exit_app
            ),
        ]
        
        return pystray.Menu(*menu_items)
    
    def do_nothing(self, icon, item):
        """空操作"""
        pass
    
    def get_frp_status_text(self):
        """获取FRP状态文本"""
        try:
            status = self.frp_manager.get_frp_status()
            if status.get('running'):
                return "运行中"
            return "已停止"
        except:
            return "已停止"
    
    def start_frp(self, icon, item):
        """启动FRP"""
        try:
            # 使用客户端配置启动
            config_dir = self.config['FRP_CONFIG_DIR']
            config_file = os.path.join(config_dir, 'client_simple.ini')
            
            if not os.path.exists(config_file):
                # 创建默认配置
                with open(config_file, 'w', encoding='utf-8') as f:
                    f.write('''[common]
server_addr = 114.132.239.35
server_port = 7000
token = Rmsz@0718

[hai]
type = tcp
local_ip = 127.0.0.1
local_port = 18789
remote_port = 18789''')
            
            binary_path = os.path.join(self.config['FRP_BIN_DIR'], 'frpc_windows_amd64.exe')
            
            if not os.path.exists(binary_path):
                _log("[ERROR] FRP二进制文件不存在")
                return
            
            # 创建日志文件
            log_file = os.path.join(self.config['FRP_LOG_DIR'], f'frpc_tray_{int(time.time())}.log')
            
            # 启动FRP进程
            subprocess.Popen(
                [binary_path, '-c', config_file],
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0,
                stdout=open(log_file, 'w'),
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE
            )
            
            _log("[INFO] FRP已启动")
            self.refresh_status(None, None)
            
        except Exception as e:
            _log(f"[ERROR] 启动FRP失败: {e}")
    
    def stop_frp(self, icon, item):
        """停止FRP"""
        try:
            # 停止内部进程
            self.frp_manager.stop_frp()
            
            # 杀死系统中的FRP进程
            if platform.system() == 'Windows':
                subprocess.run(['taskkill', '/f', '/im', 'frpc_windows_amd64.exe'], 
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.run(['pkill', '-f', 'frpc'], check=False)
            
            _log("[INFO] FRP已停止")
            self.refresh_status(None, None)
            
        except Exception as e:
            _log(f"[ERROR] 停止FRP失败: {e}")
    
    def open_web_ui(self, icon, item):
        """打开Web界面"""
        try:
            import webbrowser
            webbrowser.open(f"http://localhost:{self.config['WEB_PORT']}")
        except Exception as e:
            _log(f"[ERROR] 打开浏览器失败: {e}")
    
    def refresh_status(self, icon, item):
        """刷新状态并更新菜单"""
        if self.icon:
            self.icon.menu = self.create_menu()
            # 更新托盘提示
            status = self.get_frp_status_text()
            self.icon.title = f"FRP Manager - {status}"
    
    def exit_app(self, icon, item):
        """退出应用程序"""
        _log("[INFO] 正在退出...")
        self.running = False
        
        # 停止FRP
        try:
            self.stop_frp(None, None)
        except:
            pass
        
        # 停止托盘图标
        if self.icon:
            self.icon.stop()
        
        # 调用退出回调
        if self.exit_callback:
            try:
                self.exit_callback()
            except:
                pass
        
        # 退出程序
        os._exit(0)
    
    def run(self):
        """运行系统托盘"""
        global pystray, Image, ImageDraw, PYSTRAY_AVAILABLE
        
        _log("[DEBUG] 开始启动系统托盘...")
        
        # 动态导入pystray
        if pystray is None:
            try:
                import pystray
                _log("[DEBUG] pystray导入成功")
                PYSTRAY_AVAILABLE = True
            except ImportError as e:
                _log(f"[ERROR] pystray库导入失败: {e}")
                return
        
        if not PYSTRAY_AVAILABLE:
            _log("[WARN] pystray库未安装，系统托盘功能不可用")
            return
        
        # 动态导入PIL
        if Image is None or ImageDraw is None:
            try:
                from PIL import Image, ImageDraw
                _log("[DEBUG] PIL导入成功")
            except ImportError as e:
                _log(f"[ERROR] PIL导入失败: {e}")
                return
        
        try:
            # 创建图标
            _log("[DEBUG] 正在创建图标...")
            image = self.create_icon_image()
            if image is None:
                _log("[ERROR] 无法创建托盘图标")
                return
            _log("[DEBUG] 图标创建成功")
            
            # 创建托盘图标
            _log("[DEBUG] 正在创建托盘...")
            self.icon = pystray.Icon(
                "FRP-Manager",
                image,
                "FRP Manager",
                self.create_menu()
            )
            
            # 在单独线程中运行托盘
            self.icon.run_detached()
            _log("[INFO] 系统托盘已启动")
            
            # 启动状态监控线程
            self._start_status_monitor()
            
        except Exception as e:
            _log(f"[ERROR] 系统托盘启动失败: {e}")
    
    def _start_status_monitor(self):
        """启动状态监控线程"""
        def monitor():
            while self.running:
                try:
                    time.sleep(5)  # 每5秒检查一次
                    if self.icon and self.running:
                        # 刷新菜单状态
                        self.icon.menu = self.create_menu()
                except Exception as e:
                    pass
        
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()


def setup_system_tray(frp_manager, config, app, exit_callback=None):
    """设置系统托盘（工厂函数）"""
    global PYSTRAY_AVAILABLE, pystray
    
    _log("[DEBUG] setup_system_tray 被调用")
    _log(f"[DEBUG] 平台: {platform.system()}")
    _log(f"[DEBUG] PYSTRAY_AVAILABLE: {PYSTRAY_AVAILABLE}")
    
    if platform.system() != 'Windows':
        _log("[INFO] 系统托盘仅支持Windows系统")
        return None
    
    if not PYSTRAY_AVAILABLE:
        _log("[DEBUG] 尝试动态导入pystray...")
        try:
            import pystray
            global pystray
            _log("[DEBUG] pystray导入成功")
        except ImportError as e:
            _log(f"[WARN] 请安装pystray: pip install pystray Pillow, 错误: {e}")
            return None
    
    _log("[DEBUG] 正在创建SystemTray...")
    tray = SystemTray(frp_manager, config, app, exit_callback)
    _log("[DEBUG] 正在调用tray.run()...")
    tray.run()
    return tray
