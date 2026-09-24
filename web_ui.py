import io
import os
import re
import sys
import time
import socket
import threading
from flask import (Flask, render_template_string, request, jsonify,
                   send_from_directory, has_request_context)

# 导入FRP管理器
from frp_manager import FRPManager

app = Flask(__name__)

from frp_manager import resource_dir, data_dir

# 资源目录（只读）：static / 默认 configs / frp 二进制种子
BASE_DIR = resource_dir()
# 数据目录（可写持久）：用户配置 / 日志 / 临时 / 下载的二进制
DATA_DIR = data_dir()


# ---------------------------------------------------------------- 消息多语言
# 接口返回给前端的提示按界面语言（app_settings.ini [ui] lang）切换中英
_MSG_LANG = {'at': 0.0, 'lang': 'zh'}


def _msg_lang():
    now = time.time()
    if now - _MSG_LANG['at'] < 2.0:
        return _MSG_LANG['lang']
    lang = 'zh'
    try:
        import configparser
        f = os.path.join(DATA_DIR, 'configs', 'app_settings.ini')
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
    """按当前界面语言返回提示；英文缺省时回退中文"""
    if _msg_lang() != 'en':
        return zh
    return en if en else zh


def load_web_port(default=5000):
    """从 configs/web_port.ini 读取 Web 端口，环境变量 FRP_WEB_PORT 优先"""
    env_port = os.environ.get('FRP_WEB_PORT', '').strip()
    if env_port.isdigit():
        return int(env_port)

    port_file = os.path.join(DATA_DIR, 'configs', 'web_port.ini')
    if os.path.exists(port_file):
        try:
            with open(port_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('port'):
                        port = int(line.split('=')[1].strip())
                        if 1 <= port <= 65535:
                            return port
        except Exception:
            pass
    return default


config = {
    'WEB_PORT': load_web_port(),
    'FRP_BIN_DIR': os.path.join(DATA_DIR, 'bin'),
    'FRP_CONFIG_DIR': os.path.join(DATA_DIR, 'configs'),
    'FRP_LOG_DIR': os.path.join(DATA_DIR, 'logs'),
    'TEMP_DIR': os.path.join(DATA_DIR, 'temp'),
    'STATIC_DIR': os.path.join(BASE_DIR, 'web'),   # 页面模板与静态资源统一放 web/
}

# 创建必要的目录
for dir_path in [config['FRP_BIN_DIR'], config['FRP_CONFIG_DIR'],
                 config['FRP_LOG_DIR'], config['TEMP_DIR']]:
    os.makedirs(dir_path, exist_ok=True)

# 初始化FRP管理器
manager = FRPManager(config)
app.config['FRP_MANAGER'] = manager
app.config['CONFIG'] = config
# 面板版本号：main.py 启动时会用自身 VERSION 覆盖，侧栏/页脚即自动跟随更新
APP_VERSION = '1.0.0'
app.config['APP_VERSION'] = APP_VERSION


def app_version():
    """取当前程序版本（优先 main.py 注入的 APP_VERSION）"""
    return app.config.get('APP_VERSION') or APP_VERSION

# FRP 下载镜像选项（国内代理优先，对应 frp_manager.build_mirror_list）
MIRROR_CHOICES = [
    {'value': 'auto', 'label': '自动（官方 + 国内镜像回退）'},
    {'value': 'ghfast', 'label': 'ghfast.top 国内代理'},
    {'value': 'ghproxy_com', 'label': 'gh-proxy.com 国内代理'},
    {'value': 'ghproxy_net', 'label': 'ghproxy.net 国内代理'},
    {'value': 'mirror_ghproxy', 'label': 'mirror.ghproxy.com 国内代理'},
    {'value': 'github', 'label': '仅官方 GitHub（不使用代理）'},
]

# 初始化 Web 登录认证（账号密码 / 图形验证码开关都在 configs/web_auth.ini）
try:
    from web_auth import init_auth, load_auth_config
    init_auth(app, config)
except Exception as _e:
    print('[WARN] 登录认证模块初始化失败，已跳过: %s' % _e)
    load_auth_config = None


def resolve_config_file(mode='client'):
    """返回该模式【唯一权威】配置文件路径。

    实现统一收口到 FRPManager.resolve_config_file（单一事实来源），
    网页端与系统托盘共用同一逻辑，保证「网页/托盘看到的 = frpc/frps 实际用到的」，
    彻底杜绝 client_simple.ini / client.ini 等配置分叉问题。

    优先级：{mode}.toml > {mode}.ini > 生成一份默认配置。
    """
    manager = app.config.get('FRP_MANAGER')
    if manager is not None:
        return manager.resolve_config_file(mode)
    # 兜底：manager 尚未注入（仅测试/特殊场景）——直接按规范路径返回
    cfg_dir = config['FRP_CONFIG_DIR']
    for ext in ('toml', 'ini'):
        p = os.path.join(cfg_dir, f'{mode}.{ext}')
        if os.path.exists(p):
            return p
    return os.path.join(cfg_dir, f'{mode}.ini')


def check_client_server_addr(config_file):
    """校验客户端配置里的 server_addr 是否为无效地址（如 0.0.0.0）。

    返回 (ok, message)。ok=True 表示地址可用。
    说明：0.0.0.0 是「监听所有网卡」的含义，不能作为 frpc 去连接的目标地址，
    错误地填它会让 frpc 一启动就 dial tcp 0.0.0.0:7000 -> connection refused。
    """
    import re
    try:
        with open(config_file, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except OSError:
        return True, ''  # 读不到就放行，交给 frpc 自己报错

    m = re.search(r'(?:server_addr|serverAddr)\s*=\s*["\']?([0-9a-zA-Z.\-]+)["\']?', text)
    if not m:
        return True, ''  # 没找到 server 地址字段，交给 frpc 处理
    addr = m.group(1).strip().lower()
    if addr == '0.0.0.0':
        return False, ("server_addr 不能填 0.0.0.0——那是「监听所有网卡」的意思，"
                       "不能当连接目标。请改成 FRP 服务端实际可达的 IP 或域名"
                       "（例如 114.132.239.35）；若 frps 就跑在本机则填 127.0.0.1。")
    return True, ''


def parse_frps_webserver(config_content):
    """从服务端(frps)配置内容中解析 [webServer] 管理API 的地址/端口/账号。

    支持三种写法：
      1. ini/toml 的 [webServer] 段：  addr / port / user / password
      2. toml 的点号写法：             webServer.addr / webServer.port / ...
      3. 旧版 dashboard_* 字段
    返回 dict: {'addr','port','user','password'}（缺失项为 None）。
    """
    import re
    res = {'addr': None, 'port': None, 'user': None, 'password': None}

    # 优先查找 [webServer] 段
    m = re.search(r'(?ims)\[webServer\](.*?)(?=\n\[|\Z)', config_content)
    block = m.group(1) if m else ''

    for key in ('addr', 'port', 'user', 'password'):
        mm = re.search(r'(?im)^\s*' + key + r'\s*[=:]\s*["\']?([^\s"\']+)', block)
        if mm:
            if key == 'port':
                res[key] = int(mm.group(1)) if mm.group(1).isdigit() else None
            else:
                res[key] = mm.group(1)

    # 兼容旧版 dashboard 写法（统一 [common] 段内）
    if res['port'] is None:
        mm = re.search(r'(?im)^\s*dashboard_port\s*[=:]\s*["\']?(\d+)', config_content)
        if mm:
            res['port'] = int(mm.group(1))
    if res['user'] is None:
        mm = re.search(r'(?im)^\s*dashboard_user\s*[=:]\s*["\']?([^\s"\']+)', config_content)
        if mm:
            res['user'] = mm.group(1)
    if res['password'] is None:
        mm = re.search(r'(?im)^\s*dashboard_pwd\s*[=:]\s*["\']?([^\s"\']+)', config_content)
        if mm:
            res['password'] = mm.group(1)
    # 兼容 toml 点号写法：webServer.port = 7500 / webServer.password = "xxx"
    if any(v is None for v in res.values()):
        dotted = {}
        for line in config_content.splitlines():
            s = line.strip()
            if not s or s[0] in '#;[':
                continue
            dm = re.match(r'(?i)^webServer\s*\.\s*([A-Za-z_]+)\s*[=:]\s*(.*)$', s)
            if not dm:
                continue
            dotted[dm.group(1).lower()] = dm.group(2).strip().strip('"\'')
        for key, aliases in (('addr', ('addr', 'host', 'bind_addr')),
                             ('port', ('port',)),
                             ('user', ('user',)),
                             ('password', ('password', 'pwd'))):
            if res[key] is not None:
                continue
            for a in aliases:
                v = dotted.get(a)
                if v:
                    if key == 'port':
                        res[key] = int(v) if v.isdigit() else None
                    else:
                        res[key] = v
                    break

    if res['addr'] is None:
        res['addr'] = '0.0.0.0'

    return res


def extract_frp_ports(mode, cfg_path):
    """解析配置中的端口信息，用于运行状态面板展示。"""
    import re
    try:
        with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except OSError:
        return {}
    info = {}
    if mode == 'client':
        a = re.search(r'(?:server_addr|serverAddr)\s*=\s*["\']?([0-9a-zA-Z.\-]+)', text)
        p = re.search(r'(?:server_port|serverPort)\s*=\s*["\']?(\d+)', text)
        if a and p:
            info['connect'] = a.group(1) + ':' + p.group(1)
    else:
        bp = re.search(r'(?:bind_port|bindPort)\s*=\s*["\']?(\d+)', text)
        if bp:
            info['bind'] = bp.group(1)
        ws = parse_frps_webserver(text)
        if ws.get('port'):
            info['web'] = str(ws['port'])
    return info


def _parse_config_blocks(text):
    """把 ini/toml 配置拆成 [(段名, {key: value})] 列表（忽略注释与空行）。

    兼容：
      - ini 的 [name] 段头、键值用 = 分隔、snake_case 字段名
      - toml 的 [[proxies]] / [name] 段头、键值用 = 分隔、camelCase 字段名
    字段名统一转小写返回，便于后续统一取值。
    """
    import re
    blocks = []
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#') or s.startswith(';'):
            continue
        m = re.match(r'^\[+(.*?)\]+$', s)          # 段头： [name] 或 [[proxies]]
        if m:
            cur = {}
            blocks.append((m.group(1).strip(), cur))
            continue
        if cur is None:
            continue
        km = re.match(r'^([A-Za-z0-9_]+)\s*[=:]\s*(.*)$', s)   # 键值： = 或 :
        if km:
            key = km.group(1).strip().lower()
            val = km.group(2).strip().strip('"\'')
            cur[key] = val
    return blocks


def extract_port_mappings(mode, cfg_path):
    """解析配置里的「端口映射」用于前端展示。

    - 客户端(frpc)：每个代理的 内网(local_ip:local_port) → 外网(:remote_port) 映射；
      http/https 类型展示为 内网 → 自定义域名；stcp/xtcp 仅展示内网端口。
    - 服务端(frps)：bind_port(客户端接入端口) + [webServer] 管理面板端口 + allow_ports。
    返回 list[dict]，每个含 name/type/text 三个字段。
    """
    try:
        with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except OSError:
        return []

    blocks = _parse_config_blocks(text)

    if mode == 'client':
        out = []
        for name, kv in blocks:
            if name.lower() in ('common', 'webserver'):
                continue
            ptype = (kv.get('type') or 'tcp').lower()
            local_ip = kv.get('local_ip', kv.get('localip', '127.0.0.1'))
            local_port = kv.get('local_port', kv.get('localport', ''))
            remote_port = kv.get('remote_port', kv.get('remoteport', ''))
            custom = kv.get('custom_domains', kv.get('customdomains', ''))
            label = name if name.lower() != 'proxies' else (kv.get('name') or 'proxy')
            if ptype in ('tcp', 'udp'):
                text = _m(f"内网 {local_ip}:{local_port}  →  外网 :{remote_port}",
                    f"LAN {local_ip}:{local_port}  →  remote :{remote_port}")
            elif ptype in ('http', 'https'):
                text = _m(f"内网 {local_ip}:{local_port}  →  域名 {custom or '(未设置)'}",
                    f"LAN {local_ip}:{local_port}  →  domain {custom or '(not set)'}")
            elif ptype in ('stcp', 'xtcp'):
                text = _m(f"内网 {local_ip}:{local_port}  （P2P 点对点）",
                    f"LAN {local_ip}:{local_port}  (P2P direct)")
            else:
                text = _m(f"内网 {local_ip}:{local_port}",
                    f"LAN {local_ip}:{local_port}")
            out.append({'name': label, 'type': ptype, 'text': text})
        return out

    # 服务端
    out = []
    common = {}
    for name, kv in blocks:
        if name.lower() == 'common':
            common = kv
            break
    bind = common.get('bind_port', common.get('bindport', ''))
    if bind:
        out.append({'name': _m('FRP 服务端口', 'FRP bind port'), 'type': 'bind',
                    'text': _m(f"客户端接入 :{bind}", f"Clients connect :{bind}")})
    ws = parse_frps_webserver(text)
    if ws.get('port'):
        user = ws.get('user') or ''
        out.append({'name': _m('管理面板', 'Dashboard'), 'type': 'web',
                    'text': f":{ws['port']}" + (_m(f"  (账号 {user})", f"  (user {user})") if user else "")})
    allow = common.get('allow_ports', common.get('allowports', ''))
    if allow:
        out.append({'name': _m('允许端口范围', 'Allowed ports'), 'type': 'allow', 'text': allow})
    return out


def _pick(d, keys, default=0):
    """从字典中按候选键名取值，用于兼容 frps 管理API不同版本的字段命名"""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


# ---------------------------------------------------------------------- #
# 面板事件日志
#
# frpc / frps 的运行输出进 logs/frp_*.log，本程序自身的动作（启停操作、
# HTTP 链接探测）进 logs/manager.log。两者在日志页按时间线归并，
# manager.log 的行会带 [面板] 前缀，跟 [frpc] / [frps] 一眼分开。
# ---------------------------------------------------------------------- #
def log_event(message):
    """写一条面板事件日志（失败静默，不影响主流程）"""
    try:
        app.config['FRP_MANAGER'].write_event(message)
    except Exception:
        pass


def _vhost_http_port(default=80):
    """读取 frps 配置里的 vhost_http_port / vhostHTTPPort"""
    try:
        with open(resolve_config_file('server'), 'r',
                  encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except OSError:
        return default
    m = re.search(r'(?:vhost_http_port|vhostHTTPPort)\s*[=:]\s*["\']?(\d+)', text)
    return int(m.group(1)) if m else default


def collect_http_links():
    """汇总需要检测的 http 链接：
    1) 本程序 Web 面板  2) frps 管理面板/API  3) frps 客户端接入端口
    4) frpc 配置里 http/https 类型的穿透域名
    """
    links = []

    # 1) 本程序面板
    port = int(config.get('WEB_PORT') or 5000)
    links.append({'key': 'panel', 'name': _m('本管理面板', 'this panel'),
                  'url': f'http://127.0.0.1:{port}',
                  'host': '127.0.0.1', 'port': port})

    # 2) frps 管理面板 / 管理 API
    try:
        info = frps_api_info()
        if info.get('enabled') and info.get('port'):
            host = info.get('host') or '127.0.0.1'
            links.append({'key': 'frps-api',
                          'name': _m('frps 管理面板(API)', 'frps dashboard (API)'),
                          'url': f'http://{host}:{info["port"]}',
                          'host': host, 'port': int(info['port'])})
    except Exception:
        pass

    # 3) frps 客户端接入端口
    try:
        with open(resolve_config_file('server'), 'r',
                  encoding='utf-8', errors='ignore') as f:
            stext = f.read()
        bp = re.search(r'(?:bind_port|bindPort)\s*[=:]\s*["\']?(\d+)', stext)
        if bp:
            links.append({'key': 'frps-bind', 'name': _m('frps 接入端口', 'frps bind port'),
                          'url': f'tcp://127.0.0.1:{bp.group(1)}',
                          'host': '127.0.0.1', 'port': int(bp.group(1))})
    except OSError:
        pass

    # 4) frpc 的 http / https 穿透
    try:
        with open(resolve_config_file('client'), 'r',
                  encoding='utf-8', errors='ignore') as f:
            ctext = f.read()
    except OSError:
        ctext = ''
    if ctext:
        vhost = _vhost_http_port()
        for name, kv in _parse_config_blocks(ctext):
            if name.lower() in ('common', 'webserver'):
                continue
            ptype = (kv.get('type') or 'tcp').lower()
            if ptype not in ('http', 'https'):
                continue
            domains = (kv.get('custom_domains') or kv.get('customdomains') or '')
            sub = kv.get('subdomain') or ''
            host = (domains.split(',')[0].strip() if domains
                    else (sub + '.localhost' if sub else ''))
            if not host:
                continue
            p = 443 if ptype == 'https' else vhost
            links.append({'key': 'proxy-' + name, 'name': f'穿透 {name}({ptype})',
                          'url': f'http{"s" if ptype == "https" else ""}://{host}'
                                 + ('' if p == (443 if ptype == 'https' else 80) else f':{p}'),
                          'host': host, 'port': p})
    return links


def _tcp_reachable(host, port, timeout=1.5):
    """TCP 连通性探测（不依赖第三方库，最轻量）"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return False


_link_state = {}
_link_lock = threading.Lock()


def probe_http_links(force=False):
    """探测全部 http 链接；仅在「首次」或「状态发生变化」时写事件日志，避免刷屏"""
    results = []
    for lk in collect_http_links():
        ok = _tcp_reachable(lk['host'], lk['port'])
        key = lk['key']
        with _link_lock:
            prev = _link_state.get(key)
            changed = (prev is None) or (prev != ok) or force
            _link_state[key] = ok
        if changed:
            state = _m('可达', 'reachable') if ok else _m('不可达', 'unreachable')
            log_event(_m(f"HTTP 链接{state} · {lk['name']} {lk['url']}",
                         f"HTTP link {state} · {lk['name']} {lk['url']}"))
        results.append({'name': lk['name'], 'url': lk['url'],
                        'ok': ok, 'changed': bool(changed)})
    return results


_link_thread = None


def start_link_monitor(interval=30):
    """后台线程：定期检测 http 链接状态，变化时才落日志"""
    global _link_thread
    if _link_thread is not None and _link_thread.is_alive():
        return _link_thread

    def loop():
        time.sleep(3)          # 等服务与 frp 起来再开始首次探测
        while True:
            try:
                probe_http_links()
            except Exception:
                pass
            time.sleep(interval)

    _link_thread = threading.Thread(target=loop, daemon=True)
    _link_thread.start()
    return _link_thread


# ---------------------------------------------------------------------------
# 页面模板
# ---------------------------------------------------------------------------
# 首页与登录页的完整 HTML 都放在 web/ 目录下（index.html / login.html），
# CSS 与 JS 已内联在里面 —— 换界面只需要替换那一个 html 文件，不用碰 Python。
# ---------------------------------------------------------------------------

def load_page_html(name):
    """读取 web/<name>。依次在 源码目录 / PyInstaller 临时目录 下查找。

    找不到时返回 None，由调用方给出兜底提示。
    """
    roots = [os.path.dirname(os.path.abspath(__file__))]
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass and meipass not in roots:
        roots.insert(0, meipass)
    for root in roots:
        for sub in ('web', 'static', ''):
            path = os.path.join(root, sub, name) if sub else os.path.join(root, name)
            if os.path.isfile(path):
                try:
                    with io.open(path, 'r', encoding='utf-8') as f:
                        return f.read()
                except OSError:
                    continue
    return None


def render_page(name, **ctx):
    """渲染 web/<name>；模板缺失时给出明确提示而不是空白页"""
    tpl = load_page_html(name)
    if tpl is None:
        return ('<h3>页面模板缺失：web/%s</h3>'
                '<p>请把 web 目录（含 %s）放到程序目录后再刷新。</p>' % (name, name)), 500
    return render_template_string(tpl, **ctx)


def _auth_enabled():
    if load_auth_config is None:
        return False
    try:
        return bool(load_auth_config(config).get('enabled'))
    except Exception:
        return False


@app.route('/')
def index():
    import platform
    bits = platform.architecture()[0]
    system_info = f"{platform.system()} {platform.machine()} ({bits})"
    return render_page('index.html', system_info=system_info,
                       arch_info=manager.release_platform,
                       auth_enabled=_auth_enabled(),
                       app_version=app_version())


@app.route('/api/info')
def api_info():
    """平台/架构/二进制信息，便于确认 ARM 环境是否正确"""
    m = app.config['FRP_MANAGER']
    frpc = m.get_frp_binary('client')
    frps = m.get_frp_binary('server')
    return jsonify({
        'system': m.system,
        'machine': m.arch_machine,
        'arch': m.arch,
        'release_platform': m.release_platform,
        'is_arm': m.is_arm(),
        'web_port': config['WEB_PORT'],
        'frpc_bin': frpc,
        'frps_bin': frps,
        'frpc_ready': os.path.exists(frpc),
        'frps_ready': os.path.exists(frps),
        'frpc_version': m.binary_version('client'),
        'frps_version': m.binary_version('server'),
        'frpc_name': m.frpc_bin_name,
        'frps_name': m.frps_bin_name,
        'bin_dir': config['FRP_BIN_DIR'],
        'config_dir': config['FRP_CONFIG_DIR'],
        'log_dir': config['FRP_LOG_DIR'],
        'data_dir': DATA_DIR,
    })


@app.route('/api/bin/versions')
def bin_versions():
    """扫描本地已有的 frpc / frps 版本，供「版本切换」下拉使用"""
    m = app.config['FRP_MANAGER']
    try:
        data = {
            'success': True,
            'platform': m.release_platform,
            'bin_dir': config['FRP_BIN_DIR'],
            'versions_dir': m.versions_dir(),
            'client': m.list_local_versions('client'),
            'server': m.list_local_versions('server'),
        }
    except Exception as e:
        return jsonify({'success': False, 'message': _m(f'扫描失败：{e}', f'Scan failed: {e}')}), 500
    return jsonify(data)


@app.route('/api/bin/switch', methods=['POST'])
def bin_switch():
    """把 frpc / frps 切换到本地已有的某个版本"""
    m = app.config['FRP_MANAGER']
    body = request.get_json(silent=True) or {}
    mode = (body.get('mode') or '').strip()
    version = (body.get('version') or '').strip()
    if mode not in ('client', 'server'):
        return jsonify({'success': False, 'message': _m('mode 只能是 client 或 server', 'mode must be client or server')}), 400
    ok, msg = m.switch_binary(mode, version)
    return jsonify({'success': ok, 'message': msg,
                    'version': m.binary_version(mode)}), (200 if ok else 400)


@app.route('/api/frp/latest')
def frp_latest():
    """查询 frp 官方最新版本号，用于「检查更新」"""
    m = app.config['FRP_MANAGER']
    latest = m.get_latest_version(timeout=10)
    if not latest:
        return jsonify({'success': False, 'message': _m('无法获取最新版本号（网络受限）', 'Cannot fetch the latest version (network restricted)')}), 500
    return jsonify({'success': True, 'latest': latest,
                    'current_c': m.binary_version('client'),
                    'current_s': m.binary_version('server')})


@app.route('/api/status')
def status():
    manager = app.config['FRP_MANAGER']
    s = manager.get_frp_status()
    for mode in ('client', 'server'):
        cfg = resolve_config_file(mode)
        s[mode]['ports'] = extract_frp_ports(mode, cfg)
        s[mode]['port_map'] = extract_port_mappings(mode, cfg)
    # 进程自愈守护状态（前端角标 / 状态页展示）
    try:
        s['watchdog'] = manager.get_watchdog_status()
    except Exception:
        s['watchdog'] = {'enabled': True, 'client': {'desired': False, 'crashes': 0, 'running': False},
                         'server': {'desired': False, 'crashes': 0, 'running': False}, 'max_crashes': 5}
    return jsonify(s)


@app.route('/api/server/info')
def server_info():
    """查询 frps 管理API，返回代理连接信息（总数/当前连接/流量/代理列表）。

    需在服务端配置中启用 [webServer]（port/user/password）并启动 frps。
    """
    m = app.config['FRP_MANAGER']

    cfg = resolve_config_file('server')
    try:
        with open(cfg, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except OSError:
        return jsonify({'enabled': False, 'running': False,
                        'error': _m('未找到服务端配置文件', 'Server config file not found')})

    ws = parse_frps_webserver(content)
    if not ws.get('port'):
        return jsonify({'enabled': False, 'running': False,
                        'error': _m('服务端未启用管理API：请在服务端配置中添加 [webServer] 段，'
                                    '设置 port/user/password 后重启 frps',
                                    'Server management API is not enabled: add a [webServer] section '
                                    'to the server config, set port/user/password and restart frps')})

    # 注意：不在这里用进程检测结果提前返回 —— psutil 缺失、或 frps 由 systemd/Docker
    # 外部启动时进程检测会误判。先直接打管理API，能通就说明 frps 在跑。
    proc_running = False
    try:
        proc_running = bool(m.get_frp_status()['server']['running'])
    except Exception:
        pass

    # 本地查询：0.0.0.0 监听时改用 127.0.0.1 访问
    host = '127.0.0.1' if (ws.get('addr') in (None, '0.0.0.0', '')) else ws['addr']
    base = f"http://{host}:{ws['port']}"
    auth = (ws['user'], ws.get('password') or '') if ws.get('user') else None

    proxies = []
    totals = {'proxy_count': 0, 'cur_conns': 0, 'today_in': 0, 'today_out': 0}
    try:
        import requests
    except ImportError:
        return jsonify({'enabled': True, 'running': True, 'web_port': ws['port'],
                        'error': _m('缺少 requests 库，无法查询服务端API', 'The requests library is missing; cannot query the server API'),
                        'proxies': [], 'totals': totals})

    # frps 的 dashboard 是内网直连，绕开系统代理
    no_proxy = {'http': None, 'https': None}
    reached = False
    last_err = ''

    for ptype in ('tcp', 'udp', 'http', 'https', 'stcp', 'xtcp'):
        try:
            r = requests.get(f"{base}/api/proxy/{ptype}", auth=auth, timeout=5,
                             proxies=no_proxy)
            reached = True
            if r.status_code != 200:
                last_err = (f'HTTP {r.status_code}'
                            if r.status_code != 401 else '鉴权失败（user/password 不对）')
                continue
            data = r.json()
            if isinstance(data, dict):
                items = data.get('proxies') or data.get('proxy') or data.get('list') or []
            elif isinstance(data, list):
                items = data
            else:
                items = []
            for p in items:
                name = _pick(p, ['name', 'proxy_name'], '?')
                cur = int(_pick(p, ['cur_conns', 'cur_connections', 'conns'], 0) or 0)
                tin = int(_pick(p, ['today_traffic_in', 'traffic_in'], 0) or 0)
                tout = int(_pick(p, ['today_traffic_out', 'traffic_out'], 0) or 0)
                proxies.append({
                    'name': name,
                    'type': ptype,
                    'status': _pick(p, ['status', 'state'], ''),
                    'cur_conns': cur,
                    'today_in': tin,
                    'today_out': tout,
                    'client_version': _pick(p, ['client_version', 'version'], ''),
                    'last_start_time': _pick(p, ['last_start_time', 'lastStartTime'], ''),
                })
                totals['cur_conns'] += cur
                totals['today_in'] += tin
                totals['today_out'] += tout
        except Exception as e:
            # 该类型可能无数据或版本不支持，记录原因后跳过
            last_err = _friendly_conn_error(e)
            continue

    totals['proxy_count'] = len(proxies)
    if not reached:
        return jsonify({'enabled': True,
                        'running': proc_running,
                        'web_port': ws['port'],
                        'proxies': [], 'totals': totals,
                        'error': _m(f'无法连接管理API {base}：{last_err or "未知原因"}', f'Cannot reach the management API {base}: {last_err or "unknown reason"}')
                                 + (_m('（frps 进程也未检测到）', ' (no frps process detected)')
                                    if not proc_running else '')
                                 + _m('，请到上方点「检测 API 连接」看详细排查建议',
                                      '; click "Test API connection" above for troubleshooting tips')})
    return jsonify({'enabled': True, 'running': True, 'web_port': ws['port'],
                    'proxies': proxies, 'totals': totals})


def browser_host():
    """浏览器访问本管理端时用的 IP/域名（去端口）。

    用于把「面板地址」换成浏览器真正能打开的地址：本机打开管理端时它是 127.0.0.1，
    用 192.168.x.x:5000 打开时它就是 192.168.x.x。
    """
    try:
        if not has_request_context():
            return ''
        h = (request.host or '').strip()
    except Exception:
        return ''
    if not h:
        return ''
    if h.startswith('['):                       # [::1]:5000
        return h.split(']')[0] + ']'
    if h.count(':') == 1:                       # 1.2.3.4:5000 或 example.com:5000
        return h.rsplit(':', 1)[0]
    return h


def frps_api_info():
    """从服务端配置解析 frps 管理 API 的连接信息（不发起网络请求）"""
    cfg = resolve_config_file('server')
    try:
        with open(cfg, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except OSError:
        return {'enabled': False, 'error': _m('未找到服务端配置文件', 'Server config file not found'), 'file': cfg}

    ws = parse_frps_webserver(content)
    if not ws.get('port'):
        return {'enabled': False, 'file': cfg,
                'error': _m('服务端未配置 [webServer]：请在服务端配置里设置 '
                            'addr/port/user/password 后重启 frps',
                            '[webServer] is not configured on the server: set '
                            'addr/port/user/password and restart frps')}

    bind_addr = (ws.get('addr') or '0.0.0.0')
    # 0.0.0.0 / :: 是「监听所有网卡」，本机访问时换成 127.0.0.1
    # 若绑的是某个具体网卡 IP，则 127.0.0.1 会被拒绝 —— 候选地址里把它排在最前
    if bind_addr in ('0.0.0.0', '::', '::0', ''):
        host = '127.0.0.1'
        candidates = ['127.0.0.1']
    elif bind_addr.startswith('127.'):
        host = bind_addr
        candidates = [bind_addr]
    else:
        host = bind_addr
        candidates = [bind_addr, '127.0.0.1']
    base = f"http://{host}:{ws['port']}"
    user = ws.get('user') or ''

    # 浏览器用来打开面板的地址：绑 0.0.0.0 时用「访问本管理端所用的那个 IP」
    # （本管理端通常与 frps 同机，这样浏览器点击才是可达的，而不是 127.0.0.1）
    bhost = browser_host()
    if bind_addr in ('0.0.0.0', '::', '::0', ''):
        dash_host = bhost or host
        dash_from = ('browser' if bhost and bhost.strip('[]')
                     not in ('127.0.0.1', 'localhost', '::1') else 'local')
    else:
        dash_host = bind_addr
        dash_from = 'config'

    return {
        'enabled': True,
        'file': cfg,
        'bind_addr': bind_addr,
        'host': host,                       # 后端代发探测用
        'candidates': candidates,
        'dash_host': dash_host,             # 浏览器点击/外部 curl 用
        'dash_from': dash_from,             # browser / local / config
        'browser_host': bhost,
        'port': ws['port'],
        'user': user,
        'pwd': ws.get('password') or '',    # 仅后端探测使用，不随 /api/server/api 返回
        'has_password': bool(ws.get('password')),
        'dash_url': f"http://{dash_host}:{ws['port']}",
        'api_base': base,
        'local_only': bind_addr.startswith('127.'),
        'auth': (_m('Basic Auth（用户名/密码）', 'Basic Auth (user / password)') if user
                     else _m('未设置账号（无鉴权）', 'No account set (no auth)')),
        'endpoints': [
            {'method': 'GET', 'path': '/api/serverinfo',
             'desc': _m('服务端概览（版本/端口/客户端数）', 'Server overview (version / port / clients)')},
            {'method': 'GET', 'path': '/api/proxy/tcp',
             'desc': _m('TCP 代理列表与流量', 'TCP proxy list and traffic')},
            {'method': 'GET', 'path': '/api/proxy/udp',
             'desc': _m('UDP 代理列表与流量', 'UDP proxy list and traffic')},
            {'method': 'GET', 'path': '/api/proxy/http',
             'desc': _m('HTTP 代理列表与流量', 'HTTP proxy list and traffic')},
        ],
    }


def ini_webserver_issue():
    """若服务端配置是 ini 且写了 [webServer] 段，frp 不会启动管理面板。

    frp 的 ini 解析器只认旧的 dashboard_* 字段，[webServer] 段在 ini 里会被直接忽略，
    结果是 frps 正常起来但管理端口没有监听 —— 表现为「连接被拒绝」。
    返回 (配置文件路径 or None)。
    """
    cfg = resolve_config_file('server')
    if not cfg.lower().endswith('.ini'):
        return None
    try:
        with open(cfg, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except OSError:
        return None
    return cfg if re.search(r'(?im)^\s*\[webServer\]', text) else None


def _convert_ini_webserver_to_dashboard(text, ws):
    """把 ini 里的 [webServer] 段转成 frp 认的 dashboard_* 字段（放进 [common]）"""
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        s = lines[i].strip()
        if re.match(r'^\[.*\]$', s):
            if s.lower() == '[webserver]':
                i += 1
                while i < len(lines) and not re.match(r'^\[.*\]$', lines[i].strip()):
                    i += 1                      # 丢掉整个 [webServer] 段
                continue
        if re.match(r'(?i)^dashboard_(addr|port|user|pwd|password)\s*[=:]', s):
            i += 1
            continue                            # 旧字段先清掉，稍后统一写一份
        out.append(lines[i])
        i += 1

    insert = ['# ↓↓↓ dashboard_* 由 FRP Manager 自动转换：ini 格式下 [webServer] 段不被 frp 识别']
    if ws.get('port'):
        insert.append(f"dashboard_port = {ws['port']}")
    if ws.get('addr'):
        insert.append(f"dashboard_addr = {ws['addr']}")
    if ws.get('user'):
        insert.append(f"dashboard_user = {ws['user']}")
    if ws.get('password'):
        insert.append(f"dashboard_pwd = {ws['password']}")
    insert.append('# ↑↑↑ 修改后需重启 frps 生效')

    for idx, line in enumerate(out):
        if line.strip().lower() == '[common]':
            out = out[:idx + 1] + [''] + insert + out[idx + 1:]
            break
    else:
        out = ['[common]'] + insert + [''] + out
    return '\n'.join(out).rstrip() + '\n'


@app.route('/api/server/fix-config', methods=['POST'])
def server_fix_config():
    """修复「ini 里写了 [webServer] 段导致 frps 不开管理面板」的问题。

    把该段转成 frp 的 ini 解析器认的 dashboard_* 字段，并备份原配置。
    """
    cfg = ini_webserver_issue()
    if not cfg:
        return jsonify({'success': False, 'message': _m('当前配置无需修复（不是 ini，或没有 [webServer] 段）', 'Nothing to fix (not ini, or no [webServer] section)')})

    try:
        with open(cfg, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except OSError as e:
        return jsonify({'success': False, 'message': _m(f'读取配置失败: {e}', f'Failed to read config: {e}')}), 500

    ws = parse_frps_webserver(text)
    if not ws.get('port'):
        return jsonify({'success': False,
                        'message': _m('配置里的 [webServer] 段缺少 port，无法转换', 'The [webServer] section has no port; cannot convert')}), 400

    bak = cfg + '.bak-' + time.strftime('%Y%m%d%H%M%S')
    try:
        with open(bak, 'w', encoding='utf-8') as f:
            f.write(text)
        with open(cfg, 'w', encoding='utf-8') as f:
            f.write(_convert_ini_webserver_to_dashboard(text, ws))
    except OSError as e:
        return jsonify({'success': False, 'message': _m(f'写入配置失败: {e}', f'Failed to write config: {e}')}), 500

    return jsonify({'success': True,
                    'message': _m(f'已把 [webServer] 段转换为 dashboard_*（端口 {ws["port"]}），'
                                  f'原配置已备份为 {os.path.basename(bak)}。'
                                  f'请到「控制中心」重启 frps 后再点「检测 API 连接」',
                                  f'Converted the [webServer] section to dashboard_* (port {ws["port"]}); '
                                  f'the original config was backed up as {os.path.basename(bak)}. '
                                  f'Restart frps from "Control Center", then click "Test API connection"'),
                    'backup': bak, 'port': ws['port']})


def update_frps_webserver_auth(user, password=None):
    """把 frps 管理 API 的 Basic Auth 账号/密码写回服务端配置文件。

    按当前配置文件的风格自动选择写法：
      - .ini  → [common] 段内的 dashboard_user / dashboard_pwd
                （ini 解析器不认 [webServer] 段，必须写旧字段名）
      - .toml → [webServer] 段内的 user/password，或顶层的 webServer.user 点号写法

    password 为 None/空串时表示「不修改密码」。
    返回 (ok: bool, msg: str)
    """
    cfg = resolve_config_file('server')
    try:
        with open(cfg, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except OSError as e:
        return False, '读取配置失败: %s' % e

    is_ini = cfg.lower().endswith('.ini')
    lines = text.splitlines()
    changed = []

    def q(v):
        """ini 裸值；toml 字符串要加引号并转义"""
        if is_ini:
            return v
        return '"%s"' % v.replace('\\', '\\\\').replace('"', '\\"')

    def section_range(name):
        """返回 [name] 段的 (起始行, 结束行)；段不存在返回 (None, None)"""
        s_idx = e_idx = None
        for i, ln in enumerate(lines):
            t = ln.strip()
            if not re.match(r'^\[.*\]$', t):
                continue
            if t.lower() == '[%s]' % name.lower():
                s_idx, e_idx = i, len(lines)
            elif s_idx is not None:
                e_idx = i
                break
        return s_idx, e_idx

    def apply(pat, newline, start, end):
        for i in range(start, min(end, len(lines))):
            if re.match(pat, lines[i].strip()):
                if lines[i].strip() != newline:
                    lines[i] = newline
                    changed.append(newline)
                return True
        return False

    def insert_in(start, end, newline):
        """插到 [start, end) 区段的末尾（跳过尾部空行）"""
        pos = min(end, len(lines))
        while pos > start and not lines[pos - 1].strip():
            pos -= 1
        lines.insert(pos, newline)
        changed.append(newline)

    if is_ini:
        cs, ce = section_range('common')
        if cs is None:                       # 没有 [common] 就建一个
            lines.insert(0, '[common]')
            cs, ce = 0, len(lines)
        start, end = cs + 1, ce
        pairs = []
        if user:
            pairs.append((r'(?i)^dashboard_user\s*[=:]',
                          'dashboard_user = %s' % q(user)))
        if password:
            pairs.append((r'(?i)^dashboard_pwd\s*[=:]',
                          'dashboard_pwd = %s' % q(password)))
        for pat, newline in pairs:
            if not apply(pat, newline, start, end):
                insert_in(start, end, newline)
                end += 1
    else:
        ws, we = section_range('webServer')
        if ws is not None:                   # 已有 [webServer] 表 → 段内裸键
            start, end = ws + 1, we
            u_pat, p_pat = r'(?i)^(user|username)\s*=', r'(?i)^(password|pwd)\s*='
            u_new, p_new = 'user = %s' % q(user), 'password = %s' % q(password)
        else:                                # 否则用点号写法追加在文件末尾
            start, end = 0, len(lines)
            u_pat = r'(?i)^webServer\s*\.\s*(user|username)\s*='
            p_pat = r'(?i)^webServer\s*\.\s*(password|pwd)\s*='
            u_new = 'webServer.user = %s' % q(user)
            p_new = 'webServer.password = %s' % q(password)
        pairs = []
        if user:
            pairs.append((u_pat, u_new))
        if password:
            pairs.append((p_pat, p_new))
        for pat, newline in pairs:
            if not apply(pat, newline, start, end):
                insert_in(start, end, newline)
                end += 1

    if not changed:
        return True, '配置内容没有变化'

    bak = cfg + '.bak-' + time.strftime('%Y%m%d%H%M%S')
    try:
        with open(bak, 'w', encoding='utf-8') as f:
            f.write(text)
        with open(cfg, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except OSError as e:
        return False, '写入配置失败: %s' % e

    what = []
    if user:
        what.append('用户名')
    if password:
        what.append('密码')
    return True, ('已写入 %s（%s），原配置备份为 %s。'
                  '请在左侧「控制中心」重启 frps 后生效。'
                  % ('、'.join(what), os.path.basename(cfg), os.path.basename(bak)))


def _friendly_conn_error(e):
    """把 urllib3/requests 的异常链翻译成人话（跨平台匹配 Errorno / WinError）"""
    # requests 会把真正的原因层层包起来，逐层剥出 .reason
    parts, cur = [], e
    for _ in range(6):
        parts.append(str(cur))
        cur = getattr(cur, 'reason', None)
        if cur is None:
            break
    s = ' | '.join(parts)
    low = s.lower()

    if ('errno 111' in low or 'connection refused' in low
            or 'winerror 10061' in low or '积极拒绝' in s):
        return _m('目标端口没有任何进程监听（连接被拒绝）',
                  'Nothing is listening on the target port (connection refused)')
    if 'errno 113' in low or 'no route to host' in low:
        return _m('没有到该主机的路由（主机不通）',
                  'No route to the host (host unreachable)')
    if ('errno 101' in low or 'network is unreachable' in low
            or 'winerror 10051' in low or 'winerror 10065' in low):
        return _m('网络不可达', 'Network unreachable')
    if 'timed out' in low or 'timeout' in low or 'winerror 10060' in low:
        return _m('连接超时（防火墙/安全组未放行，或服务卡住未响应）',
                  'Connection timed out (firewall/security group blocking it, or the service is stuck)')
    if ('getaddrinfo' in low or 'name or service not known' in low
            or 'nodename nor servname' in low or 'winerror 11001' in low):
        return '地址无法解析（主机名写错或 DNS 异常）'
    if 'certificate' in low or 'ssl' in low:
        return 'TLS/证书校验失败'
    if 'proxy' in low and ('502' in s or '407' in s or 'tunnel' in low):
        return '被系统 HTTP 代理拦截（已自动绕开代理，若仍如此请检查代理设置）'

    # 兜底：尽量只保留最后的根因片段，别把整串堆栈丢给用户
    idx = s.rfind('Caused by')
    tail = s[idx:] if idx >= 0 else s
    return ('连接失败：' + tail[:180]).replace('\n', ' ').strip()


@app.route('/api/server/api')
def server_api():
    """返回 frps 管理 API 的连接方式（自动读取服务端配置里的 [webServer]）"""
    info = frps_api_info()
    # 面板本身已要求登录，这里把管理 API 的账号密码一并返回，
    # 便于页面直接展示/修改（密码在前端默认掩码，点眼睛才显示）
    try:
        import requests  # noqa: F401
        info['requests_ok'] = True
    except ImportError:
        info['requests_ok'] = False
    return jsonify(info)


@app.route('/api/server/auth', methods=['POST'])
def server_auth():
    """修改 frps 管理 API 的 Basic Auth 账号 / 密码（写回服务端配置文件）"""
    data = request.get_json(silent=True) or {}
    user = (data.get('user') or '').strip()
    pwd = data.get('password')
    pwd = pwd.strip() if isinstance(pwd, str) else None

    if not user and not pwd:
        return jsonify({'success': False, 'message': _m('用户名与密码都为空，未做任何修改', 'Username and password are both empty; nothing changed')}), 400

    ok, msg = update_frps_webserver_auth(user, pwd or None)
    return jsonify({'success': ok, 'message': msg, 'need_restart': ok})


@app.route('/api/server/probe')
def server_probe():
    """服务端管理 API 连通性探测。

    由后端发起请求（frps 的 dashboard 不返回 CORS 头，浏览器直连会被拦）。
    依次尝试多个候选地址；全部失败时给出可读的失败原因与排查建议。
    可用 ?host= &port= 覆盖配置里的地址与端口，便于排查远程 frps。
    """
    info = frps_api_info()
    if not info.get('enabled'):
        return jsonify({'ok': False, 'status': 0,
                        'msg': info.get('error', _m('未启用管理API', 'Management API is not enabled'))})
    try:
        import requests
    except ImportError:
        return jsonify({'ok': False, 'status': 0, 'msg': _m('缺少 requests 库，无法探测', 'The requests library is missing; cannot probe')})

    try:
        port = int(request.args.get('port') or info['port'])
    except (TypeError, ValueError):
        port = info['port']

    override_host = (request.args.get('host') or '').strip()
    hosts = [override_host] if override_host else (info.get('candidates') or [info['host']])

    # frps 进程是否在跑（用于给出更准的提示）
    frps_running = None
    try:
        frps_running = app.config['FRP_MANAGER'].get_frp_status()['server']['running']
    except Exception:
        pass

    auth = (info['user'], info.get('pwd') or '') if info['user'] else None
    # frps 的 dashboard 是内网直连，必须绕开系统代理，否则会被代理挡一道返回 502/407
    no_proxy = {'http': None, 'https': None}
    tried, last_status = [], 0

    for host in hosts:
        url = f"http://{host}:{port}/api/serverinfo"
        try:
            r = requests.get(url, auth=auth, timeout=5, proxies=no_proxy,
                             headers={'User-Agent': 'frp-manager'})
        except Exception as e:
            tried.append({'url': url, 'error': _friendly_conn_error(e)})
            continue

        last_status = r.status_code
        version = ''
        try:
            version = str(r.json().get('version') or '')
        except Exception:
            pass

        if r.status_code == 200:
            return jsonify({'ok': True, 'status': 200, 'url': url, 'version': version,
                            'msg': _m('连接成功', 'Connected') + (f' · frps {version}' if version else ''),
                            'tried': tried, 'frps_running': frps_running})
        if r.status_code == 401:
            return jsonify({'ok': False, 'status': 401, 'url': url,
                            'msg': _m('已连上但鉴权失败：[webServer] 的 user/password 不正确'
                                      '（注意改完要重启 frps）',
                                      'Connected but authentication failed: the [webServer] '
                                      'user/password is wrong (restart frps after changing it)'),
                            'tried': tried, 'frps_running': frps_running})
        tried.append({'url': url, 'error': f'HTTP {r.status_code}'})

    # 全部候选都失败：拼装有针对性的排查建议
    all_refused = all('连接被拒绝' in t['error'] for t in tried if t.get('error'))
    hints = []
    if frps_running is False:
        hints.append(_m('frps 当前未运行：到「控制中心」把操作目标选成「服务端 (frps)」后点启动',
                        'frps is not running: pick "Server (frps)" as the target in the Control Center and start it'))
    if frps_running is True and all_refused:
        hints.append(_m('frps 进程在跑，但配置里的管理端口没被监听：'
                        '多半是刚改完 [webServer] 还没重启 frps',
                        'The frps process is running but the dashboard port is not listening: '
                        'the [webServer] change probably needs an frps restart'))
    if all_refused:
        hints.append(f'在 frps 所在机器上确认监听：ss -ltnp | grep {port} '
                     f'（或 netstat -ano | findstr {port}）')
        if info['bind_addr'] not in ('0.0.0.0', '::', '::0', ''):
            hints.append(f"webServer.addr 绑的是 {info['bind_addr']}，"
                         f"它不会监听 127.0.0.1；已优先尝试该地址，若是远程机器请确认安全组放行")
    else:
        hints.append('若 frps 装在另一台机器（或 Docker 里），请在下方「覆盖地址/端口」填它的实际 IP 与映射端口')

    # 目标是远程机器时，重点怀疑防火墙 / 监听地址
    remote = [h for h in hosts if not (h.startswith('127.') or h in ('localhost', '::1'))]
    if remote:
        hints.append('目标是远程机器 ' + '/'.join(remote) + '：'
                     f'先在 frps 那台机器上确认监听地址不是 127.0.0.1（ss -ltnp | grep {port}，'
                     f'要看得到 0.0.0.0:{port} 或 {remote[0]}:{port}），'
                     f'再放行防火墙：sudo ufw allow {port}/tcp 或 '
                     f'sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload')
        hints.append('Windows 端快速判断通不通：'
                     f'Test-NetConnection {remote[0]} -Port {port} '
                     '（TcpTestSucceeded=False 且耗时约 2 秒 = 被防火墙丢包或主机不可达，'
                     '秒回 Connection refused 才是端口没进程监听）')
    hints.append('确认 [webServer] 段写的是 addr / port / user / password 四项，'
                 '保存后必须重启 frps 才生效')

    ini_bad = ini_webserver_issue()
    if ini_bad:
        hints.insert(0, '【大概率是这个】当前配置是 ini 格式，但 frp 的 ini 解析器不认 '
                        '[webServer] 段（只在 toml/yaml/json 里生效）——frps 会正常起来，'
                        '但管理面板压根不启动。点右侧「一键修复」把它转成 dashboard_* 字段，'
                        '或在配置编辑器里改用 toml 写法（见下方示例）')

    if all_refused and frps_running is False:
        msg = _m('连接失败：frps 未运行，该端口没有进程监听',
                 'Connection failed: frps is not running and nothing is listening on that port')
    elif all_refused:
        msg = _m('连接失败：目标端口没有进程监听',
                 'Connection failed: nothing is listening on the target port')
    else:
        msg = _m('连接失败：候选地址均不可用',
                 'Connection failed: none of the candidate addresses work')
    detail = '; '.join(f"{t['url']} → {t['error']}" for t in tried)
    return jsonify({'ok': False, 'status': last_status, 'msg': msg, 'detail': detail,
                    'tried': tried, 'hints': hints, 'frps_running': frps_running,
                    'ini_issue': bool(ini_webserver_issue())})


@app.route('/api/download-frp', methods=['POST'])
def download_frp_api():
    """后台下载当前架构对应的 frp 二进制（带进度查询）。

    立即返回，前端轮询 /api/download-frp/progress 获取进度。
    可选字段：version（指定版本）、mirror（国内代理镜像名）。
    """
    m = app.config['FRP_MANAGER']
    version = request.form.get('version', '').strip()
    mirror = request.form.get('mirror', '').strip()
    if not version and request.is_json:
        j = request.get_json(silent=True) or {}
        version = (j.get('version') or '').strip()
        mirror = (j.get('mirror') or '').strip()
    ok, msg = m.start_download_frp(version or None, mirror or None)
    if ok:
        return jsonify({'success': True, 'message': msg})
    return jsonify({'success': False, 'message': msg}), 409


@app.route('/api/download-frp/progress', methods=['GET'])
def download_frp_progress_api():
    """查询后台下载进度。"""
    m = app.config['FRP_MANAGER']
    return jsonify({'success': True, **m.download_progress()})

@app.route('/api/config/<config_type>', methods=['GET', 'POST'])
def config_endpoint(config_type):
    # 注意：函数名不能叫 config，否则会覆盖模块级的配置字典 config
    m = app.config['FRP_MANAGER']
    if config_type not in ('client', 'server'):
        return jsonify({'success': False, 'message': _m('配置类型仅支持 client / server', 'Config type must be client or server')}), 400

    if request.method == 'GET':
        # 不存在时自动生成一份可用的默认配置，避免编辑器空白
        path = resolve_config_file(config_type)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config_content = f.read()
        except Exception as e:
            print(f"[ERROR] 读取配置失败 {path}: {e}")
            config_content = ''
        return jsonify({'content': config_content, 'file': path})

    content = request.form.get('content', '')
    # 关键修复：保存到 resolve_config_file 返回的同一个权威路径，
    # 杜绝「保存写到 client.ini 而 frpc 读 client.toml」的分叉问题。
    # 复用 m.save_config：自动按内容选扩展名，并在开启 auto_snapshot 时先打快照。
    try:
        target_path = m.save_config(config_type, content)
        if not target_path:
            return jsonify({'success': False, 'message': _m('配置保存失败', 'Failed to save config')}), 500
        print(f"[DEBUG] 配置已保存: {target_path}")
        try:
            m.audit_event('save_config', config_type, 'success',
                          f'{len(content)} 字符', request.remote_addr)
        except Exception:
            pass
        return jsonify({'success': True, 'message': _m('配置保存成功', 'Config saved'), 'file': target_path})
    except Exception as e:
        print(f"[ERROR] 保存配置失败: {e}")
        try:
            m.audit_event('save_config', config_type, 'fail', str(e), request.remote_addr)
        except Exception:
            pass
        return jsonify({'success': False, 'message': _m(f'配置保存失败: {e}', f'Failed to save config: {e}')}), 500

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    """Web端口设置API"""
    if request.method == 'GET':
        return jsonify({'web_port': config['WEB_PORT']})

    new_port = request.form.get('port', type=int)
    if not new_port:
        return jsonify({'success': False, 'message': _m('端口无效', 'Invalid port')}), 400
    if not (1024 <= new_port <= 65535):
        return jsonify({'success': False,
                        'message': _m('端口无效，请使用1024-65535之间的端口', 'Invalid port; use a port between 1024 and 65535')}), 400
    if new_port == config['WEB_PORT']:
        return jsonify({'success': True, 'message': _m(f'端口未变化（{new_port}）', f'Port unchanged ({new_port})'),
                        'port': new_port})

    # 端口被占用时提前提示，避免重启后起不来
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(('127.0.0.1', new_port)) == 0:
            return jsonify({'success': False,
                            'message': _m(f'端口 {new_port} 已被其它程序占用', f'Port {new_port} is already in use')}), 400

    config['WEB_PORT'] = new_port
    config_dir = config['FRP_CONFIG_DIR']
    os.makedirs(config_dir, exist_ok=True)
    port_file = os.path.join(config_dir, 'web_port.ini')
    with open(port_file, 'w', encoding='utf-8') as f:
        f.write(f'port = {new_port}\n')
    return jsonify({'success': True,
                    'message': _m(f'端口已修改为 {new_port}，请重启应用生效', f'Port changed to {new_port}; restart the app to apply'),
                    'port': new_port})


@app.route('/api/settings/autostart', methods=['GET', 'POST'])
def settings_autostart():
    """开机启动 / 随程序启动 FRPC·FRPS / 下载镜像 设置。

    GET: 返回当前设置、操作系统是否支持开机启动、当前是否已注册、镜像可选列表。
    POST: 保存设置，并按 app_on_boot 在操作系统层面注册/注销开机启动。
    """
    m = app.config['FRP_MANAGER']
    if request.method == 'GET':
        s = m.load_app_settings()
        return jsonify({
            'success': True,
            'settings': s,
            'autostart_supported': m.system in ('windows', 'linux', 'darwin'),
            'autostart_active': m.get_app_autostart_status(),
            'system': m.system,
            'mirrors': MIRROR_CHOICES,
        })

    data = request.get_json(silent=True) or {}
    app_on_boot = bool(data.get('app_on_boot', False))
    frpc_on_start = bool(data.get('frpc_on_start', False))
    frps_on_start = bool(data.get('frps_on_start', False))
    mirror = (data.get('mirror') or 'auto')
    try:
        delay = int(data.get('autostart_delay', 0) or 0)
    except (ValueError, TypeError):
        delay = 0
    mode = data.get('autostart_mode') or 'user'
    if mode not in ('user', 'system'):
        mode = 'user'

    saved = m.save_app_settings({
        'app_on_boot': app_on_boot,
        'frpc_on_start': frpc_on_start,
        'frps_on_start': frps_on_start,
        'mirror': mirror,
        'autostart_delay': delay,
        'autostart_mode': mode,
    })

    msgs = []
    ok, msg = m.set_app_autostart(app_on_boot)
    if app_on_boot:
        msgs.append(('开机启动: ' + msg) if ok else ('开机启动失败: ' + msg))
    else:
        msgs.append('开机启动已关闭' if ok else ('开机启动关闭失败: ' + msg))
    if not saved:
        msgs.append('（设置已应用，但写入文件失败）')

    m.write_event('设置已更新 · 开机启动=%s 随启FRPC=%s 随启FRPS=%s 镜像=%s'
                  % (app_on_boot, frpc_on_start, frps_on_start, mirror))
    return jsonify({'success': True, 'message': '；'.join(msgs)})


# --------------------------------------------------------------------- #
# P2：流量监控 / 配置模板库 / 表单式代理编辑器 / 多语言
# --------------------------------------------------------------------- #
@app.route('/api/traffic')
def api_traffic():
    m = app.config['FRP_MANAGER']
    try:
        return jsonify({'success': True, **m.get_traffic_stats()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e),
                        'reachable': False, 'proxies': [], 'process': {}}), 500


@app.route('/api/templates')
def api_templates():
    m = app.config['FRP_MANAGER']
    return jsonify({'success': True, 'templates': m.get_config_templates()})


@app.route('/api/templates/apply', methods=['POST'])
def api_templates_apply():
    m = app.config['FRP_MANAGER']
    data = request.get_json(silent=True) or {}
    tid = data.get('template_id') or ''
    placeholders = data.get('placeholders') or {}
    ok, msg = m.apply_config_template(tid, placeholders)
    if ok:
        m.audit_event('apply_template', tid, 'success', msg, request.remote_addr)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@app.route('/api/proxies', methods=['GET', 'POST'])
def api_proxies():
    m = app.config['FRP_MANAGER']
    if request.method == 'GET':
        parsed = m.get_client_proxies()
        return jsonify({'success': True, 'format': parsed.get('format'),
                        'proxies': parsed.get('proxies', [])})
    data = request.get_json(silent=True) or {}
    proxies = data.get('proxies')
    if not isinstance(proxies, list):
        return jsonify({'success': False, 'message': _m('proxies 必须是数组', 'proxies must be an array')}), 400
    ok, msg = m.set_client_proxies(proxies)
    if ok:
        m.audit_event('edit_proxies', 'client', 'success',
                      'count=%d' % len(proxies), request.remote_addr)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 500)


@app.route('/api/i18n', methods=['GET', 'POST'])
def api_i18n():
    m = app.config['FRP_MANAGER']
    if request.method == 'GET':
        return jsonify({'success': True, 'lang': m.load_app_settings().get('lang', 'zh')})
    data = request.get_json(silent=True) or {}
    lang = data.get('lang') or 'zh'
    if lang not in ('zh', 'en'):
        lang = 'zh'
    m.save_app_settings({'lang': lang})
    # 立刻作废各模块的语言缓存：否则紧接着重新拉取的接口仍会按旧语言返回文案，
    # 表现为「切了语言但页面里还残留几句中文」。
    _MSG_LANG['at'] = 0.0
    _MSG_LANG['lang'] = lang
    for _name in ('web_auth', 'frp_manager'):
        _mod = sys.modules.get(_name)
        _cache = getattr(_mod, '_MSG_LANG', None) if _mod else None
        if isinstance(_cache, dict):
            _cache['at'] = 0.0
            _cache['lang'] = lang
    return jsonify({'success': True, 'lang': lang})


# --------------------------------------------------------------------- #
# 配置快照与回滚（P3-⑦）
# --------------------------------------------------------------------- #
@app.route('/api/settings/snapshot', methods=['GET', 'POST'])
def settings_snapshot():
    m = app.config['FRP_MANAGER']
    if request.method == 'GET':
        return jsonify({'success': True,
                        'auto_snapshot': m.load_app_settings().get('auto_snapshot', True)})
    data = request.get_json(silent=True) or {}
    ok = m.save_app_settings({'auto_snapshot': bool(data.get('auto_snapshot', True))})
    return jsonify({'success': ok, 'message': _m('快照设置已保存', 'Snapshot settings saved')})


@app.route('/api/snapshots/<config_type>', methods=['GET'])
def snapshots_list(config_type):
    m = app.config['FRP_MANAGER']
    if config_type not in ('client', 'server'):
        return jsonify({'success': False, 'message': _m('配置类型仅支持 client / server', 'Config type must be client or server')}), 400
    return jsonify({'success': True, 'snapshots': m.list_snapshots(config_type)})


@app.route('/api/snapshot/<config_type>/<snapshot_id>', methods=['GET', 'DELETE'])
def snapshot_detail(config_type, snapshot_id):
    m = app.config['FRP_MANAGER']
    if config_type not in ('client', 'server'):
        return jsonify({'success': False, 'message': _m('配置类型仅支持 client / server', 'Config type must be client or server')}), 400
    if request.method == 'DELETE':
        m.delete_snapshot(config_type, snapshot_id)
        m.audit_event('delete_snapshot', config_type, 'success', snapshot_id, request.remote_addr)
        return jsonify({'success': True, 'message': _m('已删除快照', 'Snapshot deleted')})
    content = m.read_snapshot(config_type, snapshot_id)
    if content is None:
        return jsonify({'success': False, 'message': _m('快照不存在', 'Snapshot not found')}), 404
    return jsonify({'success': True, 'content': content})


@app.route('/api/snapshot/rollback', methods=['POST'])
def snapshot_rollback():
    m = app.config['FRP_MANAGER']
    data = request.get_json(silent=True) or {}
    config_type = data.get('config_type')
    snapshot_id = data.get('snapshot_id')
    if config_type not in ('client', 'server') or not snapshot_id:
        return jsonify({'success': False, 'message': _m('参数缺失', 'Missing parameters')}), 400
    ok, msg = m.rollback_snapshot(config_type, snapshot_id)
    if ok:
        m.audit_event('rollback', config_type, 'success', snapshot_id, request.remote_addr)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 500)


# --------------------------------------------------------------------- #
# frp token / 加密向导（P3-⑧）
# --------------------------------------------------------------------- #
@app.route('/api/security/token', methods=['POST'])
def security_token():
    m = app.config['FRP_MANAGER']
    data = request.get_json(silent=True) or {}
    length = int(data.get('length', 32) or 32)
    token = m.generate_token(length)
    return jsonify({'success': True, 'token': token})


@app.route('/api/security/apply-token', methods=['POST'])
def security_apply_token():
    m = app.config['FRP_MANAGER']
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    if not token:
        return jsonify({'success': False, 'message': _m('token 不能为空', 'token cannot be empty')}), 400
    results = m.set_auth_token(token, config_types=('client', 'server'))
    m.audit_event('apply_token', 'auth', 'success', 'token 已写入两端', request.remote_addr)
    return jsonify({'success': True, 'results': results})


@app.route('/api/security/secure-proxy', methods=['POST'])
def security_secure_proxy():
    m = app.config['FRP_MANAGER']
    data = request.get_json(silent=True) or {}
    proxy = data.get('proxy')
    if not isinstance(proxy, dict):
        return jsonify({'success': False, 'message': _m('proxy 必须是对象', 'proxy must be an object')}), 400
    ok, msg = m.add_secure_proxy(proxy)
    if ok:
        m.audit_event('add_secure_proxy', 'client', 'success',
                      'name=%s type=%s' % (proxy.get('name'), proxy.get('type')),
                      request.remote_addr)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 500)


# --------------------------------------------------------------------- #
# 进程自愈守护设置
# --------------------------------------------------------------------- #
@app.route('/api/settings/monitor', methods=['GET', 'POST'])
def settings_monitor():
    m = app.config['FRP_MANAGER']
    if request.method == 'GET':
        s = m.load_app_settings()
        return jsonify({'success': True,
                        'watchdog_enabled': s.get('watchdog_enabled', True),
                        'watchdog_max_crashes': s.get('watchdog_max_crashes', 5),
                        'status': m.get_watchdog_status()})
    data = request.get_json(silent=True) or {}
    try:
        max_c = int(data.get('watchdog_max_crashes', 5) or 5)
    except (TypeError, ValueError):
        max_c = 5
    ok = m.save_app_settings({
        'watchdog_enabled': bool(data.get('watchdog_enabled', True)),
        'watchdog_max_crashes': max_c,
    })
    m.write_event('设置已更新 · 进程自愈=%s 连崩上限=%s'
                  % (data.get('watchdog_enabled'), max_c))
    m.audit_event('monitor_settings', 'watchdog', 'success',
                  'enabled=%s max_crashes=%s' % (data.get('watchdog_enabled'), max_c),
                  request.remote_addr)
    return jsonify({'success': True, 'message': _m('进程自愈设置已保存', 'Watchdog settings saved')})


# --------------------------------------------------------------------- #
# 定时重启 FRP 设置（v1.13.0）
# --------------------------------------------------------------------- #
@app.route('/api/settings/autorestart', methods=['GET', 'POST'])
def settings_autorestart():
    m = app.config['FRP_MANAGER']
    if request.method == 'GET':
        return jsonify({'success': True, 'settings': m.get_auto_restart_status()})
    data = request.get_json(silent=True) or {}
    mode = data.get('auto_restart_mode') or 'interval'
    if mode not in ('interval', 'daily'):
        mode = 'interval'
    try:
        hours = int(data.get('auto_restart_interval', 24) or 24)
    except (TypeError, ValueError):
        hours = 24
    hours = max(1, min(hours, 720))
    restart_time = str(data.get('auto_restart_time') or '04:00').strip()
    hm = m._parse_hhmm(restart_time)
    if hm is None:
        return jsonify({'success': False, 'message': _m('重启时刻格式应为 HH:MM（如 04:00）', 'Restart time must be in HH:MM format (e.g. 04:00)')}), 400
    restart_time = '%02d:%02d' % hm
    ok = m.save_app_settings({
        'auto_restart_enabled': bool(data.get('auto_restart_enabled', False)),
        'auto_restart_mode': mode,
        'auto_restart_interval': hours,
        'auto_restart_time': restart_time,
        'auto_restart_frpc': bool(data.get('auto_restart_frpc', True)),
        'auto_restart_frps': bool(data.get('auto_restart_frps', True)),
    })
    if not ok:
        return jsonify({'success': False, 'message': _m('保存设置失败（查看控制台日志）', 'Failed to save settings (see the console log)')}), 500
    m.write_event('设置已更新 · 定时重启=%s 模式=%s 间隔=%sh 时刻=%s frpc=%s frps=%s'
                  % (data.get('auto_restart_enabled'), mode, hours, restart_time,
                     data.get('auto_restart_frpc'), data.get('auto_restart_frps')))
    m.audit_event('autorestart_settings', 'monitor', 'success',
                  'enabled=%s mode=%s interval=%sh time=%s' %
                  (data.get('auto_restart_enabled'), mode, hours, restart_time),
                  request.remote_addr)
    return jsonify({'success': True, 'message': _m('定时重启设置已保存', 'Scheduled restart settings saved')})


# --------------------------------------------------------------------- #
# 操作审计日志
# --------------------------------------------------------------------- #
@app.route('/api/audit')
def audit_api():
    m = app.config['FRP_MANAGER']
    try:
        lines = int(request.args.get('lines', '200'))
    except (TypeError, ValueError):
        lines = 200
    return jsonify({'success': True, 'content': m.read_audit(lines)})


# --------------------------------------------------------------------- #
# 配置安全扫描
# --------------------------------------------------------------------- #
@app.route('/api/security/scan')
def security_scan_api():
    m = app.config['FRP_MANAGER']
    issues = m.scan_security()
    return jsonify({'success': True, 'issues': issues})


# --------------------------------------------------------------------- #
# 日志轮转 / 下载
# --------------------------------------------------------------------- #
@app.route('/api/log/rotate', methods=['POST'])
def log_rotate_api():
    m = app.config['FRP_MANAGER']
    n = m.rotate_now(manual=True)
    m.audit_event('log_rotate', 'logs', 'success', 'rotated=%d' % n, request.remote_addr)
    return jsonify({'success': True, 'message': _m(f'已轮转 {n} 个日志文件', f'Rotated {n} log files')})


@app.route('/api/log/download')
def log_download_api():
    m = app.config['FRP_MANAGER']
    name = (request.args.get('name') or '').strip()
    # 防止目录穿越
    if not name or '/' in name or '\\' in name or name.startswith('.') or '..' in name:
        return 'invalid name', 400
    path = os.path.join(config['FRP_LOG_DIR'], name)
    if not os.path.isfile(path):
        return 'not found', 404
    return send_from_directory(config['FRP_LOG_DIR'], name, as_attachment=True)


# --------------------------------------------------------------------- #
# 离线包导入（上传已下载的 frp_*.zip / .tar.gz）
# --------------------------------------------------------------------- #
@app.route('/api/import-frp', methods=['POST'])
def import_frp_api():
    m = app.config['FRP_MANAGER']
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'message': _m('未收到文件', 'No file received')}), 400
    fname = f.filename
    low = fname.lower()
    if not (low.endswith('.zip') or low.endswith('.tar.gz') or low.endswith('.tgz')):
        return jsonify({'success': False,
                        'message': _m('仅支持 .zip / .tar.gz 压缩包', 'Only .zip / .tar.gz archives are supported')}), 400
    import tempfile as _tf
    tmp = os.path.join(config['TEMP_DIR'], 'import_' + fname)
    try:
        f.save(tmp)
        ok, msg = m.install_frp_from_archive(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 500)


# --------------------------------------------------------------------- #
# 掉线告警推送设置 / 测试
# --------------------------------------------------------------------- #
@app.route('/api/settings/alert', methods=['GET', 'POST'])
def settings_alert():
    m = app.config['FRP_MANAGER']
    if request.method == 'GET':
        s = m.load_app_settings()
        keys = ['alert_enabled', 'alert_url', 'alert_type', 'alert_frp_down',
                'alert_heal_fail', 'alert_start_fail', 'alert_email_host',
                'alert_email_port', 'alert_email_user', 'alert_email_to']
        out = {k: s.get(k) for k in keys}
        out['alert_email_pass'] = '******' if s.get('alert_email_pass') else ''
        return jsonify({'success': True, 'settings': out})
    data = request.get_json(silent=True) or {}
    save = {}
    for k in ('alert_enabled', 'alert_url', 'alert_type', 'alert_frp_down',
              'alert_heal_fail', 'alert_start_fail', 'alert_email_host',
              'alert_email_port', 'alert_email_user', 'alert_email_to'):
        if k in data:
            save[k] = data[k]
    if data.get('alert_email_pass') and data['alert_email_pass'] != '******':
        save['alert_email_pass'] = data['alert_email_pass']
    m.save_app_settings(save)
    m.write_event('设置已更新 · 掉线告警=%s 类型=%s'
                  % (data.get('alert_enabled'), data.get('alert_type')))
    m.audit_event('alert_settings', str(data.get('alert_type') or ''), 'success',
                  'enabled=%s' % data.get('alert_enabled'), request.remote_addr)
    return jsonify({'success': True, 'message': _m('掉线告警设置已保存', 'Alert settings saved')})


@app.route('/api/settings/alert/test', methods=['POST'])
def alert_test():
    m = app.config['FRP_MANAGER']
    s = m.load_app_settings()
    if not s.get('alert_enabled'):
        return jsonify({'success': False, 'message': _m('告警未启用，请先开启', 'Alerts are disabled; enable them first')}), 400
    ok = m.send_alert('这是一条测试告警，FRP Manager 连接正常 ✅', title='FRP 告警测试')
    return jsonify({'success': ok,
                    'message': _m('测试告警已发送', 'Test alert sent') if ok
                    else _m('发送失败（检查地址/网络/账号）', 'Send failed (check the URL / network / credentials)')})


@app.route('/api/start', methods=['POST'])
def start():
    """启动 FRP（默认客户端模式，可用 mode=server 启动服务端）"""
    m = app.config['FRP_MANAGER']
    mode = (request.form.get('mode') or 'client').lower()
    if mode not in ('client', 'server'):
        mode = 'client'

    config_file = resolve_config_file(mode)
    print(f"[DEBUG] 启动 FRP mode={mode} config={config_file} "
          f"platform={m.release_platform}")

    # 客户端模式：提前校验 server_addr，避免 frpc 启动后才报 connection refused
    if mode == 'client':
        ok, msg = check_client_server_addr(config_file)
        if not ok:
            return jsonify({'success': False, 'message': msg,
                            'mode': mode, 'config': config_file}), 400

    success, message = m.start_frp(config_file, mode)
    label = 'frps 服务端' if mode == 'server' else 'frpc 客户端'
    if success:
        log_event(f"启动 {label} 成功 · {message}")
        m.audit_event('start_frp', mode, 'success', message, request.remote_addr)
        # 启动后立刻把 http 链接状态记一条（force：无论是否变化都记）
        try:
            time.sleep(1)
            probe_http_links(force=True)
        except Exception:
            pass
        return jsonify({'success': True,
                        'message': _m(f'{message}（配置文件：{config_file}）', f'{message} (config: {config_file})'),
                        'mode': mode, 'config': config_file})
    log_event(f"启动 {label} 失败 · {message}")
    m.audit_event('start_frp', mode, 'fail', message, request.remote_addr)
    return jsonify({'success': False,
                    'message': _m(f'{message}（配置文件：{config_file}）', f'{message} (config: {config_file})'),
                    'mode': mode, 'config': config_file}), 500


@app.route('/api/stop', methods=['POST'])
def stop():
    m = app.config['FRP_MANAGER']
    mode = (request.form.get('mode') or '').lower()
    if mode not in ('client', 'server'):
        mode = None

    if mode:
        # 仅停止选中的模式，不影响另一模式
        m.stop_frp(mode)
        m.kill_frp_mode(mode)
        st = m.get_frp_status()[mode]
        label = 'frps 服务端' if mode == 'server' else 'frpc 客户端'
        if st['running']:
            log_event(f"停止 {label} 失败 · 进程仍在运行")
            m.audit_event('stop_frp', mode, 'fail', '进程仍在运行', request.remote_addr)
            return jsonify({'success': False,
                            'message': _m(f'FRP {mode} 仍在运行，请查看日志', f'FRP {mode} is still running; check the logs')}), 500
        log_event(f"停止 {label} 完成")
        m.audit_event('stop_frp', mode, 'success', '', request.remote_addr)
        return jsonify({'success': True, 'message': _m(f'FRP {mode} 已停止', f'FRP {mode} stopped')})
    else:
        # 全部停止
        m.stop_frp()
        killed = m.kill_all_frp()
        s = m.get_frp_status()
        if s['client']['running'] or s['server']['running']:
            log_event('全部停止失败 · 仍有 FRP 进程在运行')
            m.audit_event('stop_frp', 'all', 'fail', '仍有 FRP 进程在运行', request.remote_addr)
            return jsonify({'success': False, 'message': _m('仍有 FRP 进程在运行', 'FRP processes are still running')}), 500
        log_event('全部停止完成 · frpc + frps 均已停止'
                  + (f'（清理 {killed} 个残留进程）' if killed else ''))
        m.audit_event('stop_frp', 'all', 'success', f'清理 {killed} 个残留进程', request.remote_addr)
        return jsonify({'success': True,
                        'message': _m('FRP 已全部停止', 'All FRP processes stopped')
                        + (f'（清理 {killed} 个进程）' if killed else '')})


@app.route('/api/restart', methods=['POST'])
def restart():
    m = app.config['FRP_MANAGER']
    mode = (request.form.get('mode') or 'client').lower()
    if mode not in ('client', 'server'):
        mode = 'client'

    label = 'frps 服务端' if mode == 'server' else 'frpc 客户端'
    m.stop_frp(mode)
    m.kill_frp_mode(mode)
    time.sleep(1)

    config_file = resolve_config_file(mode)
    if mode == 'client':
        ok, msg = check_client_server_addr(config_file)
        if not ok:
            log_event(f"重启 {label} 失败 · {msg}")
            return jsonify({'success': False, 'message': _m(f'FRP 重启失败: {msg}', f'Failed to restart FRP: {msg}'),
                            'mode': mode, 'config': config_file}), 400
    success, message = m.start_frp(config_file, mode)
    if success:
        log_event(f"重启 {label} 成功 · {message}")
        m.audit_event('restart_frp', mode, 'success', message, request.remote_addr)
        try:
            time.sleep(1)
            probe_http_links(force=True)
        except Exception:
            pass
        return jsonify({'success': True,
                        'message': _m(f'FRP 重启成功（配置文件：{config_file}）', f'FRP restarted (config: {config_file})')})
    log_event(f"重启 {label} 失败 · {message}")
    m.audit_event('restart_frp', mode, 'fail', message, request.remote_addr)
    return jsonify({'success': False,
                    'message': _m(f'FRP 重启失败: {message}（配置文件：{config_file}）', f'Failed to restart FRP: {message} (config: {config_file})')}), 500


@app.route('/api/links')
def api_links():
    """当前 http 链接状态（面板 / frps 管理API / 接入端口 / http 穿透域名）"""
    try:
        return jsonify({'success': True, 'links': probe_http_links()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'links': []}), 500

@app.route('/api/log')
def log():
    """运行日志。?mode=all|client|server 选择来源，?lines=N|all 控制行数。"""
    lines_arg = request.args.get('lines', '300')
    try:
        lines = 0 if lines_arg == 'all' else int(lines_arg)
    except (TypeError, ValueError):
        lines = 300

    mode = (request.args.get('mode') or 'all').lower()
    if mode not in ('all', 'client', 'server', 'webui'):
        mode = 'all'

    m = app.config['FRP_MANAGER']
    log_content = m.read_frp_log(mode, lines)

    if not log_content.strip():
        st = m.get_frp_status()
        running = [k for k in ('client', 'server') if st[k]['running']]
        tip = ('[frpc] ' if mode == 'client' else
               '[frps] ' if mode == 'server' else
               '[面板] ' if mode == 'webui' else '[frp] ')
        if running:
            log_content = (tip + _m(f"当前运行: {', '.join(running)}", f"Running: {', '.join(running)}") + "\n"
                           + tip + _m(f"平台: {m.platform_summary()}", f"Platform: {m.platform_summary()}") + "\n"
                           + tip + _m("暂无输出（日志可能刚被清空，或进程静默运行）",
                                      "No output yet (the log may have just been cleared, or the process is running quietly)"))
        else:
            log_content = (tip + _m("FRP 未运行", "FRP is not running") + "\n"
                           + tip + _m(f"平台: {m.platform_summary()}", f"Platform: {m.platform_summary()}") + "\n"
                           + tip + _m("请到「控制中心」点击启动", "Start it from the Control Center"))

    return jsonify({'content': log_content, 'mode': mode,
                    'files': [os.path.basename(str(p)) for p in m.log_files(mode)]})


@app.route('/api/log/clear', methods=['POST'])
def log_clear():
    """清空 logs/ 下的 frp 运行日志"""
    m = app.config['FRP_MANAGER']
    n = m.clear_frp_logs()
    return jsonify({'success': True, 'message': _m(f'已清空 {n} 个日志文件', f'Cleared {n} log files')})

@app.route('/api/generate-config', methods=['POST'])
def generate_config():
    data = request.get_json()
    server_addr = data.get('server_addr', '127.0.0.1')
    server_port = int(data.get('server_port', 7000))
    token = data.get('token', '')
    local_port = int(data.get('local_port', 3389))
    remote_port = int(data.get('remote_port', 3389))
    
    config = f'''[common]
server_addr = {server_addr}
server_port = {server_port}
{'token = ' + token if token else ''}
log_file = frpc.log
log_level = info
log_max_days = 3
pool_count = 10
tcp_mux = true

[RDP]
type = tcp
local_ip = 127.0.0.1
local_port = {local_port}
remote_port = {remote_port}
'''
    return jsonify({'success': True, 'config': config})

@app.route('/static/<path:path>')
def static_file(path):
    """静态资源（web/ 目录：页面模板与静态资源放在一起）"""
    if os.path.isfile(os.path.join(config['STATIC_DIR'], path)):
        return send_from_directory(config['STATIC_DIR'], path)
    return 'Not Found', 404

def main():
    print(f"[INFO] FRP Manager 启动中...")
    print(f"[INFO] 系统平台: {manager.platform_summary()}")
    start_link_monitor(interval=30)
    m = app.config['FRP_MANAGER']
    if not m.check_frp_binary('client'):
        print(f"[WARN] 未找到 frpc 二进制: {m.get_frp_binary('client')}")
    print(f"[INFO] Web UI 将在 http://0.0.0.0:{config['WEB_PORT']} 启动")
    print(f"[INFO] 按 Ctrl+C 退出程序")

    try:
        app.run(host='0.0.0.0', port=config['WEB_PORT'],
                debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        print("\n[INFO] 程序已退出")


if __name__ == '__main__':
    main()