#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FRP Manager 主入口

跨平台：Windows / Linux(x86_64, aarch64/ARM64, armv7l/ARM32) / macOS
ARM 版 Ubuntu 推荐用 systemd 常驻运行，服务模板见 README 的「systemd 常驻」章节
"""
import os
import sys
import time
import atexit
import signal
import argparse
import platform
import threading
import subprocess
import importlib

VERSION = '1.13.2'


# ---------------------------------------------------------------------- #
# 系统托盘（原 system_tray.py，已合并）
#
# Windows / 带图形界面的 Linux 才需要；pystray / Pillow 缺失时自动降级，
# 不影响 Web 面板运行。
# ---------------------------------------------------------------------- #
# 尝试导入pystray，处理可能的导入错误
PYSTRAY_AVAILABLE = False
pystray = None
Image = None
ImageDraw = None



# 确定日志目录
if getattr(sys, 'frozen', False):
    # 打包环境
    _log_dir = os.path.join(os.path.dirname(sys.executable), 'logs')
else:
    # Python环境
    os.makedirs(os.path.join(os.path.dirname(__file__), 'logs'), exist_ok=True)
    _log_dir = os.path.join(os.path.dirname(__file__), 'logs')

_log_file = os.path.join(_log_dir, 'tray_debug.log')

def _log(msg):
    try:
        import time
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"[{timestamp}] {msg}\n"
        with open(_log_file, 'a', encoding='utf-8') as f:
            f.write(log_msg)
    except:
        pass


def setup_headless_output():
    """无控制台时把 stdout / stderr 接到 logs/console.log。

    pythonw / 打包 GUI 下 sys.stdout 与 sys.stderr 都是 None：print 静默丢弃、
    **未捕获异常的 traceback 也一起消失**，启动闪退就成了无头案。
    这里重定向到文件，闪退原因就能查了。
    """
    if getattr(sys, 'stdout', None) is not None and getattr(sys, 'stderr', None) is not None:
        return None
    try:
        os.makedirs(_log_dir, exist_ok=True)
        path = os.path.join(_log_dir, 'console.log')
        f = open(path, 'a', encoding='utf-8', errors='ignore', buffering=1)
        sys.stdout = f
        sys.stderr = f
        f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 "
                f"(PID {os.getpid()}) =====\n")
        return path
    except OSError:
        return None

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
    """系统托盘管理类

    角标颜色与真实进程状态一致（frps/frpc 分别判定），右键菜单支持
    启动 / 重启 / 停止 / 全部停止，并分行展示 FRPS、FRPC 的运行状态。
    """
    MODE_LABEL = {'server': 'FRPS 服务端', 'client': 'FRPC 客户端'}

    def __init__(self, frp_manager, config, app, exit_callback=None):
        self.frp_manager = frp_manager
        self.config = config
        self.app = app
        self.icon = None
        self.running = True
        self.frp_status = "已停止"
        self.exit_callback = exit_callback  # 退出回调函数
        self._op_lock = threading.Lock()    # 启停操作串行化，避免并发打架
        
    def create_icon_image(self, server_running=False, client_running=False):
        """创建托盘图标图像

        颜色：frpc+frps 都在跑=绿，只有一个在跑=橙，都没跑=红；
        底部两个小方块分别是 FRPS(左) / FRPC(右)，亮=运行中。
        """
        global Image, ImageDraw

        # 动态导入
        if Image is None:
            try:
                from PIL import Image, ImageDraw
            except ImportError as e:
                _log(f"[ERROR] 无法导入PIL: {e}")
                return None

        width = height = 64

        if server_running and client_running:
            bg_color, circle_fill = '#16a34a', '#22c55e'      # 全绿
        elif server_running or client_running:
            bg_color, circle_fill = '#b45309', '#f59e0b'      # 橙：部分运行
        else:
            bg_color, circle_fill = '#b91c1c', '#ef4444'      # 红：全部停止

        image = Image.new('RGB', (width, height), color=bg_color)
        draw = ImageDraw.Draw(image)

        # 圆形背景
        draw.ellipse([8, 4, 56, 52], fill=circle_fill, outline='white', width=2)
        # 内部线条 (类似网络连接)
        draw.line([20, 28, 44, 28], fill='white', width=3)
        draw.line([20, 20, 28, 28], fill='white', width=2)
        draw.line([36, 28, 44, 20], fill='white', width=2)
        draw.line([20, 36, 28, 28], fill='white', width=2)
        draw.line([36, 28, 44, 36], fill='white', width=2)

        # 底部状态点：左 FRPS / 右 FRPC
        def dot(x, on):
            draw.rectangle([x, 55, x + 11, 63],
                           fill=(34, 197, 94) if on else (96, 96, 96),
                           outline='white')
        dot(19, server_running)
        dot(34, client_running)

        return image

    def create_menu(self):
        """创建右键菜单：FRPS / FRPC 状态分行，操作按 启动/重启/停止 分组"""
        s_run = self.mode_running('server')
        c_run = self.mode_running('client')
        s_txt = '运行中' if s_run else '已停止'
        c_txt = '运行中' if c_run else '已停止'

        def sub(title, items):
            return pystray.MenuItem(title, pystray.Menu(*items))

        return pystray.Menu(
            pystray.MenuItem(f"FRPS 服务端: {s_txt}", self.do_nothing, enabled=False),
            pystray.MenuItem(f"FRPC 客户端: {c_txt}", self.do_nothing, enabled=False),
            pystray.Menu.SEPARATOR,
            sub("启动", [
                pystray.MenuItem("启动 FRPS 服务端", self.op('start', 'server'),
                                 enabled=not s_run),
                pystray.MenuItem("启动 FRPC 客户端", self.op('start', 'client'),
                                 enabled=not c_run),
                pystray.MenuItem("全部启动", self.op('start', 'all')),
            ]),
            sub("重启", [
                pystray.MenuItem("重启 FRPS 服务端", self.op('restart', 'server'),
                                 enabled=s_run),
                pystray.MenuItem("重启 FRPC 客户端", self.op('restart', 'client'),
                                 enabled=c_run),
                pystray.MenuItem("全部重启", self.op('restart', 'all')),
            ]),
            sub("停止", [
                pystray.MenuItem("停止 FRPS 服务端", self.op('stop', 'server'),
                                 enabled=s_run),
                pystray.MenuItem("停止 FRPC 客户端", self.op('stop', 'client'),
                                 enabled=c_run),
                pystray.MenuItem("全部停止", self.op('stop', 'all')),
            ]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开Web界面", self.open_web_ui),
            pystray.MenuItem("刷新状态", self.refresh_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self.exit_app),
        )

    def do_nothing(self, icon=None, item=None):
        """空操作"""
        pass

    # ---------------- 状态 ---------------- #
    def mode_running(self, mode):
        """某个模式（client/server）是否在运行。

        注意：get_frp_status() 返回的是 {'client': {...}, 'server': {...}}，
        必须按 mode 取值——早期版本在外层 dict 上取 'running' 永远为 None，
        导致托盘状态和图标与实际运行状态不符。
        """
        try:
            st = self.frp_manager.get_frp_status().get(mode) or {}
            return bool(st.get('running'))
        except Exception as e:
            _log(f"[WARN] 获取 {mode} 状态失败: {e}")
            return False

    def get_frp_status_text(self):
        """整体状态文本：全部运行 / 部分运行 / 已停止"""
        s = self.mode_running('server')
        c = self.mode_running('client')
        if s and c:
            return "frps+frpc 运行中"
        if s or c:
            return "部分运行"
        return "已停止"

    # ---------------- 操作 ---------------- #
    def op(self, action, mode):
        """生成菜单回调（放到后台线程执行，避免卡住托盘菜单）"""
        def fn(icon=None, item=None):
            threading.Thread(target=self.do_action, args=(action, mode),
                             daemon=True).start()
        return fn

    def do_action(self, action, mode):
        mods = ('server', 'client') if mode == 'all' else (mode,)
        if not self._op_lock.acquire(False):
            self._notify('上一个操作还没结束，请稍候')
            return
        try:
            if action == 'start':
                for m in mods:
                    self._start(m)
            elif action == 'stop':
                for m in mods:
                    self._stop(m)
            elif action == 'restart':
                for m in mods:
                    self._stop(m)
                    time.sleep(1)
                    self._start(m)
            self.refresh_status()
        finally:
            self._op_lock.release()

    def _start(self, mode):
        mgr = self.frp_manager
        label = self.MODE_LABEL.get(mode, mode)
        try:
            if self.mode_running(mode):
                self._notify(f"{label} 已在运行中，无需重复启动")
                return
            # 先清掉同模式的残留进程：否则旧 frp 占着端口，新进程一启动就退出
            # （这就是「点启动跟已有 frp 冲突」的根因）
            mgr.kill_frp_mode(mode)
            time.sleep(0.6)
            cfg = mgr.resolve_config_file(mode)
            ok, msg = mgr.start_frp(cfg, mode)
            if ok:
                self._event(f"启动 {label} 成功 · {msg}")
                self._notify(f"{label} 启动成功")
            else:
                self._event(f"启动 {label} 失败 · {msg}")
                self._notify(f"{label} 启动失败：{str(msg)[:120]}")
        except Exception as e:
            self._event(f"启动 {label} 异常 · {e}")
            self._notify(f"{label} 启动异常：{e}")

    def _stop(self, mode):
        mgr = self.frp_manager
        label = self.MODE_LABEL.get(mode, mode)
        try:
            mgr.stop_frp(mode)
            mgr.kill_frp_mode(mode)
            time.sleep(0.5)
            still = self.mode_running(mode)
            if still:
                self._event(f"停止 {label} 未完成 · 进程仍在运行")
                self._notify(f"{label} 仍在运行，可到网页端查看日志")
            else:
                self._event(f"停止 {label} 完成")
        except Exception as e:
            self._event(f"停止 {label} 异常 · {e}")
            self._notify(f"{label} 停止异常：{e}")

    def _event(self, message):
        """写入 logs/manager.log（日志页里以 [面板] 前缀显示）"""
        try:
            self.frp_manager.write_event(message)
        except Exception:
            pass

    def _notify(self, message):
        """气泡提示（部分平台不支持，失败忽略）"""
        try:
            if self.icon:
                self.icon.notify(message, "FRP Manager")
        except Exception:
            pass
        _log(f"[TRAY] {message}")
    
    def open_web_ui(self, icon, item):
        """打开Web界面"""
        try:
            import webbrowser
            webbrowser.open(f"http://localhost:{self.config['WEB_PORT']}")
        except Exception as e:
            _log(f"[ERROR] 打开浏览器失败: {e}")
    
    def refresh_status(self, icon=None, item=None):
        """刷新菜单 + 图标 + 悬浮提示，保证与真实进程状态一致"""
        try:
            s_run = self.mode_running('server')
            c_run = self.mode_running('client')
            if self.icon:
                self.icon.menu = self.create_menu()
                self.icon.title = (f"FRP Manager · FRPS {'运行中' if s_run else '已停止'}"
                                   f" / FRPC {'运行中' if c_run else '已停止'}")
            self.update_icon(s_run, c_run)
        except Exception as e:
            _log(f"[ERROR] 刷新状态失败: {e}")
    
    def update_icon(self, server_running=False, client_running=False):
        """更新托盘图标颜色（绿=全运行 / 橙=部分运行 / 红=全停止）"""
        try:
            if self.icon:
                new_image = self.create_icon_image(server_running, client_running)
                if new_image:
                    self.icon.icon = new_image
        except Exception as e:
            _log(f"[ERROR] 更新图标失败: {e}")
    
    def exit_app(self, icon=None, item=None):
        """退出应用程序"""
        _log("[INFO] 正在退出...")
        self.running = False
        
        # 停止FRP（客户端 + 服务端全部停止）
        try:
            self.frp_manager.stop_frp()
            self.frp_manager.kill_all_frp()
            self._event('退出程序 · 已全部停止 frpc / frps')
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
            # 创建图标 - 根据FRP真实状态选择颜色
            _log("[DEBUG] 正在创建图标...")
            s_run = self.mode_running('server')
            c_run = self.mode_running('client')
            image = self.create_icon_image(s_run, c_run)
            if image is None:
                _log("[ERROR] 无法创建托盘图标")
                return
            _log("[DEBUG] 图标创建成功")
            
            # 创建托盘图标
            _log("[DEBUG] 正在创建托盘...")
            self.icon = pystray.Icon(
                "FRP-Manager",
                image,
                f"FRP Manager · FRPS {'运行中' if s_run else '已停止'}"
                f" / FRPC {'运行中' if c_run else '已停止'}",
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
                    time.sleep(3)  # 每3秒检查一次
                    if self.running:
                        self.refresh_status()
                except Exception:
                    pass
        
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()


def setup_system_tray(frp_manager, config, app, exit_callback=None):
    """设置系统托盘（工厂函数）

    Windows 直接支持；Linux 需要图形环境（DISPLAY/WAYLAND_DISPLAY）+ pystray。
    headless 服务器（ARM Ubuntu Server）返回 None，不影响 Web 面板运行。
    """
    global PYSTRAY_AVAILABLE, pystray

    _log("[DEBUG] setup_system_tray 被调用")
    _log(f"[DEBUG] 平台: {platform.system()}")
    _log(f"[DEBUG] PYSTRAY_AVAILABLE: {PYSTRAY_AVAILABLE}")

    supported = platform.system() == 'Windows' or (
        platform.system() == 'Linux'
        and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    )
    if not supported:
        _log("[INFO] 当前环境无图形界面，跳过系统托盘")
        return None

    if not PYSTRAY_AVAILABLE:
        _log("[DEBUG] 尝试动态导入pystray...")
        try:
            import pystray
            PYSTRAY_AVAILABLE = True
            _log("[DEBUG] pystray导入成功")
        except ImportError as e:
            _log(f"[WARN] 请安装pystray: pip install pystray Pillow, 错误: {e}")
            return None

    _log("[DEBUG] 正在创建SystemTray...")
    tray = SystemTray(frp_manager, config, app, exit_callback)
    _log("[DEBUG] 正在调用tray.run()...")
    tray.run()
    return tray


# ---------------------------------------------------------------------- #
# 路径
# ---------------------------------------------------------------------- #
from frp_manager import resource_dir, data_dir, seed_data

BASE_DIR = resource_dir()      # 只读打包资源（static / 默认 configs / frp 二进制种子）
DATA_DIR = data_dir()          # 可写持久数据（用户配置 / 日志 / 临时 / 下载的二进制）
TEMP_DIR = os.path.join(DATA_DIR, 'temp')
LOCK_FILE = os.path.join(TEMP_DIR, 'app.lock')
PID_FILE = os.path.join(TEMP_DIR, 'app.pid')


def get_lan_ip():
    """获取本机局域网 IP（用于打印可供其他设备访问的地址）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 不会真正发包，仅利用路由表拿到出口网卡 IP
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()



