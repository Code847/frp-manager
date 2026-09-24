# -*- coding: utf-8 -*-
"""
FRP 管理核心模块（跨平台 / 支持 ARM Linux）

- 按 CPU 架构自动匹配官方发布包：linux_arm64 / linux_arm / linux_amd64 / linux_386 / windows_amd64 ...
- ARM 版 Ubuntu（aarch64）与 32 位 ARM（armv7l）均可直接使用
- 下载支持多镜像回退、tar.gz / zip 自动解压、自动 chmod +x
"""
import os
import re
import sys
import time
import stat
import json
import threading
import configparser
import textwrap
import shutil
import tarfile
import zipfile
import platform
import subprocess
import secrets
import datetime

from pathlib import Path

try:
    import requests
except ImportError:  # 允许在没装 requests 时仍能导入（由 main.py 负责安装）
    requests = None

# 未能探测到最新版本时的默认版本（0.52+ 仍兼容 ini 配置格式）
# v0.71.0：最新稳定版；0.67.0 存在 CVE-2026-40910，已弃用
DEFAULT_FRP_VERSION = '0.71.0'


# ------------------------------------------------------------------ #
# 路径解析（原 app_paths.py，已合并）
#
# PyInstaller 三种运行形态：
#   - 源码（python main.py）：资源与数据都在项目目录
#   - --onedir：资源在 exe 同级的 _internal 目录
#   - --onefile：资源解压到只读的临时目录 sys._MEIPASS，退出即删
# 因此拆成 resource_dir()（只读资源）与 data_dir()（可写持久数据）两类。
# ------------------------------------------------------------------ #
def resource_dir():
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS                      # --onefile
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        internal = os.path.join(exe_dir, '_internal')
        return internal if os.path.isdir(internal) else exe_dir   # --onedir
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        try:
            if os.access(exe_dir, os.W_OK):
                return exe_dir
        except OSError:
            pass
        # 程序目录不可写（如 C:\Program Files），回退到 APPDATA
        fallback = os.environ.get('APPDATA') or os.path.expanduser('~')
        d = os.path.join(fallback, 'FRP-Manager')
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.dirname(os.path.abspath(__file__))


_MSG_LANG = {'at': 0.0, 'lang': 'zh'}


def _msg_lang():
    """当前界面语言（读 configs/app_settings.ini 的 [ui] lang），2 秒缓存"""
    now = time.time()
    if now - _MSG_LANG['at'] < 2.0:
        return _MSG_LANG['lang']
    lang = 'zh'
    try:
        f = os.path.join(data_dir(), 'configs', 'app_settings.ini')
        if os.path.exists(f):
            cp = configparser.ConfigParser()
            cp.read(f, encoding='utf-8')
            if cp.has_section('ui') and cp.has_option('ui', 'lang'):
                if cp.get('ui', 'lang').strip().lower().startswith('en'):
                    lang = 'en'
    except Exception:
        pass
    _MSG_LANG['at'] = now
    _MSG_LANG['lang'] = lang
    return lang


def _m(zh, en=None):
    """按当前界面语言返回文案；英文缺省时回退中文"""
    if _msg_lang() != 'en':
        return zh
    return en if en else zh


def seed_data(name, force=False):
    """首次运行：把打包资源里的 name 目录（configs / bin）复制到 data 目录。

    已存在且非空时跳过，避免覆盖用户的配置与已下载的二进制。
    """
    src = os.path.join(resource_dir(), name)
    dst = os.path.join(data_dir(), name)
    if not os.path.isdir(src):
        return False
    try:
        dst_exists = os.path.isdir(dst) and os.listdir(dst)
        if force or not dst_exists:
            os.makedirs(dst, exist_ok=True)
            for entry in os.listdir(src):
                s = os.path.join(src, entry)
                t = os.path.join(dst, entry)
                if os.path.isdir(s):
                    shutil.copytree(s, t, dirs_exist_ok=True)
                elif not os.path.exists(t):
                    shutil.copy2(s, t)
            return True
    except Exception:
        return False
    return False


# 官方下载地址 + 常用 GitHub 加速镜像（国内/ARM 设备网络友好）
GITHUB_URL = 'https://github.com/fatedier/frp/releases/download/v{ver}/{name}'
# 国内代理镜像（用户可在设置里指定优先使用其中一个）
DOMESTIC_MIRRORS = {
    'ghfast': 'https://ghfast.top/' + GITHUB_URL,
    'ghproxy_com': 'https://gh-proxy.com/' + GITHUB_URL,
    'ghproxy_net': 'https://ghproxy.net/' + GITHUB_URL,
    'mirror_ghproxy': 'https://mirror.ghproxy.com/' + GITHUB_URL,
}
# 兼容旧引用
GITHUB_MIRRORS = [GITHUB_URL] + list(DOMESTIC_MIRRORS.values())

# platform.machine() -> frp 官方发布包的架构后缀
ARCH_ALIASES = {
    # x86_64
    'x86_64': 'amd64', 'amd64': 'amd64', 'x64': 'amd64', 'em64t': 'amd64',
    # ARM 64 位（树莓派 3/4/5 64 位系统、鲲鹏、飞腾、Apple Silicon、阿里云倚天等）
    'aarch64': 'arm64', 'arm64': 'arm64', 'armv8l': 'arm64', 'armv8': 'arm64',
    # ARM 32 位
    'armv7l': 'arm', 'armv7': 'arm', 'armv6l': 'arm', 'armv6': 'arm', 'arm': 'arm',
    # 32 位 x86
    'i386': '386', 'i486': '386', 'i586': '386', 'i686': '386', 'x86': '386', 'ia32': '386',
    # loongarch（frp 无官方产物，走源码编译或第三方包，这里显式提示）
    'loongarch64': 'loong64', 'mips64': 'mips64', 'riscv64': 'riscv64',
}


def _norm_system():
    s = platform.system().lower()
    if s.startswith('win'):
        return 'windows'
    if s.startswith('darwin'):
        return 'darwin'
    return s or 'linux'


def _norm_arch():
    machine = (platform.machine() or '').strip().lower()
    if machine in ARCH_ALIASES:
        return ARCH_ALIASES[machine]
    # 兜底：从字符串里猜
    if 'aarch64' in machine or 'arm64' in machine:
        return 'arm64'
    if machine.startswith('arm'):
        return 'arm'
    if '64' in machine and ('x86' in machine or 'amd' in machine):
        return 'amd64'
    return machine or 'amd64'