# ---------------------------------------------------------------------- #
# 终端颜色（仅交互式终端上色，日志/重定向保持纯文本，方便复制）
# ---------------------------------------------------------------------- #
def _green(text):
    """把文本染成绿色，仅在交互式终端输出时生效（Windows 旧控制台自动跳过）。

    注意：pythonw / 打包 GUI 下 sys.stdout 是 **None**，直接 `sys.stdout.isatty()`
    会抛 AttributeError —— 曾经就是这样让 Web 线程在 app.run() 前崩掉，
    表现为「双击启动后闪退」。所以必须先判 None。
    """
    out = getattr(sys, 'stdout', None)
    if out is None:
        return text
    try:
        tty = out.isatty()
    except Exception:
        tty = False
    if not tty:
        return text
    if platform.system() == 'Windows':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32          # 开启控制台 ANSI 支持
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            return text                               # 开启失败则不染色
    return f"\033[32m{text}\033[0m"


# ---------------------------------------------------------------------- #
# 单实例
# ---------------------------------------------------------------------- #
def _pid_alive(pid):
    """跨平台判断进程是否存活"""
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    if platform.system() == 'Windows':
        try:
            out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=5)
            return str(pid) in out.stdout
        except Exception:
            return False
    # Linux / macOS
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False


def check_single_instance(force=False):
    """检查是否已有实例在运行；force=True 时忽略检查"""
    os.makedirs(TEMP_DIR, exist_ok=True)

    if not force and os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r', encoding='utf-8') as f:
                old_pid = int(f.read().strip() or 0)
            if _pid_alive(old_pid):
                msg = f"程序已在运行中 (PID: {old_pid})，请先关闭现有实例"
                print(f"[ERROR] {msg}")
                if platform.system() == 'Windows' and getattr(sys, 'frozen', False):
                    try:
                        import ctypes
                        ctypes.windll.user32.MessageBoxW(0, msg, "FRP Manager", 0x10)
                    except Exception:
                        pass
                sys.exit(1)
        except (ValueError, OSError):
            pass  # 锁文件损坏，直接覆盖

    current_pid = os.getpid()
    for path in (LOCK_FILE, PID_FILE):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(str(current_pid))
        except OSError as e:
            print(f"[WARN] 写入 {path} 失败: {e}")

    def cleanup():
        for path in (LOCK_FILE, PID_FILE):
            try:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        if f.read().strip() != str(current_pid):
                            continue  # 已被其它实例接管
                    os.remove(path)
            except OSError:
                pass

    atexit.register(cleanup)


# ---------------------------------------------------------------------- #
# 依赖
# ---------------------------------------------------------------------- #
def _port_in_use(port, host='127.0.0.1'):
    """端口是否被占用；返回占用进程的 PID（Windows 专用，其它平台返回 1）"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        if s.connect_ex((host, port)) != 0:
            return None
    except OSError:
        return None
    finally:
        s.close()

    if platform.system() == 'Windows':
        try:
            out = subprocess.run(['netstat', '-ano'], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=8)
            text = out.stdout.decode('gbk', errors='ignore')
            for line in text.splitlines():
                if f':{port} ' in line and 'LISTENING' in line.upper():
                    pid = line.split()[-1]
                    return int(pid) if pid.isdigit() else 1
        except Exception:
            pass
    return 1


def _port_can_bind(port, host='0.0.0.0'):
    """端口能否真正 bind 成功（而不是只做连接探测）。

    Windows 会把一段端口划进 Hyper-V / WinNAT 的「排除端口范围」，
    此时并没有进程 LISTENING —— connect 探测（_port_in_use）查不出来，
    但 bind 会以 WinError 10013「以一种访问权限不允许的方式做了一个访问
    套接字的尝试」失败，进而 Web 线程崩溃、整个程序退出，表现就是「闪退」。
    所以这里必须实测 bind。
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        # 刻意不加 SO_REUSEADDR：Windows 上该选项会让 bind「成功」到已被监听
        # 的端口，从而误判为可用。这里要的是「能否真正独占绑定」。
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _find_bindable_port(start_port, host='0.0.0.0', tries=30):
    """从 start_port 起找第一个能真正 bind 的端口，找不到返回 None"""
    for candidate in range(start_port, start_port + tries):
        if 1 <= candidate <= 65535 and _port_can_bind(candidate, host):
            return candidate
    return None