class FRPManager:
    # 进程自愈 / 监控（P1：避免半夜静默掉线）
    MODE_LABEL = {'client': 'FRPC 客户端', 'server': 'FRPS 服务端'}
    WATCHDOG_INTERVAL = 5              # 秒：心跳间隔
    WATCHDOG_MAX_CRASHES = 5           # 连续崩溃超过该值则停止自启并告警
    WATCHDOG_WINDOW = 300              # 秒：连崩计数窗口（窗口外重新计数）
    LOG_ROTATE_BYTES = 5 * 1024 * 1024
    LOG_ROTATE_KEEP = 5                # 保留最近 N 份历史
    AUDIT_MAX_LINES = 2000

    def __init__(self, config):
        self.config = config
        self.system = _norm_system()          # windows / linux / darwin
        self.arch_machine = (platform.machine() or 'unknown')
        self.arch = _norm_arch()              # amd64 / arm64 / arm / 386 ...
        # 客户端/服务端 各自独立进程，二者可同时运行
        self.frp_processes = {'client': None, 'server': None}
        self.frp_version = None
        self.frp_binary_path = None

        # frp 官方发布包名后缀：{os}_{arch}
        self.release_platform = f"{self.system}_{self.arch}"
        if self.system == 'windows':
            self.archive_ext = 'zip'
            self.bin_ext = '.exe'
        else:
            self.archive_ext = 'tar.gz'
            self.bin_ext = ''

        # 目标文件名（放到 bin/ 下），例如 frpc_linux_arm64 / frpc_windows_amd64.exe
        self.frpc_bin_name = f'frpc_{self.release_platform}{self.bin_ext}'
        self.frps_bin_name = f'frps_{self.release_platform}{self.bin_ext}'

        # 老版本遗留的固定名字（兼容既有部署）
        self.legacy_names = {
            'client': ['frpc', 'frpc' + self.bin_ext],
            'server': ['frps', 'frps' + self.bin_ext],
        }

        # ---- 进程自愈 / 监控状态（P1）----
        # 「期望运行状态」：用户/随启动拉起后登记为 True，自愈守护据此判断要不要拉起。
        # 仅当 desired=True 且进程不在时才自愈，避免在用户没想运行 frp 时自作主张。
        self._desired = {'client': False, 'server': False}
        self._crash = {
            'client': {'count': 0, 'first': 0.0, 'last': 0.0},
            'server': {'count': 0, 'first': 0.0, 'last': 0.0},
        }
        self._down_alerted = {'client': False, 'server': False}
        self._watchdog_thread = None
        self._watchdog_stop = threading.Event()
        self._watchdog_enabled = True
        self._watchdog_max = self.WATCHDOG_MAX_CRASHES
        self._security_issues = []

        # ---- 定时重启（v1.13.0）----
        self._ar_last_interval = time.time()   # 间隔模式：上次（或启动时）时间戳
        self._ar_last_daily = ''               # 每日模式：上次触发日期 'YYYY-MM-DD'
        self._ar_last_fire = {'client': 0.0, 'server': 0.0}
        self._ar_next_due = 0.0                # 下次预计触发的时间戳（0=未知）
        self._ar_interval_used = None          # 检测间隔变化，变了就重新计时

        # 审计日志路径（与 frp 运行日志分开）
        self._audit_path = os.path.join(self.config['FRP_LOG_DIR'], 'audit.log')

    # ------------------------------------------------------------------ #
    # 平台信息
    # ------------------------------------------------------------------ #
    def platform_summary(self):
        return f"{platform.system()} {self.arch_machine} ({self.release_platform})"

    def is_arm(self):
        return self.arch in ('arm64', 'arm')

    # ------------------------------------------------------------------ #
    # 二进制定位
    # ------------------------------------------------------------------ #
    def binary_candidates(self, mode='client'):
        """返回候选文件路径（按优先级）"""
        bin_dir = self.config['FRP_BIN_DIR']
        base = 'frpc' if mode == 'client' else 'frps'
        wanted = self.frpc_bin_name if mode == 'client' else self.frps_bin_name

        names = [wanted, base + self.bin_ext, base]
        # 去重且保持顺序
        seen, ordered = set(), []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                ordered.append(n)

        paths = [os.path.join(bin_dir, n) for n in ordered]

        # 最后兜底：bin 目录下任何 frpc*/frps* 文件
        try:
            for f in sorted(os.listdir(bin_dir)):
                if f.lower().startswith(base) and os.path.isfile(os.path.join(bin_dir, f)):
                    p = os.path.join(bin_dir, f)
                    if p not in paths:
                        paths.append(p)
        except OSError:
            pass
        return paths

    def get_frp_binary(self, mode='client'):
        """获取实际存在的 FRP 二进制路径；不存在时返回首选路径"""
        for path in self.binary_candidates(mode):
            if os.path.exists(path):
                return path
        return self.binary_candidates(mode)[0]

    def check_frp_binary(self, mode=None):
        """检查二进制是否存在（mode=None 时要求 client 与 server 都在）"""
        if mode:
            return os.path.exists(self.get_frp_binary(mode))
        return (os.path.exists(self.get_frp_binary('client'))
                and os.path.exists(self.get_frp_binary('server')))

    def ensure_executable(self):
        """Linux/macOS 下给二进制补上可执行权限"""
        if self.system == 'windows':
            return
        for mode in ('client', 'server'):
            path = self.get_frp_binary(mode)
            if os.path.exists(path):
                try:
                    st = os.stat(path)
                    os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                except OSError as e:
                    print(f"[WARN] 设置执行权限失败 {path}: {e}")

    # ------------------------------------------------------------------ #
    # 版本与下载
    # ------------------------------------------------------------------ #
    def get_latest_version(self, timeout=15):
        """获取最新 FRP 版本；失败时回退默认版本"""
        if requests is not None:
            for api in (
                'https://api.github.com/repos/fatedier/frp/releases/latest',
                'https://ghfast.top/https://api.github.com/repos/fatedier/frp/releases/latest',
            ):
                try:
                    resp = requests.get(api, timeout=timeout,
                                        headers={'User-Agent': 'frp-manager'})
                    if resp.status_code == 200:
                        tag = resp.json().get('tag_name', '')
                        ver = tag.lstrip('v').strip()
                        if re.match(r'^\d+\.\d+\.\d+', ver):
                            self.frp_version = ver
                            return ver
                except Exception as e:
                    print(f"[WARN] 获取最新版本失败({api}): {e}")

        self.frp_version = DEFAULT_FRP_VERSION
        return self.frp_version

    def _download_to(self, url, filepath, timeout=120, progress=None):
        """流式下载单个文件，失败返回 False。

        progress: 可选回调 progress(phase, percent, done, total)，用于前端进度查询。
        """
        if requests is None:
            print("[ERROR] 缺少 requests 库，无法下载")
            return False
        try:
            with requests.get(url, stream=True, timeout=timeout,
                              headers={'User-Agent': 'frp-manager'}) as resp:
                if resp.status_code != 200:
                    return False
                total = int(resp.headers.get('content-length', 0))
                done = 0
                tmp = filepath + '.part'
                if progress:
                    progress('downloading', 0, 0, total)
                with open(tmp, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if total > 0:
                                pct = done * 100.0 / total
                                if progress:
                                    progress('downloading', pct, done, total)
                                else:
                                    sys.stdout.write(
                                        f"\r[INFO] 下载中 {pct:.1f}% "
                                        f"({done}/{total} bytes)")
                                    sys.stdout.flush()
                if not progress:
                    sys.stdout.write("\n")
                if total > 0 and done < total * 0.95:
                    print(f"[ERROR] 下载不完整: {done}/{total}")
                    os.remove(tmp)
                    return False
                os.replace(tmp, filepath)
                return True
        except Exception as e:
            print(f"[WARN] 下载失败 {url}: {e}")
            try:
                if os.path.exists(filepath + '.part'):
                    os.remove(filepath + '.part')
            except OSError:
                pass
            return False

    def build_mirror_list(self, mirror=None):
        """返回待尝试的下载地址模板列表（按顺序回退）。

        mirror 可选：auto（默认，官方+全部国内镜像）/ github（仅官方）/
        ghfast / ghproxy_com / ghproxy_net / mirror_ghproxy（指定国内代理优先）。
        环境变量 FRP_DOWNLOAD_MIRROR 视为最高优先级自定义源。
        """
        if mirror and mirror in DOMESTIC_MIRRORS:
            return [DOMESTIC_MIRRORS[mirror], GITHUB_URL]
        if mirror == 'github':
            return [GITHUB_URL]
        custom = os.environ.get('FRP_DOWNLOAD_MIRROR')
        if custom:
            return [custom, GITHUB_URL] + list(DOMESTIC_MIRRORS.values())
        return [GITHUB_URL] + list(DOMESTIC_MIRRORS.values())

    def _download_with_mirrors(self, version, filename, save_path, mirror=None):
        """依次尝试官方源与各加速镜像"""
        for tpl in self.build_mirror_list(mirror):
            url = tpl.format(ver=version, name=filename) if '{' in tpl else f"{tpl.rstrip('/')}/{filename}"
            print(f"[INFO] 正在下载 FRP 压缩包: {url}")
            if self._download_to(url, save_path):
                return True
        return False

    def download_frp(self, version=None, mirror=None, progress=None):
        """下载并安装当前平台（含 ARM）对应的 frpc / frps。

        progress: 可选回调 progress(phase, percent, done, total, message)。
        返回 True/False。
        """
        def prog(phase, percent=0, done=0, total=0, message=''):
            if progress:
                progress(phase, percent, done, total, message)

        try:
            version = version or self.frp_version or self.get_latest_version()
            archive_name = f"frp_{version}_{self.release_platform}.{self.archive_ext}"
            archive_path = os.path.join(self.config['TEMP_DIR'], archive_name)

            prog('resolving', 3, 0, 0, f'解析版本 v{version}')
            ok = self._download_with_mirrors(
                version, archive_name, archive_path, mirror)
            if not ok:
                prog('failed', 0, 0, 0, '所有镜像下载失败')
                print(f"[ERROR] FRP 下载失败：{archive_name}")
                print(f"[ERROR] 可手动下载并放到 bin/ 目录：frpc / frps")
                return False

            prog('extracting', 60, 0, 0, '解压中')
            extract_dir = os.path.join(self.config['TEMP_DIR'],
                                       f"frp_{version}_{self.release_platform}")
            if os.path.isdir(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
            os.makedirs(extract_dir, exist_ok=True)

            print(f"[INFO] 正在解压: {archive_name}")
            if self.archive_ext == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as z:
                    z.extractall(self.config['TEMP_DIR'])
            else:
                with tarfile.open(archive_path, 'r:gz') as t:
                    # Python 3.12+ 的过滤器，防止路径穿越
                    try:
                        t.extractall(self.config['TEMP_DIR'], filter='data')
                    except TypeError:
                        t.extractall(self.config['TEMP_DIR'])

            if not os.path.isdir(extract_dir):
                # 有些包解压目录名不同，做一次模糊匹配
                for d in os.listdir(self.config['TEMP_DIR']):
                    full = os.path.join(self.config['TEMP_DIR'], d)
                    if os.path.isdir(full) and d.startswith(f"frp_{version}"):
                        extract_dir = full
                        break

            prog('installing', 85, 0, 0, '安装二进制')
            ok = False
            for mode, src_name, dst_name in (
                ('client', 'frpc' + self.bin_ext, self.frpc_bin_name),
                ('server', 'frps' + self.bin_ext, self.frps_bin_name),
            ):
                src = os.path.join(extract_dir, src_name)
                if os.path.exists(src):
                    dst = os.path.join(self.config['FRP_BIN_DIR'], dst_name)
                    # 先把旧版本归档到 bin/versions/，之后可以在界面上切回去
                    kept = self.archive_current_binary(mode)
                    if kept:
                        print(f"[INFO] 已归档旧版本: {os.path.basename(kept)}")
                    try:
                        shutil.copy2(src, dst)
                    except PermissionError:
                        print(f"[ERROR] {dst_name} 正在被占用，请先停止 frp 再更新")
                        continue
                    ok = True
                    print(f"[INFO] 已安装: bin/{dst_name}")
                else:
                    print(f"[WARN] 压缩包内未找到 {src_name}")

            # 权限与清理
            self.ensure_executable()
            shutil.rmtree(extract_dir, ignore_errors=True)
            try:
                os.remove(archive_path)
            except OSError:
                pass
            prog('done', 100, 0, 0, 'FRP 二进制已就绪')
            return ok

        except Exception as e:
            prog('failed', 0, 0, 0, f'下载异常: {e}')
            print(f"[ERROR] 下载FRP失败: {e}")
            return False

    # ------------------------------------------------------------------ #
    # 后台下载（带进度查询）
    # ------------------------------------------------------------------ #
    def _init_dl_state(self):
        if not hasattr(self, '_dl'):
            self._dl = {'phase': 'idle', 'percent': 0, 'done': 0, 'total': 0,
                       'message': '', 'finished': True, 'ok': None,
                       'error': None, 'version': None, 'started': None}
            self._dl_thread = None

    def _dl_progress(self, phase, percent=0, done=0, total=0, message=''):
        self._init_dl_state()
        self._dl.update({'phase': phase, 'percent': round(percent, 1),
                         'done': done, 'total': total})
        if message:
            self._dl['message'] = message

    def start_download_frp(self, version=None, mirror=None):
        """在后台线程启动下载，立即返回 (ok, message)。进度用 download_progress() 查询。"""
        self._init_dl_state()
        if self._dl_thread is not None and self._dl_thread.is_alive():
            return False, '已有下载任务正在进行，请稍后再试'
        self._dl = {'phase': 'starting', 'percent': 0, 'done': 0, 'total': 0,
                    'message': '准备下载...', 'finished': False, 'ok': None,
                    'error': None, 'version': version,
                    'started': time.strftime('%Y-%m-%d %H:%M:%S')}

        def run():
            try:
                ok = self.download_frp(version, mirror, progress=self._dl_progress)
                self._dl['finished'] = True
                self._dl['ok'] = ok
                if not self._dl['message'] or self._dl['phase'] == 'done':
                    self._dl['message'] = ('FRP 二进制已就绪（'
                                           f"{self.release_platform}）" if ok
                                           else '下载失败，请检查网络或切换镜像')
            except Exception as e:
                self._dl['finished'] = True
                self._dl['ok'] = False
                self._dl['error'] = str(e)
                self._dl['message'] = f'下载异常: {e}'

        self._dl_thread = threading.Thread(target=run, daemon=True)
        self._dl_thread.start()
        return True, '已开始在后台下载 FRP'

    def download_progress(self):
        self._init_dl_state()
        return dict(self._dl)

    # ------------------------------------------------------------------ #
    # 应用设置（开机启动 / 下载镜像偏好）持久化
    # ------------------------------------------------------------------ #
    def app_settings_path(self):
        return os.path.join(self.config['FRP_CONFIG_DIR'], 'app_settings.ini')

    def load_app_settings(self):
        """读取应用设置，返回字典；文件不存在时返回全部默认值。"""
        defaults = {
            'app_on_boot': False, 'frpc_on_start': False, 'frps_on_start': False,
            'mirror': 'auto',
            # 开机启动增强（P2-⑬）：延迟秒数 + 运行级别
            'autostart_delay': 0, 'autostart_mode': 'user',
            # 进程自愈守护
            'watchdog_enabled': True, 'watchdog_max_crashes': 5,
            # 掉线告警推送
            'alert_enabled': False, 'alert_url': '', 'alert_type': 'dingtalk',
            'alert_frp_down': True, 'alert_heal_fail': True, 'alert_start_fail': False,
            'alert_email_host': '', 'alert_email_port': 465,
            'alert_email_user': '', 'alert_email_pass': '', 'alert_email_to': '',
            # 界面语言
            'lang': 'zh',
            # 配置快照（P3-⑦）：保存配置时自动生成快照，可回滚
            'auto_snapshot': True,
            # 定时重启（v1.13.0）：mode=interval 按间隔小时 / daily 每天固定时刻
            'auto_restart_enabled': False, 'auto_restart_mode': 'interval',
            'auto_restart_interval': 24, 'auto_restart_time': '04:00',
            'auto_restart_frpc': True, 'auto_restart_frps': True,
        }
        p = self.app_settings_path()
        if not os.path.exists(p):
            return dict(defaults)
        out = dict(defaults)
        try:
            cp = configparser.ConfigParser()
            cp.read(p, encoding='utf-8')
            if cp.has_section('autostart'):
                for k in ('app_on_boot', 'frpc_on_start', 'frps_on_start'):
                    if cp.has_option('autostart', k):
                        out[k] = cp.get('autostart', k).strip().lower() in ('1', 'true', 'yes', 'on')
                if cp.has_option('autostart', 'autostart_delay'):
                    try:
                        out['autostart_delay'] = int(cp.get('autostart', 'autostart_delay'))
                    except ValueError:
                        pass
                if cp.has_option('autostart', 'autostart_mode'):
                    v = cp.get('autostart', 'autostart_mode').strip().lower()
                    if v in ('user', 'system'):
                        out['autostart_mode'] = v
            if cp.has_section('ui') and cp.has_option('ui', 'lang'):
                v = cp.get('ui', 'lang').strip().lower()
                if v in ('zh', 'en'):
                    out['lang'] = v
            if cp.has_section('download') and cp.has_option('download', 'mirror'):
                out['mirror'] = cp.get('download', 'mirror').strip() or 'auto'
            if cp.has_section('monitor'):
                if cp.has_option('monitor', 'watchdog_enabled'):
                    out['watchdog_enabled'] = cp.get('monitor', 'watchdog_enabled').strip().lower() in ('1', 'true', 'yes', 'on')
                if cp.has_option('monitor', 'watchdog_max_crashes'):
                    try:
                        out['watchdog_max_crashes'] = int(cp.get('monitor', 'watchdog_max_crashes'))
                    except ValueError:
                        pass
            if cp.has_section('alert'):
                for k in ('alert_enabled', 'alert_frp_down', 'alert_heal_fail', 'alert_start_fail'):
                    if cp.has_option('alert', k):
                        out[k] = cp.get('alert', k).strip().lower() in ('1', 'true', 'yes', 'on')
                for k in ('alert_url', 'alert_type', 'alert_email_host',
                          'alert_email_user', 'alert_email_pass', 'alert_email_to'):
                    if cp.has_option('alert', k):
                        out[k] = cp.get('alert', k).strip()
                if cp.has_option('alert', 'alert_email_port'):
                    try:
                        out['alert_email_port'] = int(cp.get('alert', 'alert_email_port'))
                    except ValueError:
                        pass
            if cp.has_section('snapshot'):
                if cp.has_option('snapshot', 'auto_snapshot'):
                    out['auto_snapshot'] = cp.get('snapshot', 'auto_snapshot').strip().lower() in ('1', 'true', 'yes', 'on')
            if cp.has_section('restart'):
                if cp.has_option('restart', 'auto_restart_enabled'):
                    out['auto_restart_enabled'] = cp.get('restart', 'auto_restart_enabled').strip().lower() in ('1', 'true', 'yes', 'on')
                if cp.has_option('restart', 'auto_restart_mode'):
                    v = cp.get('restart', 'auto_restart_mode').strip().lower()
                    if v in ('interval', 'daily'):
                        out['auto_restart_mode'] = v
                if cp.has_option('restart', 'auto_restart_interval'):
                    try:
                        out['auto_restart_interval'] = int(cp.get('restart', 'auto_restart_interval'))
                    except ValueError:
                        pass
                if cp.has_option('restart', 'auto_restart_time'):
                    out['auto_restart_time'] = cp.get('restart', 'auto_restart_time').strip() or '04:00'
                for k in ('auto_restart_frpc', 'auto_restart_frps'):
                    if cp.has_option('restart', k):
                        out[k] = cp.get('restart', k).strip().lower() in ('1', 'true', 'yes', 'on')
        except Exception as e:
            print(f"[WARN] 读取应用设置失败: {e}")
        return out

    def save_app_settings(self, d):
        """合并写入应用设置；布尔值会被规范化为 true/false。返回 True/False。"""
        merged = self.load_app_settings()
        for k, v in d.items():
            merged[k] = 'true' if v is True else ('false' if v is False else str(v))

        def sv(v):
            return 'true' if v is True else ('false' if v is False else str(v))

        try:
            cp = configparser.ConfigParser()
            cp.add_section('autostart')
            for k in ('app_on_boot', 'frpc_on_start', 'frps_on_start'):
                cp.set('autostart', k, sv(merged.get(k, False)))
            cp.set('autostart', 'autostart_delay', str(int(merged.get('autostart_delay', 0) or 0)))
            cp.set('autostart', 'autostart_mode', str(merged.get('autostart_mode', 'user')))
            cp.add_section('ui')
            cp.set('ui', 'lang', str(merged.get('lang', 'zh')))
            cp.add_section('download')
            cp.set('download', 'mirror', str(merged.get('mirror', 'auto')))
            cp.add_section('snapshot')
            cp.set('snapshot', 'auto_snapshot', sv(merged.get('auto_snapshot', True)))
            cp.add_section('restart')
            cp.set('restart', 'auto_restart_enabled', sv(merged.get('auto_restart_enabled', False)))
            cp.set('restart', 'auto_restart_mode', str(merged.get('auto_restart_mode', 'interval')))
            cp.set('restart', 'auto_restart_interval', str(int(merged.get('auto_restart_interval', 24) or 24)))
            cp.set('restart', 'auto_restart_time', str(merged.get('auto_restart_time', '04:00')))
            cp.set('restart', 'auto_restart_frpc', sv(merged.get('auto_restart_frpc', True)))
            cp.set('restart', 'auto_restart_frps', sv(merged.get('auto_restart_frps', True)))
            cp.add_section('monitor')
            cp.set('monitor', 'watchdog_enabled', sv(merged.get('watchdog_enabled', True)))
            cp.set('monitor', 'watchdog_max_crashes', str(merged.get('watchdog_max_crashes', 5)))
            cp.add_section('alert')
            for k in ('alert_enabled', 'alert_frp_down', 'alert_heal_fail', 'alert_start_fail'):
                cp.set('alert', k, sv(merged.get(k, False)))
            for k in ('alert_url', 'alert_type', 'alert_email_host',
                      'alert_email_user', 'alert_email_pass', 'alert_email_to'):
                cp.set('alert', k, str(merged.get(k, '')))
            cp.set('alert', 'alert_email_port', str(merged.get('alert_email_port', 465)))
            with open(self.app_settings_path(), 'w', encoding='utf-8') as f:
                cp.write(f)
            return True
        except Exception as e:
            print(f"[ERROR] 保存应用设置失败: {e}")
            return False

    # ------------------------------------------------------------------ #
    # 开机启动（各环境）
    # ------------------------------------------------------------------ #
    AUTO_START_KEY = 'FRPManager'

    def get_launch_command(self):
        """返回 (cmd_list, human) —— 当前环境下启动本程序的命令。

        - 打包(exe) 模式：直接用 exe 自身；
        - 源码模式：Windows 用 pythonw（无黑窗），其它用 sys.executable 运行 main.py。
        """
        if getattr(sys, 'frozen', False):
            return [sys.executable], os.path.basename(sys.executable)
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.py')
        py = sys.executable
        if self.system == 'windows':
            pyw = py.replace('python.exe', 'pythonw.exe')
            if os.path.exists(pyw):
                py = pyw
        return [py, main_py], main_py

    def set_app_autostart(self, enabled, dry_run=False):
        """开启/关闭开机启动。dry_run=True 时仅返回将要执行的操作，不落盘。"""
        if self.system == 'windows':
            return self._win_set_autostart(enabled, dry_run)
        if self.system == 'linux':
            return self._linux_set_autostart(enabled, dry_run)
        if self.system == 'darwin':
            return self._mac_set_autostart(enabled, dry_run)
        return False, '当前系统暂不支持开机启动（仅 Windows / Linux / macOS）'

    def get_app_autostart_status(self):
        """查询操作系统层面是否已注册开机启动。"""
        if self.system == 'windows':
            try:
                import winreg
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                   r'Software\Microsoft\Windows\CurrentVersion\Run')
                try:
                    winreg.QueryValueEx(k, self.AUTO_START_KEY)
                    return True
                except FileNotFoundError:
                    return False
            except Exception:
                return False
        if self.system == 'linux':
            unit = os.path.expanduser('~/.config/systemd/user/frp-manager.service')
            if os.path.exists(unit):
                return True
            desktop = os.path.expanduser('~/.config/autostart/frp-manager.desktop')
            return os.path.exists(desktop)
        if self.system == 'darwin':
            plist = os.path.expanduser('~/Library/LaunchAgents/com.frpsmanager.plist')
            return os.path.exists(plist)
        return False

    def _win_set_autostart(self, enabled, dry_run):
        try:
            import winreg
        except ImportError:
            return False, '需要 Windows 环境（当前非 Windows）'
        s = self.load_app_settings()
        delay = int(s.get('autostart_delay') or 0)
        mode = (s.get('autostart_mode') or 'user').lower()
        cmd_list, _ = self.get_launch_command()
        raw = '"' + '" "'.join(cmd_list) + '"'
        if delay > 0:
            cmd = f'cmd /c "timeout /t {delay} /nobreak >nul && {raw}"'
        else:
            cmd = raw
        if mode == 'system':
            # 系统级：以 SYSTEM 身份在开机时启动（需管理员权限）
            delay_min = max(1, delay // 60) if delay > 0 else 0
            sch = f'schtasks /Create /TN "{self.AUTO_START_KEY}" /SC ONSTART'
            if delay_min:
                sch += f' /DELAY 000{delay_min:02d}:00'
            sch += f' /RU SYSTEM /TR "{raw}" /F'
            if dry_run:
                return True, f'将以系统级计划任务注册（需管理员）: {sch}'
            try:
                subprocess.run(sch, shell=True, check=False)
                return True, '已通过系统计划任务开启开机启动（SYSTEM 身份）'
            except Exception as e:
                return False, f'系统级注册失败（可能需要管理员）: {e}'
        # 用户级：写入注册表 Run 键
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
        if dry_run:
            return True, f'注册表 {key_path}\\{self.AUTO_START_KEY} = {cmd}'
        try:
            if enabled:
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                   winreg.KEY_SET_VALUE)
                winreg.SetValueEx(k, self.AUTO_START_KEY, 0, winreg.REG_SZ, cmd)
                winreg.CloseKey(k)
                return True, '已写入注册表，下次登录将自动启动'
            try:
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                   winreg.KEY_SET_VALUE)
                winreg.DeleteValue(k, self.AUTO_START_KEY)
                winreg.CloseKey(k)
            except FileNotFoundError:
                pass
            # 同时清理可能残留的系统级任务
            try:
                subprocess.run(f'schtasks /Delete /TN "{self.AUTO_START_KEY}" /F',
                               shell=True, check=False)
            except Exception:
                pass
            return True, '已关闭开机启动'
        except Exception as e:
            return False, f'设置失败: {e}'

    def _linux_set_autostart(self, enabled, dry_run):
        s = self.load_app_settings()
        delay = int(s.get('autostart_delay') or 0)
        mode = (s.get('autostart_mode') or 'user').lower()
        cmd_list, _ = self.get_launch_command()
        exec_line = ' '.join([cmd_list[0]] + [f'"{a}"' for a in cmd_list[1:]])
        if mode == 'system':
            unit_dir = '/etc/systemd/system'
        else:
            unit_dir = os.path.expanduser('~/.config/systemd/user')
        unit_path = os.path.join(unit_dir, 'frp-manager.service')
        pre = f'ExecStartPre=/bin/sleep {delay}' if delay > 0 else ''
        unit = textwrap.dedent(f'''\
            [Unit]
            Description=FRP Manager
            After=network-online.target
            Wants=network-online.target

            [Service]
            Type=simple
            {pre}
            ExecStart={exec_line} --no-tray
            Restart=on-failure
            WorkingDirectory={os.path.dirname(os.path.abspath(__file__))}

            [Install]
            WantedBy=multi-user.target
        ''')
        scope_flag = [] if mode == 'system' else ['--user']
        if dry_run:
            scope = '系统级(/etc/systemd/system)' if mode == 'system' else '用户级(systemd --user)'
            return True, f'写入 {unit_path} 并 systemctl {" ".join(scope_flag)}enable --now frp-manager.service（{scope}）'
        try:
            os.makedirs(unit_dir, exist_ok=True)
            with open(unit_path, 'w', encoding='utf-8') as f:
                f.write(unit)
            if enabled:
                subprocess.run(['systemctl'] + scope_flag + ['enable', '--now',
                                'frp-manager.service'], check=False)
                return True, ('已通过 systemd 系统服务开启开机启动（需 root）' if mode == 'system'
                              else '已通过 systemd 用户服务开启开机启动')
            # 关闭
            subprocess.run(['systemctl'] + scope_flag + ['disable', '--now',
                            'frp-manager.service'], check=False)
            desktop = os.path.expanduser('~/.config/autostart/frp-manager.desktop')
            if os.path.exists(desktop):
                os.remove(desktop)
            return True, '已关闭开机启动'
        except Exception as e:
            return False, f'设置失败: {e}'

    def _mac_set_autostart(self, enabled, dry_run):
        s = self.load_app_settings()
        delay = int(s.get('autostart_delay') or 0)
        mode = (s.get('autostart_mode') or 'user').lower()
        if mode == 'system':
            plist_dir = '/Library/LaunchDaemons'
            label = 'com.frpsmanager.daemon'
        else:
            plist_dir = os.path.expanduser('~/Library/LaunchAgents')
            label = 'com.frpsmanager'
        plist = os.path.join(plist_dir, label + '.plist')
        cmd_list, _ = self.get_launch_command()
        prog = '\n'.join(f'    <string>{a}</string>' for a in cmd_list)
        interval = (f'    <key>StartInterval</key>\n    <integer>{delay}</integer>\n'
                    if delay > 0 else '')
        content = textwrap.dedent(f'''\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
             "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key><string>{label}</string>
                <key>ProgramArguments</key>
                <array>
            {prog}
                </array>
                {interval}<key>RunAtLoad</key><true/>
                <key>KeepAlive</key><false/>
            </dict>
            </plist>
        ''')
        if dry_run:
            scope = '系统级(/Library/LaunchDaemons)' if mode == 'system' else '用户级(~/Library/LaunchAgents)'
            return True, f'写入 {plist} 并 launchctl load（{scope}）'
        try:
            os.makedirs(plist_dir, exist_ok=True)
            with open(plist, 'w', encoding='utf-8') as f:
                f.write(content)
            if enabled:
                subprocess.run(['launchctl', 'load', plist], check=False)
                return True, ('已通过 launchd 系统级开启开机启动（需 root）' if mode == 'system'
                              else '已通过 launchd 开启开机启动')
            subprocess.run(['launchctl', 'unload', plist], check=False)
            if os.path.exists(plist):
                os.remove(plist)
            return True, '已关闭开机启动'
        except Exception as e:
            return False, f'设置失败: {e}'

    # ------------------------------------------------------------------ #
    # 进程控制
    # ------------------------------------------------------------------ #
    def _creation_flags(self):
        """仅在 Windows 下隐藏子进程窗口"""
        if self.system == 'windows':
            return getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        return 0

    def start_frp(self, config_path, mode='client'):
        """启动 FRP（返回 (success, message)）。只停同类进程，不影响另一模式，
        因此 frpc 与 frps 可以同时运行。"""
        try:
            self._stop_one(mode)

            binary_path = self.get_frp_binary(mode)
            if not os.path.exists(binary_path):
                return False, (f"FRP 二进制文件不存在: {binary_path}\n"
                               f"请把 {self.frpc_bin_name if mode == 'client' else self.frps_bin_name} "
                               f"放入 bin/ 目录，或在界面点击“下载 FRP”")
            if not os.path.isfile(config_path):
                return False, f"配置文件不存在: {config_path}"

            self.ensure_executable()

            log_file = os.path.join(self.config['FRP_LOG_DIR'],
                                    f'frp_{mode}_{int(time.time())}.log')
            log_f = open(log_file, 'w', encoding='utf-8', errors='ignore')
            proc = subprocess.Popen(
                [binary_path, '-c', config_path],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=(self.system != 'windows'),
                creationflags=self._creation_flags(),
            )
            self.frp_processes[mode] = proc
            time.sleep(1.5)

            if proc.poll() is None:
                print(f"[INFO] FRP {mode} 已启动 (PID: {proc.pid})")
                print(f"[INFO] 日志文件: {log_file}")
                self.set_desired(mode, True)
                return True, f"FRP 启动成功 (PID: {proc.pid})"

            # 进程立刻退出，把日志尾部带回去便于排错
            tail = ''
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    tail = f.read().strip()[-400:]
            except OSError:
                pass
            self.frp_processes[mode] = None
            return False, f"FRP 启动后立即退出：{tail or '请查看日志'}"

        except Exception as e:
            return False, f"启动FRP失败: {e}"

    def _stop_one(self, mode):
        """停止由本程序启动的某模式 FRP 进程（client/server）"""
        proc = self.frp_processes.get(mode)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                print(f"[INFO] FRP {mode} 进程已停止")
            except Exception as e:
                print(f"[WARN] 停止 FRP {mode} 进程时出错: {e}")
            finally:
                self.frp_processes[mode] = None
                self.set_desired(mode, False)     # 主动停止即撤出自愈守护
        return True

    def stop_frp(self, mode=None):
        """停止 FRP 进程。mode 指定则只停该模式，否则全部停止。
        client 与 server 互不影响。"""
        if mode in ('client', 'server'):
            self._stop_one(mode)
        else:
            self._stop_one('client')
            self._stop_one('server')
        self._proc_scan = None          # 停止后立刻作废缓存，状态马上反映为「未运行」

    def kill_frp_mode(self, mode):
        """按模式清理系统中残留的 frpc（client）或 frps（server）进程，不影响另一模式"""
        bin_char = 'c' if mode == 'client' else 's'
        killed = 0
        try:
            import psutil
        except ImportError:
            # 没有 psutil 时退回系统命令
            try:
                if self.system == 'windows':
                    exe = (self.frpc_bin_name if mode == 'client' else self.frps_bin_name)
                    subprocess.run(['taskkill', '/f', '/im', exe],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=self._creation_flags())
                else:
                    subprocess.run(['pkill', '-f', r'/(frp' + bin_char + r')(\s|$)'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return 1
            except Exception:
                return 0

        me = os.getpid()
        pat = re.compile(r'(^|[/\\ ])frp' + bin_char + r'(\.exe)?(\s|$)')
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] == me:
                    continue
                name = (proc.info.get('name') or '').lower()
                cmdline = ' '.join(proc.info.get('cmdline') or []).lower()
                if name.startswith('frp' + bin_char) or pat.search(cmdline):
                    proc.terminate()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        if killed:
            print(f"[INFO] 已结束 {killed} 个残留 FRP {mode} 进程")
        return killed

    def kill_all_frp(self):
        """清理系统中所有残留的 frpc/frps 进程（跨平台，基于 psutil）"""
        return self.kill_frp_mode('client') + self.kill_frp_mode('server')

    # ------------------------------------------------------------------ #
    # 状态与日志
    # ------------------------------------------------------------------ #
    # 进程扫描结果的复用窗口（秒）。psutil 全进程遍历在 Windows 上开销不小，
    # 而一次 /api/status 里「状态 / 端口映射 / 守护状态」多处都要判断是否在跑，
    # 各扫一遍会把请求拖到数百毫秒，所以合并成单次扫描并短时复用。
    PROC_SCAN_TTL = 1.0

    def _scan_external_frp(self):
        """一次遍历找出外部启动的 frpc / frps，返回 {mode: 状态dict 或 None}"""
        now = time.time()
        cache = getattr(self, '_proc_scan', None)
        if cache and (now - cache.get('ts', 0)) < self.PROC_SCAN_TTL:
            return cache['data']

        data = {'client': None, 'server': None}
        try:
            import psutil
            pats = {}
            for mode, ch in (('client', 'c'), ('server', 's')):
                pats[mode] = (re.compile(r'(^|[/\\ ])frp' + ch + r'(\.exe)?(\s|$)'),
                              'frp' + ch)
            for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    name = (p.info.get('name') or '').lower()
                    cmdline = ' '.join(p.info.get('cmdline') or [])
                    low = cmdline.lower()
                    for mode, (pat, prefix) in pats.items():
                        if data[mode] is None and (name.startswith(prefix) or pat.search(low)):
                            data[mode] = {'running': True, 'pid': p.info['pid'],
                                          'mode': mode,
                                          'message': f'外部启动: {cmdline[:120]}'}
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                if data['client'] and data['server']:
                    break      # 两端都找到了，提前结束遍历
        except Exception:
            pass
        self._proc_scan = {'ts': now, 'data': data}
        return data

    def _status_for(self, mode):
        """获取单个模式（client/server）的运行状态"""
        proc = self.frp_processes.get(mode)
        if proc is not None and proc.poll() is None:
            return {'running': True, 'pid': proc.pid,
                    'mode': mode,
                    'message': _m('通过 Web UI 启动', 'Started from the Web UI')}

        ext = self._scan_external_frp().get(mode)
        if ext:
            return dict(ext)
        return {'running': False, 'pid': None, 'mode': mode,
                'message': _m('未运行', 'Idle')}

    def get_frp_status(self):
        """获取 FRP 运行状态（跨平台）。client 与 server 各自独立返回，
        因此可同时得知 frpc 与 frps 是否在运行。"""
        return {
            'client': self._status_for('client'),
            'server': self._status_for('server'),
        }

    # ------------------------------------------------------------------ #
    # 日志（按模式拆分 + 合并打标）
    # ------------------------------------------------------------------ #
    LOG_TS_RE = re.compile(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T]'
                           r'(\d{1,2}):(\d{2}):(\d{2})')
    # frp 默认输出带 ANSI 颜色码，网页展示前需要去掉
    ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

    # 本程序自身的事件日志（启停操作 / HTTP 链接探测），与 frpc、frps 分开存放，
    # 日志页里以 [面板] 前缀显示，便于一眼区分「frp 的输出」和「本程序的检测结果」。
    MANAGER_LOG = 'manager.log'
    MANAGER_LOG_TAG = '面板'
    MANAGER_LOG_MAX = 1200      # 超过则只保留末尾若干行，避免长期运行把磁盘写满

    @classmethod
    def log_tag(cls, path):
        """按日志文件名判断归属：frpc / frps / 面板"""
        name = os.path.basename(str(path)).lower()
        if name == cls.MANAGER_LOG or name.startswith('manager'):
            return cls.MANAGER_LOG_TAG
        if 'client' in name or name.startswith('frpc'):
            return 'frpc'
        if 'server' in name or name.startswith('frps'):
            return 'frps'
        return 'frp'

    def manager_log_path(self):
        """事件日志文件路径（logs/manager.log）"""
        return os.path.join(self.config['FRP_LOG_DIR'], self.MANAGER_LOG)

    def write_event(self, message):
        """写一条本程序事件（启停操作、HTTP 链接探测结果等）到 logs/manager.log。

        行首带时间戳，可被 read_frp_log 的时间线归并识别，所以「全部」模式下
        这些记录会和 frpc/frps 的输出按时间混排，并用 [面板] 前缀区分。
        """
        try:
            os.makedirs(self.config['FRP_LOG_DIR'], exist_ok=True)
            path = self.manager_log_path()
            line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line)
            self._trim_manager_log(path)
            return True
        except Exception as e:
            print(f"[WARN] 写入事件日志失败: {e}")
            return False

    def _trim_manager_log(self, path):
        """事件日志超过上限时裁剪，只保留末尾 MANAGER_LOG_MAX 行"""
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            if len(lines) <= self.MANAGER_LOG_MAX:
                return
            with open(path, 'w', encoding='utf-8') as f:
                f.writelines(lines[-self.MANAGER_LOG_MAX:])
        except OSError:
            pass

    def log_files(self, mode='all'):
        """列出日志文件（按修改时间升序）。mode: all / client / server / webui"""
        log_dir = self.config['FRP_LOG_DIR']
        try:
            files = [p for p in Path(log_dir).glob('frp*.log') if p.is_file()]
            mgr = Path(log_dir) / self.MANAGER_LOG
            if mgr.is_file():
                files.append(mgr)
        except OSError:
            return []
        tag_of = {'client': 'frpc', 'server': 'frps', 'webui': self.MANAGER_LOG_TAG}
        if mode in tag_of:
            want = tag_of[mode]
            files = [p for p in files if self.log_tag(p) == want]
        try:
            files.sort(key=lambda p: p.stat().st_mtime)
        except OSError:
            pass
        return files

    @classmethod
    def _ts_key(cls, line):
        """解析行首时间戳，返回可比较的元组；无时间戳返回 None"""
        m = cls.LOG_TS_RE.match(line.strip())
        if not m:
            return None
        try:
            return tuple(int(g) for g in m.groups())
        except (TypeError, ValueError):
            return None

    def read_frp_log(self, mode='all', lines=100):
        """读取日志并按来源打标。

        mode='client' 只看 frpc，'server' 只看 frps，'all' 则按时间戳把两者
        合并成一条时间线，每行前缀 [frpc] / [frps]，便于区分来源。
        """
        try:
            files = self.log_files(mode)
            if not files:
                return ''

            # (排序键, 文件序号, 行号, 文本) —— 稳定归并，保证同一文件内顺序不变
            entries = []
            for fi, path in enumerate(files):
                tag = self.log_tag(path)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except OSError:
                    continue
                last_key = (0,)
                for li, raw in enumerate(content.splitlines()):
                    line = self.ANSI_RE.sub('', raw)
                    if not line.strip():
                        continue
                    k = self._ts_key(line) or last_key
                    last_key = k
                    entries.append((k, fi, li, f'[{tag}] {line}'))

            entries.sort(key=lambda e: (e[0], e[1], e[2]))
            out = [e[3] for e in entries]
            if lines and lines > 0:
                out = out[-lines:]
            return '\n'.join(out)
        except Exception as e:
            return f"读取日志失败: {e}"

    def clear_frp_logs(self):
        """清空 logs/ 下的 frp 运行日志（保留文件，仅截断内容）"""
        n = 0
        for path in self.log_files('all'):
            try:
                with open(path, 'w', encoding='utf-8'):
                    pass
                n += 1
            except OSError:
                continue
        return n

    # ------------------------------------------------------------------ #
    # 版本探测
    # ------------------------------------------------------------------ #
    def binary_version(self, mode='client'):
        """执行 <bin> -v 读取版本号；二进制缺失或执行失败返回 ''"""
        path = self.get_frp_binary(mode)
        if not os.path.exists(path):
            return ''
        try:
            out = subprocess.run([path, '-v'],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,
                                 timeout=5,
                                 creationflags=self._creation_flags())
        except Exception:
            return ''
        txt = (out.stdout or b'').decode('utf-8', 'ignore')
        m = re.search(r'(\d+\.\d+\.\d+)', txt)
        if m:
            return m.group(1)
        return txt.strip().splitlines()[0][:48] if txt.strip() else ''

    # ------------------------------------------------------------------ #
    # 本地多版本：扫描 / 归档 / 切换
    # ------------------------------------------------------------------ #
    def versions_dir(self):
        """归档历史版本的目录：bin/versions/"""
        return os.path.join(self.config['FRP_BIN_DIR'], 'versions')

    @staticmethod
    def _ver_from_name(name):
        m = re.search(r'(\d+\.\d+\.\d+)', name)
        return m.group(1) if m else ''

    def _matches_platform(self, name):
        """文件名里的平台后缀必须与当前平台完全一致（避免 arm 误匹配 arm64）"""
        plat = self.release_platform
        i = name.find(plat)
        if i < 0:
            return False
        after = name[i + len(plat):]
        return after == '' or after[0] in '._-'

    def _probe_version(self, path):
        """读单个二进制的版本：先按文件名猜，猜不到再执行 -v"""
        v = self._ver_from_name(os.path.basename(path))
        if v:
            return v
        try:
            out = subprocess.run([path, '-v'], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=5,
                                 creationflags=self._creation_flags())
            txt = (out.stdout or b'').decode('utf-8', 'ignore')
            m = re.search(r'(\d+\.\d+\.\d+)', txt)
            if m:
                return m.group(1)
        except Exception:
            pass
        return ''

    def list_local_versions(self, mode='client'):
        """扫描本地可用的 frpc/frps 版本。

        来源：当前生效二进制 / bin/versions/ 归档 / temp 里解压出来的官方发布包
        / bin 根目录下同平台的其它副本。返回按版本号倒序、生效中排最前的列表。
        """
        base = 'frpc' if mode == 'client' else 'frps'
        bin_dir = self.config['FRP_BIN_DIR']
        active = os.path.abspath(self.get_frp_binary(mode))
        found = {}

        # 同一版本可能有多个来源，取优先级最高的：生效中 > bin > 归档 > 解压包
        rank = {'active': 0, 'bin': 1, 'versions': 2, 'temp': 3}

        def add(path, origin, hint=''):
            try:
                if not os.path.isfile(path):
                    return
            except OSError:
                return
            ap = os.path.abspath(path)
            # 文件名自带版本号最快；其次用调用方给的提示（如解压目录名 frp_0.71.0_xxx）；
            # 都没有才真的执行 <bin> -v
            ver = (self._ver_from_name(os.path.basename(ap)) or hint
                   or self._probe_version(ap))
            if not ver:
                return
            try:
                st = os.stat(ap)
                size, mt = st.st_size, st.st_mtime
            except OSError:
                size, mt = 0, 0
            is_active = (ap == active)
            old = found.get(ver)
            if old is not None and rank.get(origin, 9) >= rank.get(old['origin'], 9):
                return
            found[ver] = {'version': ver, 'path': ap,
                          'name': os.path.basename(ap), 'origin': origin,
                          'size': size, 'mtime': mt, 'active': is_active}

        add(active, 'active')

        vdir = self.versions_dir()
        if os.path.isdir(vdir):
            for f in sorted(os.listdir(vdir)):
                if f.lower().startswith(base) and self._matches_platform(f):
                    add(os.path.join(vdir, f), 'versions')

        temp = self.config.get('TEMP_DIR') or ''
        if os.path.isdir(temp):
            for d in sorted(os.listdir(temp)):
                full = os.path.join(temp, d)
                if os.path.isdir(full) and d.lower().startswith('frp_') \
                        and self._matches_platform(d):
                    add(os.path.join(full, base + self.bin_ext), 'temp',
                        self._ver_from_name(d))

        try:
            for f in sorted(os.listdir(bin_dir)):
                if f.lower().startswith(base) and self._matches_platform(f):
                    add(os.path.join(bin_dir, f), 'bin')
        except OSError:
            pass

        def vkey(v):
            try:
                return tuple(int(n) for n in v.split('.'))
            except ValueError:
                return (0,)

        items = list(found.values())
        items.sort(key=lambda x: (not x['active'], tuple(-n for n in vkey(x['version']))))
        return items

    def archive_current_binary(self, mode):
        """把当前生效的二进制归档到 bin/versions/，方便之后切回来"""
        base = 'frpc' if mode == 'client' else 'frps'
        path = self.get_frp_binary(mode)
        if not os.path.exists(path):
            return None
        # 优先执行 -v 拿真实版本；执行不出来（文件被占用/非标准产物）时退回文件名里的版本号
        ver = self.binary_version(mode) or self._ver_from_name(os.path.basename(path))
        if not ver:
            return None
        try:
            vdir = self.versions_dir()
            os.makedirs(vdir, exist_ok=True)
            dst = os.path.join(vdir,
                               f"{base}_{self.release_platform}_{ver}{self.bin_ext}")
            if os.path.abspath(dst) == os.path.abspath(path):
                return None
            if not os.path.exists(dst):
                shutil.copy2(path, dst)
                return dst
        except OSError as e:
            print(f"[WARN] 归档 {base} {ver} 失败: {e}")
        return None

    def switch_binary(self, mode, version):
        """把指定版本切换为当前生效的二进制，返回 (ok, message)"""
        base = 'frpc' if mode == 'client' else 'frps'
        want = str(version or '').strip()
        if not want:
            return False, '未指定版本'
        items = {i['version']: i for i in self.list_local_versions(mode)}
        target = items.get(want)
        if not target:
            avail = '、'.join(sorted(items.keys(), reverse=True)) or '无'
            return False, f"本地没有 {base} 的 {want} 版本（可用：{avail}）"
        active = self.get_frp_binary(mode)
        if os.path.abspath(target['path']) == os.path.abspath(active):
            return True, f"{base} 已经是 {want}"
        # 先把当前版本归档，别把唯一的二进制弄丢
        self.archive_current_binary(mode)
        try:
            shutil.copy2(target['path'], active)
        except PermissionError:
            return False, (f"切换失败：{os.path.basename(active)} 正在被占用，"
                           f"请先停止 {base} 再切换版本")
        except OSError as e:
            return False, f"切换失败：{e}"
        self.ensure_executable()
        return True, f"{base} 已切换到 {want}"

    # ------------------------------------------------------------------ #
    # 配置读写
    # ------------------------------------------------------------------ #
    def save_config(self, config_type, config_content, snapshot=None):
        """保存配置。按内容自动选择扩展名：TOML 内容存 .toml，INI 内容存 .ini

        snapshot=None 时按 app_settings.auto_snapshot 决定；传 True/False 显式覆盖。
        保存前若启用快照，会先为「当前」配置生成一份快照，便于回滚。
        """
        if snapshot is None:
            try:
                snapshot = bool(self.load_app_settings().get('auto_snapshot', True))
            except Exception:
                snapshot = True
        if snapshot:
            try:
                cur = self.load_config(config_type)
                if cur:
                    self.create_snapshot(config_type, content=cur, comment='保存前自动快照')
                else:
                    # 首次保存（之前无配置）：把这份初始配置也留一份，便于日后回滚
                    self.create_snapshot(config_type, content=config_content, comment='初始配置')
            except Exception as e:
                print(f"[WARN] 保存前自动快照失败: {e}")
        try:
            head = config_content.lstrip()
            is_toml = (
                head.startswith('serverAddr')
                or head.startswith('bindPort')
                or '[[proxies]]' in config_content
                or re.search(r'^\s*\[\[', config_content, re.M) is not None
            )
            ext = 'toml' if is_toml else 'ini'
            config_file = os.path.join(self.config['FRP_CONFIG_DIR'],
                                       f'{config_type}.{ext}')
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            print(f"[DEBUG] 配置已保存: {config_file}")
            return config_file
        except Exception as e:
            print(f"[ERROR] 保存配置文件失败: {e}")
            return None

    def load_config(self, config_type):
        try:
            for suffix in ('ini', 'toml', 'json', 'yaml'):
                path = os.path.join(self.config['FRP_CONFIG_DIR'],
                                    f'{config_type}.{suffix}')
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        return f.read()
            return ''
        except Exception as e:
            print(f"[ERROR] 加载配置文件失败: {e}")
            return ''

    # ------------------------------------------------------------------ #
    # 配置快照与回滚（P3-⑦）
    # ------------------------------------------------------------------ #
    def snapshot_dir(self, config_type):
        d = os.path.join(self.config['FRP_CONFIG_DIR'], 'snapshots', config_type)
        os.makedirs(d, exist_ok=True)
        return d

    def _snapshot_index(self, config_type):
        d = self.snapshot_dir(config_type)
        idx = os.path.join(d, 'index.json')
        if os.path.exists(idx):
            try:
                with open(idx, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def _write_snapshot_index(self, config_type, entries):
        d = self.snapshot_dir(config_type)
        with open(os.path.join(d, 'index.json'), 'w', encoding='utf-8') as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    def create_snapshot(self, config_type, content=None, comment=''):
        """为某配置生成一份快照。content 缺省时取当前配置内容。返回 {id,ts,comment}。"""
        if content is None:
            content = self.load_config(config_type)
        if content is None:
            content = ''
        d = self.snapshot_dir(config_type)
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        sid = ts
        path = os.path.join(d, sid + '.cfg')
        n = 1
        while os.path.exists(path):
            n += 1
            sid = '%s_%d' % (ts, n)
            path = os.path.join(d, sid + '.cfg')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        entries = self._snapshot_index(config_type)
        entries.append({'id': sid, 'ts': ts, 'comment': comment or ''})
        # 仅保留最近 50 份，超出删除最旧
        if len(entries) > 50:
            for old in entries[:-50]:
                oldp = os.path.join(d, old['id'] + '.cfg')
                if os.path.exists(oldp):
                    try:
                        os.remove(oldp)
                    except Exception:
                        pass
            entries = entries[-50:]
        self._write_snapshot_index(config_type, entries)
        return {'id': sid, 'ts': ts, 'comment': comment or ''}

    def list_snapshots(self, config_type):
        return sorted(self._snapshot_index(config_type),
                      key=lambda x: x.get('ts', ''), reverse=True)

    def read_snapshot(self, config_type, snapshot_id):
        d = self.snapshot_dir(config_type)
        path = os.path.join(d, snapshot_id + '.cfg')
        if not os.path.exists(path) or not re.match(r'^[\w\-]+$', snapshot_id or ''):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def delete_snapshot(self, config_type, snapshot_id):
        d = self.snapshot_dir(config_type)
        path = os.path.join(d, snapshot_id + '.cfg')
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        entries = [e for e in self._snapshot_index(config_type) if e.get('id') != snapshot_id]
        self._write_snapshot_index(config_type, entries)
        return True

    def rollback_snapshot(self, config_type, snapshot_id):
        """回滚到指定快照：先为当前配置生成一份「回滚前」快照，再把快照内容写回当前配置。"""
        content = self.read_snapshot(config_type, snapshot_id)
        if content is None:
            return False, '快照不存在或已被删除'
        try:
            self.create_snapshot(config_type, comment='回滚前自动快照')
        except Exception as e:
            print(f"[WARN] 回滚前快照失败: {e}")
        target = self.resolve_config_file(config_type)
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, '已回滚到快照 %s' % snapshot_id

    # ------------------------------------------------------------------ #
    # 配置解析（唯一权威路径）
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # 进程自愈 / 监控（P1：避免半夜静默掉线）
    # ------------------------------------------------------------------ #
    def _load_monitor_settings(self):
        """从应用设置读取自愈守护开关与连崩上限（每次心跳刷新，改设置无需重启）"""
        s = self.load_app_settings()
        self._watchdog_enabled = bool(s.get('watchdog_enabled', True))
        try:
            self._watchdog_max = int(s.get('watchdog_max_crashes') or self.WATCHDOG_MAX_CRASHES)
        except (TypeError, ValueError):
            self._watchdog_max = self.WATCHDOG_MAX_CRASHES
        if self._watchdog_max < 1:
            self._watchdog_max = self.WATCHDOG_MAX_CRASHES

    def start_monitor(self):
        """启动监控线程（自愈 + 日志轮转）。幂等，重复调用只起一个。"""
        if getattr(self, '_watchdog_thread', None) is not None and self._watchdog_thread.is_alive():
            return self._watchdog_thread
        self._watchdog_stop = threading.Event()
        t = threading.Thread(target=self._monitor_loop, name='frp-monitor', daemon=True)
        self._watchdog_thread = t
        t.start()
        return t

    def stop_monitor(self):
        stop = getattr(self, '_watchdog_stop', None)
        if stop is not None:
            stop.set()

    def _monitor_loop(self):
        while not self._watchdog_stop.is_set():
            try:
                self._load_monitor_settings()
                if getattr(self, '_watchdog_enabled', True):
                    self._watchdog_tick()
                self._maybe_rotate_logs()
                self._auto_restart_tick()
            except Exception as e:
                print(f"[WARN] 监控线程异常: {e}")
            # 用 Event.wait 既能定时又能被 stop 立即唤醒
            self._watchdog_stop.wait(self.WATCHDOG_INTERVAL)

    def _watchdog_tick(self):
        for mode in ('client', 'server'):
            if not self._desired.get(mode):
                self._down_alerted[mode] = False
                continue
            st = self.get_frp_status().get(mode) or {}
            if st.get('running'):
                cr = self._crash[mode]
                if cr['count'] and (time.time() - cr['last']) > 30:
                    cr['count'] = 0
                self._down_alerted[mode] = False
                continue
            # 期望运行但进程不在 → 掉线告警（仅首次提醒，避免刷屏）+ 自愈
            label = self.MODE_LABEL.get(mode, mode)
            if not self._down_alerted.get(mode):
                self.send_alert(f"FRP {label} 已掉线，正在尝试自动重启（自愈守护已介入）",
                                title='FRP 掉线提醒')
                self._down_alerted[mode] = True
            self._self_heal(mode)

    def _self_heal(self, mode):
        label = self.MODE_LABEL.get(mode, mode)
        cr = self._crash[mode]
        now = time.time()
        if (now - cr['first']) > self.WATCHDOG_WINDOW:
            cr['count'] = 0
            cr['first'] = now
        cr['count'] += 1
        if cr['count'] > self._watchdog_max:
            self._desired[mode] = False
            msg = (f"自愈失败 · {label} 在 {self.WATCHDOG_WINDOW}s 内连续崩溃 "
                   f"{cr['count']} 次，已停止自动重启，请检查配置与日志")
            self.write_event(msg)
            self.send_alert(f"【严重】FRP {label} 自愈失败：连续崩溃超过 {self._watchdog_max} 次，"
                            f"已停止自动重启，请手动排查", title='FRP 自愈失败')
            return
        backoff = min(cr['count'] * 3, 30)   # 第 n 次崩溃等待 n*3 秒（上限 30s）
        time.sleep(backoff)
        cfg = self.resolve_config_file(mode)
        ok, msg = self.start_frp(cfg, mode)
        cr['last'] = time.time()
        if ok:
            cr['count'] = 0
            cr['first'] = now
            self.write_event(f"自愈重启 {label} 成功")
        else:
            self.write_event(f"自愈重启 {label} 失败（第 {cr['count']} 次）· {msg}")

    def set_desired(self, mode, running):
        """登记某模式的「期望运行状态」，供自愈守护判断是否需拉起。"""
        if mode in self._desired:
            self._desired[mode] = bool(running)
            if running:
                self._crash[mode] = {'count': 0, 'first': 0.0, 'last': 0.0}

    def get_watchdog_status(self):
        """返回自愈守护状态，供前端 / API 展示。"""
        out = {}
        # 只取一次状态：get_frp_status() 会遍历进程，放在循环里会重复扫描
        st = self.get_frp_status()
        for mode in ('client', 'server'):
            out[mode] = {
                'desired': bool(self._desired.get(mode)),
                'crashes': self._crash[mode]['count'],
                'running': st.get(mode, {}).get('running', False),
            }
        out['enabled'] = getattr(self, '_watchdog_enabled', True)
        out['max_crashes'] = getattr(self, '_watchdog_max', self.WATCHDOG_MAX_CRASHES)
        return out

    # ------------------------------------------------------------------ #
    # 定时重启 FRP（v1.13.0）：按间隔小时或每天固定时刻重启 frpc / frps
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_hhmm(s):
        """'HH:MM' → (H, M)；非法返回 None。"""
        try:
            parts = str(s or '').strip().split(':')
            if len(parts) != 2:
                return None
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h < 24 and 0 <= m < 60:
                return (h, m)
        except (ValueError, TypeError):
            pass
        return None

    def _auto_restart_tick(self):
        """监控线程内每 5 秒调用一次：到期则重启勾选的 frpc / frps。"""
        s = self.load_app_settings()
        now = time.time()
        if not s.get('auto_restart_enabled'):
            # 关闭期间持续刷新计时基准，避免重新开启后立刻触发
            self._ar_last_interval = now
            self._ar_last_daily = time.strftime('%Y-%m-%d')
            self._ar_next_due = 0.0
            return
        modes = []
        if s.get('auto_restart_frpc', True):
            modes.append('client')
        if s.get('auto_restart_frps', True):
            modes.append('server')
        if not modes:
            self._ar_next_due = 0.0
            return

        due = False
        if s.get('auto_restart_mode', 'interval') == 'daily':
            hm = self._parse_hhmm(s.get('auto_restart_time', '04:00'))
            if hm is None:
                self._ar_next_due = 0.0
                return
            today = time.strftime('%Y-%m-%d')
            hhmm = time.strftime('%H:%M')
            target = '%02d:%02d' % hm
            # 到点且今天还没触发过（tick 粒度 5s，HH:MM 相等即命中）
            if hhmm >= target and self._ar_last_daily != today:
                due = True
                self._ar_last_daily = today
                self._ar_last_interval = now
            self._ar_next_due = 0.0
        else:
            try:
                hours = int(s.get('auto_restart_interval', 24) or 24)
            except (TypeError, ValueError):
                hours = 24
            hours = max(1, min(hours, 720))
            # 设置变了 → 重新计时，避免改个数字马上重启
            if self._ar_interval_used != hours:
                self._ar_interval_used = hours
                self._ar_last_interval = now
            period = hours * 3600
            if now - self._ar_last_interval >= period:
                due = True
                self._ar_last_interval = now
            self._ar_next_due = self._ar_last_interval + period

        if not due:
            return
        label_all = []
        for mode in modes:
            label = self.MODE_LABEL.get(mode, mode)
            st = self.get_frp_status().get(mode) or {}
            if not (st.get('running') or self._desired.get(mode)):
                self._ar_last_fire[mode] = now
                self.write_event(_m(f"定时重启跳过 {label} · 当前未运行",
                                    f"Scheduled restart skipped {label} · not running"))
                continue
            self.stop_frp(mode)
            self.kill_frp_mode(mode)
            time.sleep(1)
            ok, msg = self.start_frp(self.resolve_config_file(mode), mode)
            self._ar_last_fire[mode] = time.time()
            if ok:
                self.write_event(f"定时重启 {label} 成功 · {msg}")
            else:
                self.write_event(f"定时重启 {label} 失败 · {msg}")
                self.send_alert(f"FRP {label} 定时重启失败：{msg}", title='FRP 定时重启失败')
            label_all.append(label)
        if label_all:
            print(f"[INFO] 定时重启完成：{' / '.join(label_all)}")

    def get_auto_restart_status(self):
        """定时重启：当前设置 + 上次触发 / 下次预计，供前端展示。"""
        s = self.load_app_settings()
        out = {k: s.get(k) for k in ('auto_restart_enabled', 'auto_restart_mode',
                                     'auto_restart_interval', 'auto_restart_time',
                                     'auto_restart_frpc', 'auto_restart_frps')}
        out['last_fire'] = {
            'client': self._ar_last_fire.get('client', 0.0),
            'server': self._ar_last_fire.get('server', 0.0),
        }
        nd = getattr(self, '_ar_next_due', 0.0)
        out['next_due'] = nd if nd and s.get('auto_restart_enabled') else 0
        return out

    # ------------------------------------------------------------------ #
    # 日志轮转
    # ------------------------------------------------------------------ #
    def _maybe_rotate_logs(self):
        try:
            log_dir = self.config['FRP_LOG_DIR']
            for f in os.listdir(log_dir):
                if (f.startswith('frp') and f.endswith('.log')) or f == self.MANAGER_LOG:
                    p = os.path.join(log_dir, f)
                    try:
                        if os.path.getsize(p) > self.LOG_ROTATE_BYTES:
                            self._rotate_one(p)
                    except OSError:
                        pass
        except OSError:
            pass

    def _rotate_one(self, path):
        keep = self.LOG_ROTATE_KEEP
        oldest = f"{path}.{keep}"
        try:
            if os.path.exists(oldest):
                os.remove(oldest)
        except OSError:
            pass
        for i in range(keep - 1, 0, -1):
            src = f"{path}.{i}"
            if os.path.exists(src):
                try:
                    os.replace(src, f"{path}.{i + 1}")
                except OSError:
                    pass
        try:
            if os.path.exists(path):
                os.replace(path, f"{path}.1")
        except OSError:
            pass

    def rotate_now(self, manual=True):
        """立即轮转所有运行日志（手动按钮用，不受大小限制）。"""
        try:
            log_dir = self.config['FRP_LOG_DIR']
            rotated = 0
            for f in os.listdir(log_dir):
                if (f.startswith('frp') and f.endswith('.log')) or f == self.MANAGER_LOG:
                    self._rotate_one(os.path.join(log_dir, f))
                    rotated += 1
            if manual:
                self.write_event(f"手动轮转日志完成 · 共 {rotated} 个文件")
            return rotated
        except Exception as e:
            print(f"[WARN] 日志轮转失败: {e}")
            return 0

    # ------------------------------------------------------------------ #
    # 操作审计日志
    # ------------------------------------------------------------------ #
    def audit_event(self, action, target='', result='', detail='', source=''):
        """记录一条操作审计（来源 / 时间 / 动作 / 对象 / 结果 / 明细）。"""
        try:
            os.makedirs(self.config['FRP_LOG_DIR'], exist_ok=True)
            line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{source}\t{action}\t"
                    f"{target}\t{result}\t{detail}\n")
            with open(self._audit_path, 'a', encoding='utf-8') as f:
                f.write(line)
            self._trim_audit()
            return True
        except Exception as e:
            print(f"[WARN] 写入审计日志失败: {e}")
            return False

    def _trim_audit(self):
        try:
            if not os.path.exists(self._audit_path):
                return
            with open(self._audit_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            if len(lines) <= self.AUDIT_MAX_LINES:
                return
            with open(self._audit_path, 'w', encoding='utf-8') as f:
                f.writelines(lines[-self.AUDIT_MAX_LINES:])
        except OSError:
            pass

    def read_audit(self, lines=200):
        try:
            if not os.path.exists(self._audit_path):
                return ''
            with open(self._audit_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
            content = [l.rstrip('\n') for l in content if l.strip()]
            if lines and lines > 0:
                content = content[-lines:]
            return '\n'.join(content)
        except Exception:
            return ''

    # ------------------------------------------------------------------ #
    # 配置安全扫描
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_webserver(text):
        res = {'addr': None, 'port': None, 'user': None, 'password': None}
        m = re.search(r'(?ims)\[webServer\](.*?)(?=\n\[|\Z)', text)
        block = m.group(1) if m else ''
        for key in ('addr', 'port', 'user', 'password'):
            mm = re.search(r'(?im)^\s*' + key + r'\s*[=:]\s*["\']?([^\s"\']+)', block)
            if mm:
                res[key] = int(mm.group(1)) if key == 'port' else mm.group(1)
        # toml 点号写法
        if any(v is None for v in res.values()):
            for line in text.splitlines():
                s = line.strip()
                if not s or s[0] in '#;[':
                    continue
                dm = re.match(r'(?i)^webServer\s*\.\s*([A-Za-z_]+)\s*[=:]\s*(.*)$', s)
                if not dm:
                    continue
                k = dm.group(1).lower()
                if k in res and res[k] is None:
                    v = dm.group(2).strip().strip('"\'')
                    res[k] = int(v) if k == 'port' else v
        if res['addr'] is None:
            res['addr'] = '0.0.0.0'
        return res

    @staticmethod
    def _parse_token(text):
        for pat in (r'(?im)^\s*auth\.token\s*[=:]\s*["\']?([^\s"\']+)',
                    r'(?im)^\s*token\s*[=:]\s*["\']?([^\s"\']+)'):
            m = re.search(pat, text)
            if m:
                return m.group(1).strip().strip('"\'')
        return ''

    def scan_security(self):
        """扫描 frps/frpc 配置里的风险项，返回问题列表（含级别与修复建议）。"""
        issues = []
        for mode in ('server', 'client'):
            cfg = self.resolve_config_file(mode)
            try:
                with open(cfg, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            except OSError:
                continue
            if mode == 'server':
                ws = self._parse_webserver(text)
                if ws.get('port'):
                    if not ws.get('user') or not ws.get('password'):
                        issues.append({'level': 'high', 'mode': 'server',
                                       'msg': _m('frps 管理面板已开启但未设置账号密码，公网可直连控制',
                                                 'The frps dashboard is on but has no credentials; anyone on the internet can control it'),
                                       'fix': _m('在 [webServer] 段设置 user 与 password，或 bind 到 127.0.0.1',
                                                 'Set user and password in the [webServer] section, or bind it to 127.0.0.1')})
                    if ws.get('addr') in (None, '0.0.0.0', '::', ''):
                        issues.append({'level': 'medium', 'mode': 'server',
                                       'msg': _m('frps 管理面板监听 0.0.0.0（所有网卡），建议仅监听内网',
                                                 'The frps dashboard listens on 0.0.0.0 (all interfaces); bind it to the LAN only'),
                                       'fix': 'webServer.addr = "127.0.0.1"'})
                tok = self._parse_token(text)
                if not tok:
                    issues.append({'level': 'high', 'mode': 'server',
                                   'msg': _m('frps 未设置 auth.token，任何人都能接入你的服务端',
                                             'frps has no auth.token; anyone can connect to your server'),
                                   'fix': _m('在配置中设置 auth.token = "复杂字符串"',
                                             'Set auth.token = "a-strong-random-string" in the config')})
            else:
                tok = self._parse_token(text)
                if not tok:
                    issues.append({'level': 'medium', 'mode': 'client',
                                   'msg': _m('frpc 未设置 token，与服务端可能不一致或被拒绝',
                                             'frpc has no token; it may not match the server and get rejected'),
                                   'fix': _m('token 需与服务端 auth.token 一致',
                                             'The token must match the server auth.token')})
                m = re.search(r'(?:server_addr|serverAddr)\s*=\s*["\']?([0-9a-zA-Z.\-]+)', text)
                if m and m.group(1).strip().lower() == '0.0.0.0':
                    issues.append({'level': 'high', 'mode': 'client',
                                   'msg': _m('frpc 的 server_addr 不能填 0.0.0.0',
                                             'server_addr must not be 0.0.0.0'),
                                   'fix': _m('改为服务端可达的 IP 或域名',
                                             'Use an IP or domain that can reach the server')})
        self._security_issues = issues
        return issues

    # ------------------------------------------------------------------ #
    # 离线包导入（把已下载的 frp_*.zip / .tar.gz 安装到 bin/）
    # ------------------------------------------------------------------ #
    def install_frp_from_archive(self, archive_path):
        extract_dir = os.path.join(self.config['TEMP_DIR'],
                                   'import_' + time.strftime('%Y%m%d%H%M%S'))
        try:
            os.makedirs(extract_dir, exist_ok=True)
            if archive_path.endswith('.zip'):
                with zipfile.ZipFile(archive_path) as z:
                    z.extractall(extract_dir)
            elif archive_path.endswith(('.tar.gz', '.tgz')):
                with tarfile.open(archive_path, 'r:gz') as t:
                    try:
                        t.extractall(extract_dir, filter='data')
                    except TypeError:
                        t.extractall(extract_dir)
            else:
                return False, '不支持的压缩包格式（仅支持 .zip / .tar.gz）'
        except Exception as e:
            return False, f'解压失败: {e}'

        copied = []
        ok = False
        for mode, name in (('client', 'frpc'), ('server', 'frps')):
            found = None
            for root, _, files in os.walk(extract_dir):
                for f in files:
                    b = f.lower()
                    if b == name or b == name + self.bin_ext:
                        found = os.path.join(root, f)
                        break
                if found:
                    break
            if not found:
                continue
            try:
                self.archive_current_binary(mode)
                dst = os.path.join(self.config['FRP_BIN_DIR'],
                                   self.frpc_bin_name if mode == 'client' else self.frps_bin_name)
                shutil.copy2(found, dst)
                copied.append(name)
                ok = True
            except PermissionError:
                shutil.rmtree(extract_dir, ignore_errors=True)
                return False, f'{name} 正在被占用，请先停止 FRP 再导入'
            except OSError as e:
                return False, f'复制 {name} 失败: {e}'
        shutil.rmtree(extract_dir, ignore_errors=True)
        if not ok:
            return False, '压缩包内未找到 frpc / frps 二进制'
        self.ensure_executable()
        self.write_event('离线导入 FRP 成功 · ' + ', '.join(copied))
        self.audit_event('import_frp', 'bin', 'success', ', '.join(copied))
        return True, '已导入: ' + ', '.join(copied)

    # ------------------------------------------------------------------ #
    # 掉线告警推送（P1：frp 失联 / 自愈失败 时通知）
    # ------------------------------------------------------------------ #
    def send_alert(self, message, title='FRP Manager 告警'):
        s = self.load_app_settings()
        if not s.get('alert_enabled'):
            return False
        etype = s.get('alert_type', 'dingtalk')
        if etype == 'email':
            return self._send_alert_email(s, message, title)
        url = (s.get('alert_url') or '').strip()
        if not url:
            return False
        payload = self._alert_payload(etype, message, title)
        try:
            import requests
        except ImportError:
            return False
        try:
            r = requests.post(url, json=payload, timeout=10)
            return r.status_code < 400
        except Exception as e:
            print(f"[WARN] 发送告警失败: {e}")
            return False

    @staticmethod
    def _alert_payload(etype, message, title):
        text = f"{title}\n{message}"
        if etype == 'feishu':
            return {"msg_type": "text", "content": {"text": text}}
        return {"msgtype": "text", "text": {"content": text}}

    def _send_alert_email(self, s, message, title):
        try:
            import smtplib
            import ssl
            from email.mime.text import MIMEText
        except ImportError:
            return False
        host = (s.get('alert_email_host') or '').strip()
        user = (s.get('alert_email_user') or '').strip()
        pwd = s.get('alert_email_pass') or ''
        to = (s.get('alert_email_to') or '').strip()
        if not (host and user and to):
            return False
        try:
            port = int(s.get('alert_email_port') or 465)
        except (TypeError, ValueError):
            port = 465
        try:
            msg = MIMEText(message, 'plain', 'utf-8')
            msg['Subject'] = title
            msg['From'] = user
            msg['To'] = to
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as srv:
                srv.login(user, pwd)
                srv.sendmail(user, [to], msg.as_string())
            return True
        except Exception as e:
            print(f"[WARN] 发送告警邮件失败: {e}")
            return False

    def resolve_config_file(self, mode='client'):
        """返回该模式【唯一权威】配置文件路径（client / server）。

        网页端与系统托盘都经此函数，保证「看到的就是 frpc/frps 实际用到的」，
        杜绝 client_simple.ini / client.ini 等配置分叉。

        优先级：{mode}.toml > {mode}.ini > 生成一份默认配置。
        """
        cfg_dir = self.config['FRP_CONFIG_DIR']
        os.makedirs(cfg_dir, exist_ok=True)
        canon_ini = os.path.join(cfg_dir, f'{mode}.ini')
        canon_toml = os.path.join(cfg_dir, f'{mode}.toml')
        # 用户已保存过：优先 toml，其次 ini（这两个也是 save_config 写入的文件）
        if os.path.exists(canon_toml):
            return canon_toml
        if os.path.exists(canon_ini):
            return canon_ini
        # 生成一份可直接编辑的默认配置
        # 服务端默认给 TOML：frp 的 ini 解析器【不识别 [webServer] 段】，
        # 会导致 dashboard/管理API 压根不启动（只能用旧的 dashboard_* 字段）。
        content = self._default_config(mode)
        target = canon_toml if mode == 'server' else canon_ini
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
        return target

    def has_user_config(self, mode='client'):
        """是否已存在【用户自己的】配置（而不是系统自动生成的默认模板）。

        用于「随程序启动」判断：首次运行、只有默认模板时，拉起 frpc/frps
        必然因配置不可用而报错，所以此时应跳过；等用户在面板里配置完成后，
        再由用户主动勾选「随程序启动 FRPC / FRPS」。
        """
        cfg_dir = self.config['FRP_CONFIG_DIR']
        default_txt = self._default_config(mode).strip()
        for ext in ('.toml', '.ini'):
            path = os.path.join(cfg_dir, f'{mode}{ext}')
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
            except Exception:
                continue
            if content and content != default_txt:
                return True
        return False

    def _default_config(self, mode='client'):
        """生成默认配置内容（与网页端历史默认保持一致）。"""
        if mode == 'client':
            return (
                "[common]\n"
                "server_addr = 127.0.0.1\n"
                "server_port = 7000\n"
                "token = \n"
                "\n"
                "[tcp-1]\n"
                "type = tcp\n"
                "local_ip = 127.0.0.1\n"
                "local_port = 8080\n"
                "remote_port = 8080\n"
            )
        # 服务端默认配置用 TOML：
        # frp 的 ini 解析器不认 [webServer] 段（只认旧的 dashboard_* 字段），
        # 用 ini 写 [webServer] 会导致管理面板/管理API 完全不启动。
        return (
            "# frps 服务端配置（TOML 格式，frp 0.52+ 推荐）\n"
            "\n"
            "#【服务端口】客户端通过此端口接入\n"
            "bindPort = 7000\n"
            "\n"
            "#【授权码，客户端要用同一个，建议改复杂点】\n"
            'auth.token = "Rmsz@0718"\n'
            "\n"
            "#【服务端接收公网 http 请求的端口，按需开启】\n"
            "# vhostHTTPPort = 7002\n"
            "\n"
            "#【每个客户端的链接上限】\n"
            "transport.maxPoolCount = 15\n"
            "\n"
            "#【dashboard / 管理API 配置】务必保留，否则本页面的连接信息不可用\n"
            'webServer.addr = "0.0.0.0"\n'
            "webServer.port = 7500\n"
            'webServer.user = "admin"\n'
            'webServer.password = "Rmsz@0718"\n'
            "\n"
            "# 日志\n"
            'log.to = "./frps.log"\n'
            'log.level = "info"\n'
            "log.maxDays = 3\n"
        )

    # ------------------------------------------------------------------ #
    # 流量与资源监控（P2-②）
    # ------------------------------------------------------------------ #
    def _read_server_config(self):
        try:
            p = self.resolve_config_file('server')
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return ''

    def _frps_api_base(self):
        """返回 (base_url, user, password) 或 None（无 dashboard/管理API）。"""
        ws = self._parse_webserver(self._read_server_config())
        if not ws or not ws.get('port'):
            return None
        addr = ws.get('addr') or '0.0.0.0'
        if addr in ('0.0.0.0', '', None):
            addr = '127.0.0.1'
        return f"http://{addr}:{ws['port']}", ws.get('user'), ws.get('password')

    def _frps_api_get(self, path):
        base = self._frps_api_base()
        if not base:
            return None
        url, user, pwd = base
        try:
            import requests
        except ImportError:
            return None
        auth = (user, pwd or '') if user else None
        try:
            r = requests.get(url + path, auth=auth, timeout=2)
            if r.status_code == 200:
                return r.json()
        except Exception:
            return None
        return None

    def _process_stats(self):
        """用 psutil 取 frpc/frps 进程的 CPU / 内存占用。"""
        res = {'client': {}, 'server': {}}
        try:
            import psutil
        except ImportError:
            return res
        me = os.getpid()
        for mode in ('client', 'server'):
            bin_name = 'frpc' if mode == 'client' else 'frps'
            found = None
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                if proc.pid == me:
                    continue
                try:
                    cl = proc.info.get('cmdline') or []
                    nm = proc.info.get('name') or ''
                    if bin_name in nm or any(bin_name in (c or '') for c in cl):
                        found = proc
                        break
                except Exception:
                    continue
            if found:
                try:
                    res[mode] = {
                        'pid': found.pid,
                        'cpu': round(found.cpu_percent(interval=0.1), 1),
                        'mem_mb': round(found.memory_info().rss / 1024 / 1024, 1),
                    }
                except Exception:
                    pass
        return res

    def get_traffic_stats(self):
        """聚合 frps 管理API 的各代理流量 + 进程资源占用。

        返回 {'reachable': bool, 'proxies': [...], 'process': {...}}。
        frps 未运行 / 未开放管理API 时 reachable=False，proxies 为空，process 仍尽量返回。
        """
        out = {'reachable': False, 'proxies': [], 'process': self._process_stats()}
        data = self._frps_api_get('/api/proxy/tcp')
        if data is None:
            return out
        out['reachable'] = True
        proxies = []
        for kind in ('tcp', 'udp', 'http', 'https', 'stcp', 'sudp', 'xtcp'):
            j = self._frps_api_get('/api/proxy/' + kind)
            if not j or 'proxies' not in j:
                continue
            for p in j['proxies']:
                proxies.append({
                    'name': p.get('name'),
                    'type': kind,
                    'todayIn': p.get('todayTrafficIn', 0),
                    'todayOut': p.get('todayTrafficOut', 0),
                    'curConns': p.get('curConns', 0),
                    'totalConns': p.get('totalConns', 0),
                })
        out['proxies'] = proxies
        return out

    # ------------------------------------------------------------------ #
    # 配置模板库（P2-⑥）
    # ------------------------------------------------------------------ #
    # 模板占位符：给出中文名、默认值与填写说明，前端据此生成表单，
    # 避免套用时把 {LOCAL_IP} 这类字面量直接写进配置导致 frpc 起不来。
    TPL_PLACEHOLDER_META = {
        'LOCAL_IP': {'label': '本机 IP', 'default': '127.0.0.1',
                     'tip': '被穿透服务所在的本机地址，同机填 127.0.0.1'},
        'LOCAL_PORT': {'label': '本地端口', 'default': '',
                       'tip': '本机服务监听端口，如 80 / 5000 / 3389'},
        'REMOTE_PORT': {'label': '远程端口', 'default': '6000',
                        'tip': '服务端对外开放的端口，需已在防火墙放行'},
        'SUBDOMAIN': {'label': '子域名', 'default': '',
                      'tip': '仅 http/https 需要，服务端须已配置 subdomain_host'},
    }

    def _tpl_placeholders(self, toml_text):
        """按出现顺序提取模板里的 {PLACEHOLDER}，附带中文名 / 默认值 / 说明。"""
        keys = []
        for m in re.finditer(r'\{([A-Z0-9_]+)\}', toml_text or ''):
            if m.group(1) not in keys:
                keys.append(m.group(1))
        out = []
        for k in keys:
            meta = self.TPL_PLACEHOLDER_META.get(k, {'label': k, 'default': '', 'tip': ''})
            out.append({'key': k, 'label': meta.get('label', k),
                        'default': meta.get('default', ''), 'tip': meta.get('tip', '')})
        return out

    def get_config_templates(self):
        tpls = [
            {'id': 'ssh', 'name': 'SSH 远程', 'desc': '把本机 22 端口映射出去，远程用 ssh 连接',
             'toml': '[[proxies]]\nname = "ssh"\ntype = "tcp"\nlocalIP = "{LOCAL_IP}"\nlocalPort = 22\nremotePort = {REMOTE_PORT}\nuseEncryption = true\n'},
            {'id': 'web_http', 'name': 'Web 站点（http）', 'desc': '把本机 Web 服务通过子域名暴露到公网',
             'toml': '[[proxies]]\nname = "web"\ntype = "http"\nlocalIP = "{LOCAL_IP}"\nlocalPort = {LOCAL_PORT}\nsubdomain = "{SUBDOMAIN}"\n'},
            {'id': 'web_https', 'name': 'Web 站点（https）', 'desc': '复用已有证书暴露 https 站点',
             'toml': '[[proxies]]\nname = "web"\ntype = "https"\nlocalIP = "{LOCAL_IP}"\nlocalPort = {LOCAL_PORT}\nsubdomain = "{SUBDOMAIN}"\n'},
            {'id': 'rdp', 'name': '远程桌面 RDP', 'desc': 'Windows 远程桌面 3389',
             'toml': '[[proxies]]\nname = "rdp"\ntype = "tcp"\nlocalIP = "{LOCAL_IP}"\nlocalPort = 3389\nremotePort = {REMOTE_PORT}\n'},
            {'id': 'game_udp', 'name': '游戏联机（UDP）', 'desc': '把本机 UDP 端口映射出去用于联机',
             'toml': '[[proxies]]\nname = "game"\ntype = "udp"\nlocalIP = "{LOCAL_IP}"\nlocalPort = {LOCAL_PORT}\nremotePort = {REMOTE_PORT}\n'},
            {'id': 'nas', 'name': '群晖 / 威联通', 'desc': 'NAS 管理界面（5000/5001）穿透',
             'toml': '[[proxies]]\nname = "nas"\ntype = "tcp"\nlocalIP = "{LOCAL_IP}"\nlocalPort = 5000\nremotePort = {REMOTE_PORT}\n'},
        ]
        for t in tpls:
            t['placeholders'] = self._tpl_placeholders(t['toml'])
        return tpls

    def apply_config_template(self, template_id, placeholders=None):
        placeholders = placeholders or {}
        tpl = next((t for t in self.get_config_templates() if t['id'] == template_id), None)
        if not tpl:
            return False, '未找到该模板'
        content = tpl['toml']
        for k, v in placeholders.items():
            content = content.replace('{' + str(k).upper() + '}', str(v))
        # 仍有未替换的占位符说明调用方漏填：与其写出一份 frpc 起不来的配置，不如直接报错
        left = sorted(set(re.findall(r'\{([A-Z0-9_]+)\}', content)))
        if left:
            names = ', '.join(self.TPL_PLACEHOLDER_META.get(k, {}).get('label', k) for k in left)
            return False, '以下占位符未填写：%s' % names
        path = self.resolve_config_file('client')
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                existing = f.read()
        except Exception:
            existing = ''
        if path.endswith('.ini'):
            toml_common = self._ini_common_to_toml(existing)
            new_path = os.path.join(os.path.dirname(path), 'client.toml')
            combined = (toml_common.rstrip() + '\n\n' + content).rstrip() + '\n'
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(combined)
            return True, '已套用模板并生成 %s（原 ini 已保留）' % os.path.basename(new_path)
        combined = (existing.rstrip() + '\n\n' + content).rstrip() + '\n'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(combined)
        return True, '已追加代理到 %s' % os.path.basename(path)

    def _ini_common_to_toml(self, ini_text):
        """把 INI 客户端的 [common] 段转换成 TOML 公共段（去掉代理段）。"""
        out = []
        in_common = False
        for line in ini_text.splitlines():
            s = line.strip()
            if s.startswith('['):
                in_common = s.lower().startswith('[common')
                continue
            if not in_common:
                continue
            if not s or s.startswith('#') or s.startswith(';'):
                continue
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', s)
            if not m:
                continue
            k, v = m.group(1), m.group(2).strip()
            key = {'server_addr': 'serverAddr', 'server_port': 'serverPort',
                   'token': 'auth.token', 'user': 'user', 'protocol': 'protocol',
                   'tls_enable': 'tls.enable', 'log_file': 'log.to',
                   'log_level': 'log.level', 'log_max_days': 'log.maxDays',
                   'heartbeat_interval': 'heartbeatInterval',
                   'heartbeat_timeout': 'heartbeatTimeout'}.get(k, k)
            if v.lower() in ('true', 'false'):
                out.append('%s = %s' % (key, v.lower()))
            elif re.match(r'^-?\d+$', v):
                out.append('%s = %s' % (key, v))
            else:
                out.append('%s = "%s"' % (key, v))
        return '\n'.join(out)

    # ------------------------------------------------------------------ #
    # 表单式代理编辑器（P2-⑤）
    # ------------------------------------------------------------------ #
    PROXY_KNOWN = ['name', 'type', 'localIP', 'localPort', 'remotePort', 'customDomains',
                   'subdomain', 'useEncryption', 'useCompression', 'sk', 'role', 'serverName',
                   'locations', 'plugin', 'pluginLocalAddr', 'bandwidthLimit']
    INI_PROXY_KEY_MAP = {
        'type': 'type', 'local_ip': 'localIP', 'local_port': 'localPort',
        'remote_port': 'remotePort', 'custom_domains': 'customDomains',
        'subdomain': 'subdomain', 'use_encryption': 'useEncryption',
        'use_compression': 'useCompression', 'sk': 'sk', 'role': 'role',
        'server_name': 'serverName', 'locations': 'locations',
        'plugin': 'plugin', 'plugin_local_addr': 'pluginLocalAddr',
        'bandwidth_limit': 'bandwidthLimit',
    }

    def parse_proxies(self, text):
        """解析 frpc 配置中的代理条目，支持 TOML([[proxies]]) 与 INI([name])。
        返回 {'format','common','proxies':[{field:value,'_extra':{}}]}"""
        text = text or ''
        if '[[proxies]]' in text:
            return self._parse_proxies_toml(text)
        return self._parse_proxies_ini(text)

    def _toml_value(self, raw):
        raw = raw.strip()
        if raw == 'true':
            return True
        if raw == 'false':
            return False
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            return raw[1:-1]
        if raw.startswith('['):
            inner = raw.strip('[]').strip()
            if not inner:
                return []
            return [self._toml_value(x.strip()) for x in inner.split(',')]
        try:
            return int(raw) if '.' not in raw else float(raw)
        except ValueError:
            return raw

    def _parse_proxies_toml(self, text):
        proxies = []
        blocks = re.split(r'(?m)^\s*\[\[proxies\]\]\s*$', text)
        header = blocks[0]
        for blk in blocks[1:]:
            d, extra, name = {}, {}, None
            for line in blk.splitlines():
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', s)
                if not m:
                    continue
                k, v = m.group(1), self._toml_value(m.group(2).strip())
                if k == 'name':
                    name = v
                elif k in self.PROXY_KNOWN:
                    d[k] = v
                else:
                    extra[k] = v
            if name is None:
                name = 'proxy%d' % (len(proxies) + 1)
            d['name'] = name
            d['_extra'] = extra
            proxies.append(d)
        return {'format': 'toml', 'common': header, 'proxies': proxies}

    def _parse_proxies_ini(self, text):
        proxies = []
        parts = re.split(r'(?m)^\s*\[([^\]]+)\]\s*$', text)
        common = parts[0]
        for i in range(1, len(parts), 2):
            sec = parts[i].strip()
            body = parts[i + 1] if i + 1 < len(parts) else ''
            if sec.lower() == 'common':
                common = body
                continue
            d, extra = {'name': sec, '_extra': {}}, {}
            for line in body.splitlines():
                s = line.strip()
                if not s or s.startswith('#') or s.startswith(';'):
                    continue
                m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', s)
                if not m:
                    continue
                k = m.group(1)
                mapped = self.INI_PROXY_KEY_MAP.get(k.lower(), k)
                if mapped == 'name':
                    continue
                v = m.group(2).strip()
                if mapped in self.PROXY_KNOWN:
                    if v.lower() in ('true', 'false'):
                        d[mapped] = (v.lower() == 'true')
                    elif re.match(r'^-?\d+$', v):
                        d[mapped] = int(v)
                    else:
                        d[mapped] = v
                else:
                    extra[mapped] = v
            proxies.append(d)
        return {'format': 'ini', 'common': common, 'proxies': proxies}

    def serialize_proxies(self, common, proxies):
        """公共段 + 代理列表 → frpc.toml 文本（统一 TOML [[proxies]]）。"""
        lines = []
        if common and common.strip():
            lines.append(common.rstrip())
            lines.append('')
        order = self.PROXY_KNOWN
        for d in proxies:
            lines.append('[[proxies]]')
            lines.append('name = "%s"' % (d.get('name', '') or ''))
            for k in order:
                if k == 'name' or k not in d:
                    continue
                lines.append(self._fmt_toml(k, d[k]))
            for k, v in (d.get('_extra', {}) or {}).items():
                if k in order:
                    continue
                lines.append(self._fmt_toml(k, v))
            lines.append('')
        return '\n'.join(lines).rstrip() + '\n'

    def _fmt_toml(self, k, v):
        if isinstance(v, bool):
            return '%s = %s' % (k, 'true' if v else 'false')
        if isinstance(v, (int, float)):
            return '%s = %s' % (k, v)
        if isinstance(v, list):
            return '%s = [%s]' % (k, ', '.join('"%s"' % x for x in v))
        return '%s = "%s"' % (k, v)

    def get_client_proxies(self):
        path = self.resolve_config_file('client')
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except Exception:
            text = ''
        return self.parse_proxies(text)

    def set_client_proxies(self, proxies):
        path = self.resolve_config_file('client')
        parsed = self.get_client_proxies()
        common = parsed.get('common', '')
        content = self.serialize_proxies(common, proxies)
        if path.endswith('.ini'):
            new_path = os.path.join(os.path.dirname(path), 'client.toml')
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, '已转换为 TOML 并写入 %s' % os.path.basename(new_path)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True, '已保存到 %s' % os.path.basename(path)

    # ------------------------------------------------------------------ #
    # frp token / 加密向导（P3-⑧）
    # ------------------------------------------------------------------ #
    def generate_token(self, length=32):
        """生成密码学安全的随机 token（十六进制）。"""
        try:
            return secrets.token_hex(int(length) if int(length) > 0 else 32)
        except (TypeError, ValueError):
            return secrets.token_hex(32)

    def set_auth_token(self, token, config_types=('client', 'server')):
        """把鉴权 token 写入 frps 与 frpc 配置。

        - TOML：确保存在 [auth] 段（server 设 method="token" + token；client 设 token）
        - INI：在 [common] 段写入 token = xxx
        返回 {config_type: 结果说明}
        """
        token = (token or '').strip()
        if not token:
            return {ct: 'token 为空' for ct in config_types}
        results = {}
        for ct in config_types:
            try:
                content = self.load_config(ct)
            except Exception:
                content = ''
            if not content:
                results[ct] = '当前无配置，未改动'
                continue
            is_toml = ('[[' in content) or ('serverAddr' in content) \
                or ('bindPort' in content) or content.lstrip().startswith('[')
            new_content = self._set_auth_token_toml(content, token) if is_toml \
                else self._set_auth_token_ini(content, token)
            try:
                with open(self.resolve_config_file(ct), 'w', encoding='utf-8') as f:
                    f.write(new_content)
                results[ct] = '已写入 token'
            except Exception as e:
                results[ct] = '写入失败: %s' % e
        return results

    def _set_auth_token_toml(self, content, token):
        lines = content.splitlines()
        out, i, n, replaced = [], 0, len(lines), False
        while i < n:
            line = lines[i]
            if line.strip() == '[auth]':
                out.append('[auth]')
                out.append('method = "token"')
                out.append('token = "%s"' % token)
                replaced = True
                i += 1
                while i < n and not lines[i].lstrip().startswith('['):
                    i += 1
                continue
            out.append(line)
            i += 1
        if not replaced:
            out.append('')
            out.append('[auth]')
            out.append('method = "token"')
            out.append('token = "%s"' % token)
        return '\n'.join(out).rstrip() + '\n'

    def _set_auth_token_ini(self, content, token):
        lines = content.splitlines()
        out, i, n, in_common, replaced = [], 0, len(lines), False, False
        while i < n:
            line = lines[i]
            s = line.strip()
            if s.startswith('['):
                in_common = s.lower().startswith('[common')
                out.append(line)
                i += 1
                continue
            if in_common and re.match(r'^token\s*=', s, re.I):
                out.append('token = %s' % token)
                replaced = True
                i += 1
                continue
            out.append(line)
            i += 1
        if not replaced:
            if not any(l.strip().lower().startswith('[common') for l in lines):
                out.insert(0, '[common]')
                out.insert(1, 'token = %s' % token)
            else:
                for idx, l in enumerate(out):
                    if l.strip().lower().startswith('[common'):
                        out.insert(idx + 1, 'token = %s' % token)
                        break
        return '\n'.join(out).rstrip() + '\n'

    def add_secure_proxy(self, proxy):
        """追加一条更安全的穿透代理（stcp / sudp 等），需预共享密钥 sk。

        proxy 字段：name, type(stcp/sudp), role(server/visitor), sk,
        serverName(visitor 必填), bindAddr, bindPort(visitor) 等。
        """
        if not isinstance(proxy, dict):
            return False, 'proxy 必须是对象'
        name = (proxy.get('name') or '').strip()
        ptype = (proxy.get('type') or '').strip().lower()
        if not name or ptype not in ('stcp', 'sudp'):
            return False, '需要 name 与 type(stcp/sudp)'
        parsed = self.get_client_proxies()
        proxies = parsed.get('proxies', [])
        if any((p.get('name') == name) for p in proxies):
            return False, '代理名 %s 已存在' % name
        d = {k: proxy[k] for k in proxy if k in self.PROXY_KNOWN}
        d['_extra'] = {k: v for k, v in proxy.items() if k not in self.PROXY_KNOWN}
        d['name'] = name
        d['type'] = ptype
        proxies.append(d)
        return self.set_client_proxies(proxies)