def _no_console():
    """是否运行在无控制台环境（pythonw 启动、或打包成 GUI 程序）"""
    return getattr(sys, 'stdout', None) is None or getattr(sys, 'frozen', False)


def _pip_kwargs():
    """无控制台时把子进程输出丢到 DEVNULL，避免继承到不存在的 stdout 句柄"""
    if _no_console():
        return {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    return {}


def _pip_install(specs, extra):
    """实际执行 pip install；常规镜像都失败后，若疑似缺编译工具链，
    则自动补装 gcc/python3-dev 再重试一次（ARM aarch64 + py3.6 常见）。"""
    kw = _pip_kwargs()
    base_attempts = [
        [sys.executable, '-m', 'pip', 'install', *specs, *extra],
        [sys.executable, '-m', 'pip', 'install', *specs, *extra,
         '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'],
    ]
    for attempt in base_attempts:
        try:
            subprocess.check_call(attempt, **kw)
            print("[INFO] 依赖安装成功")
            return True
        except subprocess.CalledProcessError:
            print("[WARN] 安装失败，尝试其它方式...")

    # 编译型失败兜底：补装构建工具链后重试
    print("[WARN] 常规安装失败，尝试安装编译工具链(gcc / python3-dev)后重试...")
    try:
        subprocess.check_call(['apt-get', 'update'], **kw)
        subprocess.check_call(['apt-get', 'install', '-y', 'gcc',
                               'python3-dev', 'python3-pip'], **kw)
    except Exception as e:
        print(f"[WARN] 安装编译工具链失败: {e}（可忽略，继续重试 pip）")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                               *specs, *extra], **kw)
        print("[INFO] 依赖安装成功（已补装编译工具链）")
        return True
    except subprocess.CalledProcessError:
        return False


def install_dependencies():
    """检查（必要时安装）运行所需依赖"""
    if getattr(sys, 'frozen', False):
        return

    # Debian/Ubuntu 的 PEP 668 保护：系统 Python 需要显式允许（新版 pip 才有此参数）
    in_venv = (sys.prefix != getattr(sys, 'base_prefix', sys.prefix))
    extra = [] if in_venv else ['--break-system-packages']

    old_py = sys.version_info < (3, 7)

    if old_py:
        # Python 3.6（如 Ubuntu 18.04）：ARM aarch64 上 MarkupSafe 2.x 没有
        # 预编译 wheel 且源码编译会自引用死锁；整条链路降到 Flask 1.1.x
        # （几乎全是纯 Python wheel），仅 MarkupSafe/psutil 需本地编译。
        req_file = os.path.join(BASE_DIR, 'requirements-py36.txt')
        if os.path.exists(req_file):
            print(f"[INFO] 检测到 Python {sys.version_info.major}."
                  f"{sys.version_info.minor}，使用兼容依赖 {req_file}")
            # 优先用文件整体安装，避免逐个解析时重新拉到 MarkupSafe 2.x
            if _pip_install(['-r', req_file], extra):
                return
            # 文件安装失败时，兜底逐个钉死版本
            print("[WARN] 通过 requirements 文件安装失败，改用钉死版本逐个安装")
            specs = [
                'Flask==1.1.4', 'Werkzeug==1.0.1', 'Jinja2==2.11.3',
                'MarkupSafe==1.1.1', 'itsdangerous==1.1.0', 'click==7.1.2',
                'requests==2.27.1', 'psutil==5.9.8',
            ]
            if _pip_install(specs, extra):
                return
        else:
            print("[WARN] 未找到 requirements-py36.txt，回退到钉死版本安装")
            specs = [
                'Flask==1.1.4', 'Werkzeug==1.0.1', 'Jinja2==2.11.3',
                'MarkupSafe==1.1.1', 'itsdangerous==1.1.0', 'click==7.1.2',
                'requests==2.27.1', 'psutil==5.9.8',
            ]
            if _pip_install(specs, extra):
                return
    else:
        # Python >= 3.7：优先用通用 requirements.txt
        req_file = os.path.join(BASE_DIR, 'requirements.txt')
        if os.path.exists(req_file) and _pip_install(['-r', req_file], extra):
            return
        specs = ['Flask>=2.0.0', 'requests>=2.25.0', 'psutil>=5.8.0']
        if _pip_install(specs, extra):
            return

    print("[ERROR] 依赖安装失败，请手动执行安装命令（见上方提示）")
    print("[ERROR] ARM Ubuntu 建议：")
    print("        sudo apt-get install -y gcc python3-dev")
    print("        python3 -m pip install -r requirements-py36.txt")
    sys.exit(1)


def preflight(frp_manager, cfg):
    """打印环境自检信息，供 --check 使用"""
    print("=" * 60)
    print(f" FRP Manager v{VERSION} 环境自检")
    print("=" * 60)
    print(f" Python      : {sys.version.split()[0]} ({sys.executable})")
    print(f" 系统/架构   : {frp_manager.platform_summary()}")
    print(f" 是否 ARM    : {'是' if frp_manager.is_arm() else '否'}")
    print(f" 根目录      : {DATA_DIR}")
    print(f" Web 端口    : {cfg['WEB_PORT']}")
    print(f" frpc        : {frp_manager.get_frp_binary('client')} "
          f"({'存在' if frp_manager.check_frp_binary('client') else '缺失'})")
    print(f" frps        : {frp_manager.get_frp_binary('server')} "
          f"({'存在' if frp_manager.check_frp_binary('server') else '缺失'})")

    for name in ('flask', 'requests', 'psutil'):
        try:
            importlib.import_module(name)
            print(f" 依赖 {name:<8}: OK")
        except ImportError:
            print(f" 依赖 {name:<8}: 缺失")
    print("=" * 60)


# ---------------------------------------------------------------------- #
# Web UI 线程
# ---------------------------------------------------------------------- #
def start_web_ui(app, frp_manager, cfg, err_box=None):
    # 把 main 解析出来的运行时配置同步给 web_ui 模块（保证 --port 生效）
    try:
        import web_ui
        web_ui.config['WEB_PORT'] = cfg['WEB_PORT']
        web_ui.config['FRP_BIN_DIR'] = cfg['FRP_BIN_DIR']
        web_ui.config['FRP_CONFIG_DIR'] = cfg['FRP_CONFIG_DIR']
        web_ui.config['FRP_LOG_DIR'] = cfg['FRP_LOG_DIR']
        web_ui.config['TEMP_DIR'] = cfg['TEMP_DIR']
    except Exception as e:
        print(f"[WARN] 同步 Web 配置失败: {e}")

    app.config['FRP_MANAGER'] = frp_manager
    app.config['CONFIG'] = cfg
    # 侧栏/页脚显示的版本号始终跟随 main.py 的 VERSION，不再写死在页面里
    app.config['APP_VERSION'] = VERSION
    try:
        import web_ui
        web_ui.app.config['APP_VERSION'] = VERSION
    except Exception:
        pass

    host = cfg['WEB_HOST']
    port = cfg['WEB_PORT']
    lan = get_lan_ip()

    # 端口冲突 / 被系统保留时，自动顺延到下一个可用端口重试，
    # 避免一遇 WinError 10013 就线程崩溃 -> 主进程跟着退出（所谓「闪退」）。
    last_err = f"Web 服务启动失败（端口 {port}）"
    cur_port = port
    for attempt in range(30):
        # 同步最终端口，保证状态页 / 托盘「打开面板」用的一定是实际端口
        cfg['WEB_PORT'] = cur_port
        try:
            import web_ui as _wu
            _wu.config['WEB_PORT'] = cur_port
        except Exception:
            pass
        if attempt:
            print(f"[WARN] 端口 {port} 不可用，已自动改用 {cur_port}")
        # 打印并落地最终访问地址：窗口实时可见，start.bat / 用户无需翻日志
        print(f"[INFO] Web UI 监听 {_green(f'http://{host}:{cur_port}')}  (本机全部网卡)")
        print(f"[INFO] 本机访问:   {_green(f'http://127.0.0.1:{cur_port}')}")
        if host in ('0.0.0.0', ''):
            print(f"[INFO] 局域网访问: {_green(f'http://{lan}:{cur_port}')}")
        try:
            os.makedirs(cfg['FRP_LOG_DIR'], exist_ok=True)
            with open(os.path.join(cfg['FRP_LOG_DIR'], 'panel_url.txt'),
                      'w', encoding='utf-8') as f:
                f.write(f"http://127.0.0.1:{cur_port}\n")
                if host in ('0.0.0.0', ''):
                    f.write(f"http://{lan}:{cur_port}\n")
        except Exception:
            pass
        try:
            app.run(host=host, port=cur_port,
                    debug=False, use_reloader=False, threaded=True)
            return
        except KeyboardInterrupt:
            return
        except Exception as e:
            last_err = f"Web 服务启动失败: {type(e).__name__}: {e}"
            print(f"[ERROR] {last_err}")
            nxt = _find_bindable_port(cur_port + 1, host or '0.0.0.0')
            if nxt is None:
                break
            cur_port = nxt

    # 全部候选端口都失败，才留下痕迹让主进程结束（此时确有致命错误）
    if err_box is not None:
        err_box.append(last_err)


# ---------------------------------------------------------------------- #
# 主流程
# ---------------------------------------------------------------------- #
def parse_args():
    p = argparse.ArgumentParser(description='FRP Manager - 跨平台 FRP 管理工具')
    p.add_argument('--host', default='0.0.0.0', help='Web 监听地址（默认 0.0.0.0）')
    p.add_argument('--port', type=int, default=None,
                   help='Web 端口，默认读取 configs/web_port.ini 或 5000')
    p.add_argument('--no-tray', action='store_true', help='不启动系统托盘（Linux 默认）')
    p.add_argument('--force', action='store_true', help='忽略单实例检查')
    p.add_argument('--check', action='store_true', help='仅做环境自检后退出')
    p.add_argument('--download-frp', action='store_true',
                   help='下载当前架构对应的 frpc/frps 后退出')
    p.add_argument('--version', action='version', version=f'FRP Manager {VERSION}')
    return p.parse_args()


def main():
    args = parse_args()

    # pythonw / 打包 GUI 下先把输出落到 logs/console.log，闪退才能查到原因
    setup_headless_output()

    from frp_manager import FRPManager

    # 端口：命令行 > 环境变量 > 配置文件 > 默认
    port = args.port
    if port is None:
        env_port = os.environ.get('FRP_WEB_PORT', '').strip()
        if env_port.isdigit():
            port = int(env_port)
    if port is None:
        port_file = os.path.join(BASE_DIR, 'configs', 'web_port.ini')
        port = 5000
        if os.path.exists(port_file):
            try:
                with open(port_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip().startswith('port'):
                            value = int(line.split('=')[1].strip())
                            if 1 <= value <= 65535:
                                port = value
                                break
            except Exception:
                pass

    cfg = {
        'WEB_PORT': port,
        'WEB_HOST': args.host,
        'LOG_LEVEL': 'info',
        'FRP_BIN_DIR': os.path.join(DATA_DIR, 'bin'),
        'FRP_CONFIG_DIR': os.path.join(DATA_DIR, 'configs'),
        'FRP_LOG_DIR': os.path.join(DATA_DIR, 'logs'),
        'TEMP_DIR': os.path.join(DATA_DIR, 'temp'),
    }

    for dir_path in (cfg['FRP_BIN_DIR'], cfg['FRP_CONFIG_DIR'],
                     cfg['FRP_LOG_DIR'], cfg['TEMP_DIR']):
        os.makedirs(dir_path, exist_ok=True)

    # 首次运行：把打包内的默认 configs / frp 二进制 复制到可写数据目录
    try:
        seed_data('configs')
        seed_data('bin')
    except Exception as e:
        print(f"[WARN] 初始化默认配置/二进制失败: {e}")

    frp_manager = FRPManager(cfg)

    if args.check:
        preflight(frp_manager, cfg)
        print(f"[INFO] 需要 {frp_manager.frpc_bin_name} / {frp_manager.frps_bin_name} "
              f"放在 {cfg['FRP_BIN_DIR']}")
        return

    if args.download_frp:
        ok = frp_manager.download_frp()
        print("[INFO] 下载完成" if ok else "[ERROR] 下载失败")
        sys.exit(0 if ok else 1)

    check_single_instance(force=args.force)
    install_dependencies()

    from web_ui import app

    print(f"[INFO] FRP Manager v{VERSION} 启动中...")
    print(f"[INFO] 系统平台: {frp_manager.platform_summary()}")
    print(f"[INFO] Web UI 将在 http://localhost:{cfg['WEB_PORT']} 启动")

    # 读取应用设置（开机启动 / 随程序启动 FRPC·FRPS / 下载镜像）
    app_settings = frp_manager.load_app_settings()

    if not frp_manager.check_frp_binary('client'):
        print(f"[WARN] 未找到 {frp_manager.frpc_bin_name}")
        print("[INFO] 正在下载 FRP 二进制文件...")
        if frp_manager.download_frp(version=None, mirror=app_settings.get('mirror')):
            print("[INFO] FRP 二进制文件下载成功")
        else:
            print("[ERROR] 下载失败，可在 Web 界面点“下载/更新FRP”，"
                  "或手动放入 bin/ 目录")
    frp_manager.ensure_executable()

    # 按设置「随程序启动 FRPC / FRPS」：仅当【用户已真正配置过】且勾选时才拉起。
    # 首次运行只有系统自动生成的默认模板，此时启动必然报错，故跳过，
    # 等用户在面板完成配置后再自行勾选。
    for mode, key, label in (('client', 'frpc_on_start', 'FRPC 客户端'),
                             ('server', 'frps_on_start', 'FRPS 服务端')):
        if not app_settings.get(key):
            continue
        if not frp_manager.has_user_config(mode):
            print(f"[INFO] 未检测到 {label} 的有效配置，已跳过随程序启动"
                  f"（请先在面板完成配置，再于『开机启动』处勾选）")
            continue
        try:
            cfg_file = frp_manager.resolve_config_file(mode)
            ok, msg = frp_manager.start_frp(cfg_file, mode)
            frp_manager.write_event(f'随程序启动 {label}: {msg}')
            print(f"[INFO] 随程序启动 {mode}: {msg}")
        except Exception as e:
            print(f"[WARN] 随程序启动 {mode} 失败: {e}")

    stop_event = threading.Event()

    # ---- 进程自愈守护 + 日志轮转（后台常驻线程）----
    try:
        frp_manager.start_monitor()
        print("[INFO] 进程自愈守护 / 日志轮转已启动")
    except Exception as e:
        print(f"[WARN] 启动监控线程失败: {e}")

    # ---- 配置安全扫描（启动即检查风险项，写入面板日志）----
    try:
        issues = frp_manager.scan_security()
        if issues:
            hi = [i for i in issues if i['level'] == 'high']
            frp_manager.write_event(frp_manager._m(
                f"配置安全扫描：发现 {len(issues)} 项风险（高危 {len(hi)} 项），详见「安全扫描」页",
                f"Security scan: {len(issues)} risk(s) found ({len(hi)} high), see the Security Scan page"))
            for i in issues:
                frp_manager.write_event(f"Security[{i['level']}][{i['mode']}] {i['msg']}"
                                        if frp_manager._msg_lang() == 'en'
                                        else f"安全[{i['level']}][{i['mode']}] {i['msg']}")
        else:
            frp_manager.write_event(frp_manager._m(
                "配置安全扫描：未发现明显风险项",
                "Security scan: no obvious risks found"))
    except Exception as e:
        print(f"[WARN] 配置安全扫描失败: {e}")

    # ---- 系统托盘（Windows 桌面 / 带图形界面的 Linux） ----
    tray = None
    has_display = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    want_tray = (not args.no_tray) and (
        platform.system() == 'Windows'
        or (platform.system() == 'Linux' and has_display)
    )
    if want_tray:
        try:
            tray = setup_system_tray(frp_manager, cfg, app, stop_event.set)
            print("[INFO] 系统托盘已启动" if tray
                  else "[INFO] 系统托盘未启用（不影响 Web 面板）")
        except ImportError as e:
            print(f"[WARN] 系统托盘功能不可用: {e}（pip install pystray Pillow 可启用）")
        except Exception as e:
            print(f"[WARN] 系统托盘启动失败: {e}")

    # ---- 优雅退出 ----
    def graceful_exit(signum=None, frame=None):
        print("\n[INFO] 正在停止 FRP 服务...")
        try:
            frp_manager.stop_frp()
            frp_manager.kill_all_frp()
        except Exception as e:
            print(f"[WARN] 停止 FRP 时出错: {e}")
        stop_event.set()
        if tray is not None:
            try:
                tray.running = False
                if tray.icon:
                    tray.icon.stop()
            except Exception:
                pass
        print("[INFO] 已退出")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, graceful_exit)
        except (ValueError, OSError, AttributeError):
            pass  # 非主线程或平台不支持

    # ---- 端口预检 + 自动挑选可用端口 ----
    # 不能只靠 _port_in_use（连接探测）：端口被 Windows 划进排除范围时并没有
    # 进程监听、探测不出结果，但 bind 会 WinError 10013 —— 必须实测 bind。
    port_busy = _port_in_use(cfg['WEB_PORT'])
    if port_busy:
        print(f"[WARN] 端口 {cfg['WEB_PORT']} 已被占用（PID {port_busy}），"
              f"多半是另一个 FRP Manager 实例还在跑")

    original_port = cfg['WEB_PORT']
    bind_host = cfg['WEB_HOST'] or '0.0.0.0'
    if not _port_can_bind(original_port, bind_host):
        alt = _find_bindable_port(original_port + 1, bind_host)
        if alt is None:
            print(f"[ERROR] 端口 {original_port} 及后续 30 个端口都无法绑定，"
                  f"很可能是被 Hyper-V / WinNAT 划进了排除端口范围")
            print("[HINT] 用 netsh interface ipv4 show excludedportrange protocol=tcp 查看保留范围")
        else:
            cfg['WEB_PORT'] = alt
            try:
                import web_ui
                web_ui.config['WEB_PORT'] = alt
            except Exception:
                pass
            print(f"[WARN] 端口 {original_port} 无法绑定（被系统保留或占用），"
                  f"本次自动改用 {alt}")
            print(f"[HINT] 想固定端口可在 configs\\web_port.ini 写入 port = {alt}")

    # ---- Web UI 线程 ----
    web_err = []
    web_thread = threading.Thread(target=start_web_ui,
                                  args=(app, frp_manager, cfg, web_err),
                                  daemon=True)
    web_thread.start()

    # ---- HTTP 链接状态监测（结果写 logs/manager.log，日志页以 [面板] 显示）----
    try:
        import web_ui
        web_ui.start_link_monitor(interval=30)
    except Exception as e:
        print(f"[WARN] HTTP 链接监测未启动: {e}")

    # 无控制台（pythonw / 打包 GUI）时，浏览器由托盘菜单打开，这里不自动弹窗
    if not _no_console():
        print(f"[INFO] 访问 http://localhost:{cfg['WEB_PORT']} 进行配置")
        print("[INFO] 按 Ctrl+C 退出")

    try:
        # 主线程阻塞等待；headless 环境下不依赖 stdin，systemd 可直接托管
        while not stop_event.wait(1.0):
            if not web_thread.is_alive():
                reason = web_err[0] if web_err else (
                    f"端口 {cfg['WEB_PORT']} 被占用" if port_busy else '原因见日志')
                print(f"[ERROR] Web 服务已退出，程序即将结束：{reason}")
                try:
                    frp_manager.write_event('启动失败 · Web 服务退出：' + reason)
                    frp_manager.send_alert('FRP Manager 启动失败：Web 服务退出（' + reason + '）',
                                           title='FRP Manager 启动失败')
                except Exception:
                    pass
                if tray is not None:
                    tray._notify(f"Web 服务启动失败：{reason}\n详情见 logs/console.log")
                break
    except KeyboardInterrupt:
        pass

    graceful_exit()
    sys.exit(0)


if __name__ == '__main__':
    main()
