# -*- coding: utf-8 -*-
"""FRP Manager · Web 登录认证模块

账号 / 密码 / 图形验证码开关统一保存在 **配置文件** 里：

    <数据目录>/configs/web_auth.ini

    [auth]
    enabled         = true      # 是否开启登录保护（false = 免登录直接进面板）
    username        = admin
    password        = admin     # 明文；也支持 werkzeug 的 pbkdf2 哈希串
    captcha         = true      # ★ 图形验证码开关
    session_minutes = 0         # 会话有效期(分钟)，0 = 关掉浏览器即失效
    remember_days   = 7         # 「记住此设备」勾选后的天数

只需要在主模块里调用一次：

    from web_auth import init_auth
    init_auth(app, config)
"""

import base64
import hashlib
import hmac
import io
import ipaddress
import os
import random
import secrets
import socket
import struct
import sys
import time
import urllib.parse
from datetime import timedelta

try:
    import configparser
except ImportError:  # pragma: no cover
    configparser = None

from flask import (Blueprint, jsonify, redirect, request, session,
                   render_template_string, Response)

try:  # werkzeug 2.x 才有 generate_password_hash / check_password_hash
    from werkzeug.security import generate_password_hash, check_password_hash
    _HAS_WZ = True
except Exception:  # pragma: no cover
    _HAS_WZ = False


AUTH_FILE_NAME = 'web_auth.ini'
CAPTCHA_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXY3456789'   # 去掉 I O 0 1 2 Z 等易混字符

_CONFIG = {}
_APP = None

# 不需要登录即可访问的路径前缀
_OPEN_PREFIX = (
    '/login', '/static/', '/api/login', '/api/captcha', '/favicon.ico',
    # 界面语言偏好：登录页也要能读写，否则登录页无法跟随/切换语言
    '/api/i18n',
    # IP 白名单拦截后的说明页：必须同时免登录、免白名单，否则会跳回登录页形成死循环
    '/blocked',
)


# ---------------------------------------------------------------- 配置读写

def auth_file(cfg=None):
    cfg = cfg or _CONFIG
    d = cfg.get('FRP_CONFIG_DIR') or os.path.join(os.getcwd(), 'configs')
    return os.path.join(d, AUTH_FILE_NAME)


_DEFAULT_INI = """# FRP Manager · Web 控制台登录认证配置
#
# 修改后无需重启进程，下次访问 / 请求时自动生效（在线会话会在改密码后立刻失效）。

[auth]
# 是否启用登录保护。false = 任何人都能直接打开面板
enabled = true

# 登录账号
username = admin

# 登录密码（明文即可；也可填 werkzeug generate_password_hash 生成的 pbkdf2 串）
password = admin

# 图形验证码开关：true = 登录时必须额外填写右侧图片里的 4 位字符
captcha = true

# 会话有效期（分钟）。0 = 不勾选「记住此设备」时，关闭浏览器立刻失效
session_minutes = 0

# 勾选「记住此设备」后保留的天数
remember_days = 7

# ---- 登录加固（v1.15.0）----
# 登录失败限流：防止暴力破解
login_rate_limit = false

# 允许的最大连续失败次数（超过则锁定时长）
max_fails = 5

# 失败计数滑动窗口（分钟）：窗口外的失败不计
fail_window_min = 15

# 触发上限后锁定时长（分钟）
lock_min = 30

# 登录 IP 白名单：逗号 / 换行分隔，支持 CIDR（如 192.168.1.0/24）。为空=不限制
ip_allowlist =

# TOTP 二次验证（可选）：开启后登录需额外输入 6 位动态码
totp_enabled = false

# TOTP 密钥（base32），由「生成并启用」产生
totp_secret =
"""


def ensure_default(cfg=None):
    """配置文件不存在时生成一份带默认账号的模板。"""
    cfg = cfg or _CONFIG
    path = auth_file(cfg)
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_DEFAULT_INI)
    except Exception as e:
        print('[WARN] 生成 %s 失败: %s' % (path, e))
    return path


def load_auth_config(cfg=None):
    """返回认证配置 dict（带 _ver 指纹，用于密码变更后踢掉老会话）。"""
    cfg = cfg or _CONFIG
    out = {
        'enabled': False, 'username': 'admin', 'password': 'admin',
        'captcha': True, 'session_minutes': 0, 'remember_days': 7,
        'login_rate_limit': False, 'max_fails': 5, 'fail_window_min': 15,
        'lock_min': 30, 'ip_allowlist': '', 'totp_enabled': False,
        'totp_secret': '',
        'file': auth_file(cfg), '_ver': 'x',
    }
    path = ensure_default(cfg)
    cp = configparser.RawConfigParser()
    try:
        cp.read(path, encoding='utf-8')
    except Exception as e:
        print('[WARN] 读取 %s 失败: %s' % (path, e))
        return out

    # 登录加固的键与账号密码同在 [auth] 段。早期文档曾写成 [security]，
    # 若这里不认，照旧文档手改配置的人会「改了半天没生效」却查不出原因。
    sec = None
    for _name in ('auth', 'security'):
        if cp.has_section(_name):
            sec = _name
            break
    if not sec:
        sec = cp.sections()[0] if cp.sections() else None
    if not sec:
        return out

    def get(k, d):
        try:
            return cp.get(sec, k)
        except Exception:
            return d

    def as_bool(v, d=False):
        s = str(v).strip().lower()
        if s in ('1', 'true', 'yes', 'on', '是', '开'):
            return True
        if s in ('0', 'false', 'no', 'off', '否', '关'):
            return False
        return d

    def as_int(v, d=0):
        try:
            return int(str(v).strip())
        except Exception:
            return d

    out['enabled'] = as_bool(get('enabled', 'true'), True)
    out['username'] = get('username', 'admin').strip() or 'admin'
    out['password'] = get('password', 'admin')
    out['captcha'] = as_bool(get('captcha', 'true'), True)
    out['session_minutes'] = max(0, as_int(get('session_minutes', 0), 0))
    out['remember_days'] = max(1, as_int(get('remember_days', 7), 7))
    out['login_rate_limit'] = as_bool(get('login_rate_limit', 'false'), False)
    out['max_fails'] = max(1, as_int(get('max_fails', 5), 5))
    out['fail_window_min'] = max(1, as_int(get('fail_window_min', 15), 15))
    out['lock_min'] = max(1, as_int(get('lock_min', 30), 30))
    raw_al = get('ip_allowlist', '') or ''
    out['ip_allowlist'] = ','.join([x.strip() for x in raw_al.replace('\n', ',').split(',') if x.strip()])
    out['totp_enabled'] = as_bool(get('totp_enabled', 'false'), False)
    out['totp_secret'] = (get('totp_secret', '') or '').strip()
    out['_ver'] = hashlib.md5(
        (out['username'] + '\x00' + out['password']).encode('utf-8')
    ).hexdigest()[:12]
    return out


def save_auth_config(patch, cfg=None):
    """局部更新认证配置；返回 (新配置dict, 提示语)。"""
    cfg = cfg or _CONFIG
    path = ensure_default(cfg)
    cur = load_auth_config(cfg)

    new = {
        'enabled': cur['enabled'],
        'username': cur['username'],
        'password': cur['password'],
        'captcha': cur['captcha'],
        'session_minutes': cur['session_minutes'],
        'remember_days': cur['remember_days'],
        'login_rate_limit': cur['login_rate_limit'],
        'max_fails': cur['max_fails'],
        'fail_window_min': cur['fail_window_min'],
        'lock_min': cur['lock_min'],
        'ip_allowlist': cur['ip_allowlist'],
        'totp_enabled': cur['totp_enabled'],
        'totp_secret': cur['totp_secret'],
    }

    for k, v in patch.items():
        if k == 'enabled':
            new['enabled'] = bool(v)
        elif k == 'captcha':
            new['captcha'] = bool(v)
        elif k == 'username':
            s = str(v).strip()
            if not s:
                return cur, '账号不能为空'
            new['username'] = s
        elif k == 'password':
            s = str(v)
            if s == '':
                pass                       # 留空 = 不修改
            elif len(s) < 3:
                return cur, '密码长度至少 3 位'
            else:
                new['password'] = s
        elif k == 'session_minutes':
            new['session_minutes'] = max(0, int(v or 0))
        elif k == 'remember_days':
            new['remember_days'] = max(1, int(v or 7))
        elif k == 'login_rate_limit':
            new['login_rate_limit'] = bool(v)
        elif k == 'max_fails':
            new['max_fails'] = max(1, int(v or 5))
        elif k == 'fail_window_min':
            new['fail_window_min'] = max(1, int(v or 15))
        elif k == 'lock_min':
            new['lock_min'] = max(1, int(v or 30))
        elif k == 'ip_allowlist':
            s = str(v or '')
            new['ip_allowlist'] = ','.join([x.strip() for x in s.replace('\n', ',').split(',') if x.strip()])
        elif k == 'totp_enabled':
            new['totp_enabled'] = bool(v)
        elif k == 'totp_secret':
            new['totp_secret'] = str(v or '').strip()

    txt = (
        "# FRP Manager · Web 控制台登录认证配置\n"
        "#\n"
        "# 修改后无需重启进程；改动密码会让所有已登录会话立即失效。\n"
        "\n"
        "[auth]\n"
        "# 是否启用登录保护。false = 任何人都能直接打开面板\n"
        "enabled = %s\n"
        "\n"
        "# 登录账号\n"
        "username = %s\n"
        "\n"
        "# 登录密码（明文即可；也可填 werkzeug generate_password_hash 生成的 pbkdf2 串）\n"
        "password = %s\n"
        "\n"
        "# 图形验证码开关：true = 登录时必须额外填写右侧图片里的 4 位字符\n"
        "captcha = %s\n"
        "\n"
        "# 会话有效期（分钟）。0 = 不勾选「记住此设备」时，关闭浏览器立刻失效\n"
        "session_minutes = %d\n"
        "\n"
        "# 勾选「记住此设备」后保留的天数\n"
        "remember_days = %d\n"
        "\n"
        "# ---- 登录加固（v1.15.0）----\n"
        "# 登录失败限流（防暴力破解）\n"
        "login_rate_limit = %s\n"
        "# 允许的最大连续失败次数\n"
        "max_fails = %d\n"
        "# 失败计数滑动窗口（分钟）\n"
        "fail_window_min = %d\n"
        "# 触发上限后锁定时长（分钟）\n"
        "lock_min = %d\n"
        "# 登录 IP 白名单：逗号/换行分隔，支持 CIDR；为空=不限制\n"
        "ip_allowlist = %s\n"
        "# TOTP 二次验证（可选）\n"
        "totp_enabled = %s\n"
        "# TOTP 密钥（base32，由「生成并启用」产生）\n"
        "totp_secret = %s\n"
    ) % (
        'true' if new['enabled'] else 'false',
        new['username'],
        new['password'],
        'true' if new['captcha'] else 'false',
        new['session_minutes'],
        new['remember_days'],
        'true' if new['login_rate_limit'] else 'false',
        new['max_fails'],
        new['fail_window_min'],
        new['lock_min'],
        new['ip_allowlist'],
        'true' if new['totp_enabled'] else 'false',
        new['totp_secret'],
    )

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(txt)
    except Exception as e:
        return cur, '保存失败: %s' % e

    return load_auth_config(cfg), '已保存到 ' + path


def password_ok(stored, plain):
    """兼容明文与 pbkdf2 哈希两种写法。"""
    stored = stored or ''
    plain = plain or ''
    if _HAS_WZ and (stored.startswith('pbkdf2:') or stored.startswith('scrypt:')):
        try:
            return check_password_hash(stored, plain)
        except Exception:
            return False
    return secrets.compare_digest(stored, plain)


def hash_password(plain):
    if _HAS_WZ:
        try:
            return generate_password_hash(plain or '')
        except Exception:
            pass
    return plain


# ---------------------------------------------------------------- 登录加固（v1.15.0）

# 限流状态（进程内，仅用于单实例面板；重启后自动清零，属可接受取舍）
_FAIL = {}      # ip -> [失败时间戳, ...]
_LOCK = {}      # ip -> 锁定到期时间戳


def _client_ip():
    """取真实客户端 IP（兼容反代 X-Forwarded-For）。"""
    xff = (request.headers.get('X-Forwarded-For') or '').split(',')
    if xff and xff[0].strip():
        return xff[0].strip()
    return request.remote_addr or '0.0.0.0'


def _is_private_ip(ip):
    """判断是否私有/回环地址（界面上决定要不要给「填网段」按钮）。"""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


def _cidr24(ip):
    """把 IP 收成 /24 网段，便于「整个局域网都能登录」。"""
    try:
        return str(ipaddress.ip_network('%s/24' % ip, strict=False))
    except ValueError:
        return ip


def local_ips():
    """列出本机可用于登录面板的 IPv4 地址（排除回环），已去重并按「主网卡优先」排序。

    开启 IP 白名单后，用户最容易卡在「不知道该填哪个地址」上 —— 这个列表
    直接喂给界面，就能一键填入，而不是让用户猜。

    顺序约定：能出公网的出口 IP 排最后（它是本机地址，但通常不是别人访问
    本机的地址），私有网段（192.168/10/172.16-31）与主机名解析出的 IP 在前。
    """
    out, seen = [], set()

    def _add(ip, kind):
        if not ip or ip in seen:
            return
        seen.add(ip)
        out.append({'ip': ip, 'kind': kind})

    # 1) 出口 IP：靠路由表拿，不真正发包；多网卡 / VPN 下最贴近「别人访问你」的地址
    for probe in (('8.8.8.8', 80), ('223.5.5.5', 80), ('10.255.255.255', 1)):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.4)
            s.connect(probe)
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.'):
                _add(ip, 'outbound')
                break
        except Exception:
            continue
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    # 2) 主机名解析出的所有地址：覆盖多网卡、Docker 网桥等「有地址但无默认路由」的情况
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            _add(info[4][0], 'host')
    except Exception:
        pass

    # 排序：私有网段在前，出口 IP（ NAT 后的本机地址，别人一般访问不到）在后
    def _rank(item):
        return (0 if _is_private_ip(item['ip']) else 1, item['ip'])

    out.sort(key=_rank)
    return out


_LAN_IP_CACHE = {'at': 0.0, 'value': []}


def local_ips_cached(ttl=10):
    """带短缓存的版本：网卡地址不会秒变，避免每次请求都做一次探测。"""
    now = time.time()
    if now - _LAN_IP_CACHE['at'] < ttl and _LAN_IP_CACHE['value']:
        return _LAN_IP_CACHE['value']
    val = local_ips()
    # 探测彻底失败时（无网卡 / 沙箱）也要给一点兜底，界面才有东西可显示
    if not val:
        val = [{'ip': '127.0.0.1', 'kind': 'loopback'}]
    _LAN_IP_CACHE.update({'at': now, 'value': val})
    return val


def _ip_allowed(client_ip, allowlist):
    """allowlist 为空=不限制；否则需命中某个 IP 或 CIDR。"""
    if not allowlist:
        return True
    ip = client_ip.strip()
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for item in allowlist.replace('\n', ',').split(','):
        item = item.strip()
        if not item:
            continue
        if item == ip:
            return True
        try:
            if addr in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            if item == ip:
                return True
    return False


def _fail_count(ip, window_min):
    now = time.time()
    lst = _FAIL.get(ip)
    if not lst:
        return 0
    cutoff = now - window_min * 60
    lst[:] = [t for t in lst if t >= cutoff]
    return len(lst)


def _register_fail(ip):
    _FAIL.setdefault(ip, []).append(time.time())


# ----------------------------------------------------------------------- #
# TOTP 验证码单独限流
# ----------------------------------------------------------------------- #
# 6 位动态码只有 10^6 种，不限流的话「二次验证」的厚度几乎等于没有。
_TOTP_FAIL = {}
_TOTP_MAX_FAILS = 8
_TOTP_WINDOW = 15 * 60          # 15 分钟内的错误次数才计入


def _totp_fail_count(ip):
    cutoff = time.time() - _TOTP_WINDOW
    lst = _TOTP_FAIL.get(ip) or []
    lst = [t for t in lst if t >= cutoff]
    _TOTP_FAIL[ip] = lst
    return len(lst)


def _totp_fail(ip):
    _TOTP_FAIL.setdefault(ip, []).append(time.time())


def _totp_reset(ip):
    _TOTP_FAIL.pop(ip, None)


def _is_locked(ip):
    exp = _LOCK.get(ip)
    if exp and time.time() < exp:
        return exp
    if exp:
        _LOCK.pop(ip, None)
    return 0


def _lock(ip, minutes):
    _LOCK[ip] = time.time() + minutes * 60


def _clear_fails(ip):
    _FAIL.pop(ip, None)
    _LOCK.pop(ip, None)


def totp_generate_secret():
    """生成 RFC4226 base32 密钥（16 字节 = 32 字符，无需补齐）。"""
    return base64.b32encode(os.urandom(16)).decode('ascii').rstrip('=')


def totp_uri(secret, label='FRP Manager', issuer='FRP Manager'):
    s = (secret or '').strip().rstrip('=')
    return 'otpauth://totp/%s?secret=%s&issuer=%s&period=30&digits=6' % (
        urllib.parse.quote(label), s, urllib.parse.quote(issuer))


def _totp_at(secret, when=None, digits=6, period=30):
    key = (secret or '').strip().upper()
    if not key:
        return None
    pad = (8 - len(key) % 8) % 8
    try:
        k = base64.b32decode(key + '=' * pad)
    except Exception:
        return None
    t = int(time.time() if when is None else when)
    counter = t // period
    msg = struct.pack('>Q', counter)
    h = hmac.new(k, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0f
    code = (struct.unpack('>I', h[o:o + 4])[0] & 0x7fffffff) % (10 ** digits)
    return str(code).zfill(digits)


def totp_verify(secret, code, window=1):
    code = str(code or '').strip()
    if not code.isdigit() or len(code) != 6:
        return False
    for w in range(-window, window + 1):
        if _totp_at(secret, when=time.time() + w * 30) == code:
            return True
    return False


# ---------------------------------------------------------------- 验证码

def gen_code(n=4):
    return ''.join(random.choice(CAPTCHA_CHARS) for _ in range(n))


def captcha_svg(code, w=112, h=40):
    """纯 Python 生成 SVG 图形验证码（无 Pillow 依赖）。

    风格对齐参考项目：深色底 + 随机旋转字符 + 干扰线 + 噪点。
    """
    rnd = random.Random()
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
        % (w, h, w, h),
        '<rect width="100%" height="100%" fill="#080f1e"/>',
    ]
    # 背景斜纹
    for i in range(0, w, 7):
        parts.append('<line x1="%d" y1="0" x2="%d" y2="%d" stroke="rgba(130,185,240,.05)" '
                     'stroke-width="1"/>' % (i, i - 12, h))
    # 干扰线
    for _ in range(3):
        parts.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" '
            'stroke-linecap="round"/>'
            % (rnd.uniform(0, w * .3), rnd.uniform(2, h - 2),
               rnd.uniform(w * .7, w), rnd.uniform(2, h - 2),
               rnd.choice(['#22d3ee', '#6366f1', '#94a3b8']), rnd.uniform(.7, 1.6)))
    # 噪点
    for _ in range(26):
        parts.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" opacity="%.2f"/>'
                     % (rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(.4, 1.5),
                        rnd.choice(['#22d3ee', '#a5b4fc', '#e8f0fb', '#94a3b8']),
                        rnd.uniform(.15, .6)))
    # 字符（随机旋转 + 双色交替）
    n = len(code)
    step = (w - 16) / max(1, n)
    for i, ch in enumerate(code):
        parts.append(
            '<text x="%.1f" y="%.1f" font-family="Consolas,Monaco,monospace" font-size="%d" '
            'font-weight="bold" fill="%s" text-anchor="middle" '
            'transform="rotate(%.1f %.1f %.1f)">%s</text>'
            % (10 + step * (i + .5), h * .5 + 8, rnd.choice([21, 22, 23]),
               ('#22d3ee' if i % 2 else '#e8f0fb'),
               rnd.uniform(-16, 16), 10 + step * (i + .5), h * .5,
               _xml_escape(ch)))
    parts.append('</svg>')
    return ''.join(parts)


def _xml_escape(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


# ---------------------------------------------------------------- 路由

auth_bp = Blueprint('webauth', __name__)


@auth_bp.route('/login')
def login_page():
    a = load_auth_config(_CONFIG)
    if not a['enabled']:
        return redirect('/')
    if _logged_in(a):
        nxt = request.args.get('next') or '/'
        return redirect(nxt)
    try:
        session.pop('cap', None)
        session.pop('cap_exp', None)
    except Exception:
        pass
    nxt = request.args.get('next') or '/'
    if not str(nxt).startswith('/') or str(nxt).startswith('//'):
        nxt = '/'
    return render_page(
        'login.html',
        app_version=_app_version(),
        captcha_on=a['captcha'],
        totp_on=a['totp_enabled'],
        next=nxt,
        remember_days=a['remember_days'],
        toast='',
        default_pwd=(password_ok(a['password'], 'admin') and a['username'] == 'admin'),
        ver_mismatch=(request.args.get('err') == '1'),
    )


@auth_bp.route('/logout')
def logout_page():
    try:
        session.clear()
    except Exception:
        pass
    a = load_auth_config(_CONFIG)
    if not a['enabled']:
        return redirect('/')
    return render_page(
        'login.html', app_version=_app_version(),
        captcha_on=a['captcha'], next='/',
        remember_days=a['remember_days'],
        toast='已安全退出',
        default_pwd=(password_ok(a['password'], 'admin') and a['username'] == 'admin'),
        ver_mismatch=False)


@auth_bp.route('/api/captcha')
def api_captcha():
    a = load_auth_config(_CONFIG)
    code = gen_code(4)
    session['cap'] = code
    session['cap_exp'] = int(time.time()) + 180
    svg = captcha_svg(code)
    if a.get('captcha') is False:
        # 关闭验证码时不产出图片
        return Response('', mimetype='image/svg+xml')
    return Response(
        svg,
        mimetype='image/svg+xml',
        headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
                 'Pragma': 'no-cache'},
    )


@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    a = load_auth_config(_CONFIG)
    if not a['enabled']:
        return jsonify({'success': True, 'message': _m('未启用登录保护', 'Login protection is disabled'), 'redirect': '/'})

    ip = _client_ip()

    # 1) IP 白名单：不在名单直接拒绝（名单为空=不限制）
    if not _ip_allowed(ip, a['ip_allowlist']):
        return jsonify({'success': False,
                        'message': _m('当前 IP 不在允许名单内，已拒绝登录',
                                      'Your IP is not in the allowlist; login refused'),
                        'field': 'pwd'}), 403

    # 2) 失败限流：已锁定时直接拒绝，并提示剩余时长
    lock_exp = _is_locked(ip)
    if lock_exp:
        remain = int((lock_exp - time.time()) / 60) + 1
        return jsonify({'success': False,
                        'message': _m('尝试次数过多，已临时锁定，请 %d 分钟后再试' % remain,
                                      'Too many attempts; locked for %d minutes' % remain),
                        'field': 'pwd'}), 429

    d = request.get_json(silent=True) or request.form or {}
    user = str(d.get('user') or '').strip()
    pwd = str(d.get('pwd') or '')
    code = str(d.get('code') or '').strip().upper()
    totp_code = str(d.get('totp') or '').strip()
    remember = str(d.get('remember') or '') in ('1', 'true', 'True', 'on')

    time.sleep(0.35)   # 轻微限速，降低暴力破解可行性

    if not secrets.compare_digest(user, a['username']) or not password_ok(a['password'], pwd):
        _register_fail(ip)
        if a['login_rate_limit'] and _fail_count(ip, a['fail_window_min']) >= a['max_fails']:
            _lock(ip, a['lock_min'])
        session.pop('cap', None)
        return jsonify({'success': False, 'message': _m('账号或密码不正确', 'Incorrect username or password'),
                        'field': 'pwd', 'refresh_captcha': True})

    if a['captcha']:
        cap = str(session.get('cap') or '').upper()
        exp = int(session.get('cap_exp') or 0)
        if not cap or time.time() > exp or not secrets.compare_digest(code, cap):
            session.pop('cap', None)
            return jsonify({'success': False, 'message': _m('验证码不正确或已过期', 'Captcha is incorrect or expired'),
                            'field': 'code', 'refresh_captcha': True})

    # 3) TOTP 二次验证（可选）
    if a['totp_enabled']:
        if not totp_verify(a['totp_secret'], totp_code):
            _register_fail(ip)
            if a['login_rate_limit'] and _fail_count(ip, a['fail_window_min']) >= a['max_fails']:
                _lock(ip, a['lock_min'])
            session.pop('cap', None)
            return jsonify({'success': False,
                            'message': _m('动态验证码不正确', 'Invalid TOTP code'),
                            'field': 'totp', 'refresh_captcha': True})

    # 通过：清掉失败计数
    _clear_fails(ip)
    session.pop('cap', None)
    session.pop('cap_exp', None)
    session['auth_user'] = a['username']
    session['auth_ver'] = a['_ver']
    session['auth_at'] = int(time.time())
    if remember:
        session.permanent = True
        session['auth_exp'] = int(time.time()) + a['remember_days'] * 86400
    elif a['session_minutes'] > 0:
        session.permanent = True
        session['auth_exp'] = int(time.time()) + a['session_minutes'] * 60
    else:
        session.permanent = False
        session['auth_exp'] = 0

    # 登录成功即清掉该 IP 的验证码错误计数，否则一次手滑会影响后续登录
    _totp_reset(_client_ip())
    nxt = str(d.get('next') or '/')
    if not nxt.startswith('/') or nxt.startswith('//'):
        nxt = '/'
    return jsonify({'success': True, 'message': _m('验证通过', 'Verified'), 'redirect': nxt})


@auth_bp.route('/api/auth/config', methods=['GET', 'POST'])
def api_auth_config():
    if request.method == 'GET':
        a = load_auth_config(_CONFIG)
        return jsonify({
            'success': True,
            'enabled': a['enabled'],
            'username': a['username'],
            'captcha': a['captcha'],
            'session_minutes': a['session_minutes'],
            'remember_days': a['remember_days'],
            'file': a['file'],
            'logged_user': session.get('auth_user', ''),
        })

    d = request.get_json(silent=True) or request.form or {}
    patch = {}
    if 'enabled' in d:
        patch['enabled'] = str(d.get('enabled')) in ('1', 'true', 'True', 'on', 'yes')
    if 'captcha' in d:
        patch['captcha'] = str(d.get('captcha')) in ('1', 'true', 'True', 'on', 'yes')
    if 'username' in d:
        patch['username'] = d.get('username')
    if d.get('password'):
        patch['password'] = d.get('password')
    if 'session_minutes' in d:
        patch['session_minutes'] = d.get('session_minutes')
    if 'remember_days' in d:
        patch['remember_days'] = d.get('remember_days')

    new, msg = save_auth_config(patch, _CONFIG)
    # 密码/账号改了就把当前会话顶掉，强制重新登录
    if session.get('auth_user') and str(session.get('auth_ver')) != new['_ver']:
        try:
            session.clear()
        except Exception:
            pass
    else:
        session['auth_ver'] = new['_ver']
    return jsonify({'success': True, 'message': msg,
                    'enabled': new['enabled'], 'captcha': new['captcha'],
                    'username': new['username']})


def _api_security_get():
    a = load_auth_config(_CONFIG)
    out = {
        'success': True,
        'login_rate_limit': a['login_rate_limit'],
        'max_fails': a['max_fails'],
        'fail_window_min': a['fail_window_min'],
        'lock_min': a['lock_min'],
        'ip_allowlist': a['ip_allowlist'],
        'totp_enabled': a['totp_enabled'],
        'totp_has_secret': bool(a['totp_secret']),
        'file': a['file'],
        # 白名单开启后，最常卡住用户的是「不知道该填哪个 IP」。
        # 把当前来源 IP 与本机候选地址一并返回，界面就能一键填入。
        'client_ip': _client_ip(),
        'client_allowed': _ip_allowed(_client_ip(), a['ip_allowlist']),
        'lan_ips': [x['ip'] for x in local_ips_cached()],
    }
    return jsonify(out)


def _api_security_post():
    d = request.get_json(silent=True) or request.form or {}
    patch = {}
    for k in ('login_rate_limit', 'max_fails', 'fail_window_min', 'lock_min'):
        if k in d:
            patch[k] = d.get(k)
    if 'ip_allowlist' in d:
        patch['ip_allowlist'] = d.get('ip_allowlist')
    # 注意：不要在这里接受 totp_enabled=False —— 关闭 TOTP 必须走 /api/auth/totp/disable
    new, msg = save_auth_config(patch, _CONFIG)
    return jsonify({'success': True, 'message': _m('登录加固设置已保存', 'Login hardening saved'),
                    'login_rate_limit': new['login_rate_limit'],
                    'max_fails': new['max_fails'],
                    'fail_window_min': new['fail_window_min'],
                    'lock_min': new['lock_min'],
                    'ip_allowlist': new['ip_allowlist']})


def _api_totp_setup():
    """生成新密钥与 otpauth URI（尚未启用），供前端展示。"""
    secret = totp_generate_secret()
    return jsonify({'success': True, 'secret': secret,
                    'uri': totp_uri(secret),
                    'label': 'FRP Manager'})


def _api_totp_enable():
    """启用 TOTP。支持两种用法：

    1) 带 secret（新密钥）+ code —— 生成并启用，必须用新密钥的码确认；
    2) 不带 secret 或 secret 等于已保存的密钥 —— 「重新启用」，
       用已保存密钥的当前验证码即可，不必重新扫码。

    第 2 种是「停用后立刻重开」的通道：密钥一直留着，用户只输一次 6 位码。
    """
    d = request.get_json(silent=True) or request.form or {}
    secret = str(d.get('secret') or '').strip()
    code = str(d.get('code') or '').strip()
    if not code:
        return jsonify({'success': False, 'message': _m('缺少验证码', 'Missing verification code')}), 400

    cur = load_auth_config(_CONFIG)
    # 6 位码空间有限，错误重试必须限流，否则等于把二次验证的厚度降到 10^6
    ip = _client_ip()
    if _totp_fail_count(ip) >= _TOTP_MAX_FAILS:
        return jsonify({'success': False, 'message': _m(
            '连续输入错误次数过多，请稍后再试', 'Too many wrong codes; try again later')}), 429
    if secret and secret != cur.get('totp_secret'):
        if not totp_verify(secret, code):          # 新密钥必须用新码确认
            _totp_fail(ip)
            return jsonify({'success': False, 'message': _m(
                '验证码不正确，请确认时间同步后重试', 'Invalid code; check time sync')}), 400
    else:
        secret = (cur.get('totp_secret') or '').strip()
        if not secret:
            return jsonify({'success': False, 'message': _m(
                '还没有密钥，请先点「生成并启用」', 'No secret yet; generate and enable first')}), 400
        if not totp_verify(secret, code):
            _totp_fail(ip)
            return jsonify({'success': False, 'message': _m(
                '验证码不正确，请确认时间同步后重试', 'Invalid code; check time sync')}), 400

    save_auth_config({'totp_secret': secret, 'totp_enabled': True}, _CONFIG)
    _totp_reset(ip)
    return jsonify({'success': True, 'message': _m('TOTP 二次验证已启用', 'TOTP 2FA enabled')})


def _api_totp_disable():
    """关闭 TOTP（仍保留密钥，便于下次快速重新启用）。"""
    new, msg = save_auth_config({'totp_enabled': False}, _CONFIG)
    return jsonify({'success': True, 'message': _m('TOTP 二次验证已关闭', 'TOTP 2FA disabled')})


# ---------------------------------------------------------------- 被拦截页
# 白名单开启后误配（把自己关在门外）是几乎必发生的事，此时必须告诉用户
# 「怎么办」，而不是甩一个没有下文的 403。
_BLOCKED_PAGE = u"""<!doctype html>
<html lang="%(lang)s"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(t1)s</title>
<style>
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
background:#f6f8fb;color:#1f2733;margin:0;padding:40px 16px;line-height:1.7}
main{max-width:680px;margin:0 auto;background:#fff;border:1px solid #e3e8ef;
border-radius:14px;padding:28px 30px}
h1{font-size:1.2rem;margin:0 0 10px}
code{background:#f1f4f9;padding:2px 7px;border-radius:6px;font-size:.95em;color:#0a6cff}
.warn{border-left:4px solid #f5a623;background:#fff8ec;padding:12px 18px;
border-radius:8px;margin:18px 0}
.warn ol{padding-left:20px;margin:8px 0 0}
footer{margin-top:22px;font-size:.85em;color:#707a87}
</style></head><body><main>
<h1>%(t1)s</h1>
<p>%(t2)s <code>%(ip)s</code> %(t3)s</p>
<div class="warn">
<p style="margin:0">%(t4)s</p>
<ol>
<li>%(t5)s <code id="localUrl">http://127.0.0.1:PORT</code></li>
<li>%(t6)s</li>
</ol>
</div>
<footer>%(t7)s</footer>
</main>
<script>
// 面板端口可能被保留端口规则顺延过（如 5000 → 5002），
// 所以「本机地址」要按用户当前实际访问的地址重写，不能写死一个端口。
(function(){
  var el = document.getElementById('localUrl');
  if (!el) return;
  try {
    var u = new URL(window.location.href);
    u.protocol = 'http:'; u.hostname = '127.0.0.1';
    el.textContent = u.toString();
  } catch (e) {}
})();
</script>
</body></html>"""

_BLOCKED_TEXT = {
    'zh': {
        't1': u'当前 IP 不在允许名单内',
        't2': u'你正在使用的地址',
        't3': u'不在「登录 IP 白名单」里，因此面板与接口都已拒绝访问。',
        't4': u'要恢复访问，任选一种方式：',
        't5': u'用本机地址重新打开面板（同一台电脑上的浏览器）：',
        't6': u'登录后在「安全中心 → 登录加固」里把自己这个地址（建议填整个网段，如 192.168.1.0/24）加进白名单，再点保存。',
        't7': u'也可以直接编辑配置文件 configs/web_auth.ini 中的 ip_allowlist 项。',
    },
    'en': {
        't1': u'Your IP is not on the allowlist',
        't2': u'The address you are using is',
        't3': u'which is not in the "Login IP allowlist", so the panel and API have been blocked.',
        't4': u'To restore access, pick either of these:',
        't5': u'Reopen the panel from this same computer via localhost:',
        't6': u'Then go to Security Center → Login hardening, add your address (a whole subnet such as 192.168.1.0/24 is recommended) and save.',
        't7': u'You can also edit ip_allowlist in configs/web_auth.ini directly.',
    },
}


def _page_blocked():
    lang = _msg_lang()
    t = _BLOCKED_TEXT.get(lang) or _BLOCKED_TEXT['zh']
    if lang == 'en':
        t = _BLOCKED_TEXT['en']
    html = _BLOCKED_PAGE % dict(t, lang=lang, ip=_client_ip())
    return Response(html, mimetype='text/html; charset=utf-8')


# 注册新端点（在 init_auth 内统一挂到 blueprint 上）
SECURITY_ROUTES = [
    ('/blocked', ['GET'], {'GET': _page_blocked}),
    ('/api/auth/security', ['GET', 'POST'], {'GET': _api_security_get, 'POST': _api_security_post}),
    ('/api/auth/totp/setup', ['GET'], {'GET': _api_totp_setup}),
    ('/api/auth/totp/enable', ['POST'], {'POST': _api_totp_enable}),
    ('/api/auth/totp/disable', ['POST'], {'POST': _api_totp_disable}),
]


# ---------------------------------------------------------------- 守卫

def _logged_in(a=None):
    a = a or load_auth_config(_CONFIG)
    if not a['enabled']:
        return True
    if not session.get('auth_user'):
        return False
    if str(session.get('auth_ver')) != a['_ver']:
        return False
    exp = int(session.get('auth_exp') or 0)
    if exp and time.time() > exp:
        return False
    return True


# ---------------------------------------------------------------- 消息多语言
_MSG_LANG = {'at': 0.0, 'lang': 'zh'}


def _msg_lang():
    now = time.time()
    if now - _MSG_LANG['at'] < 2.0:
        return _MSG_LANG['lang']
    lang = 'zh'
    try:
        import configparser
        d = _CONFIG.get('FRP_CONFIG_DIR') or os.path.join(os.getcwd(), 'configs')
        f = os.path.join(d, 'app_settings.ini')
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


def _need_json():
    return (request.path.startswith('/api/')
            or 'application/json' in (request.headers.get('Accept') or ''))


def _guard():
    a = load_auth_config(_CONFIG)
    if not a['enabled']:
        # 未启用登录保护时，放行一切；同时保留 /login 可用（会自动跳回首页）
        return None
    p = request.path
    for pre in _OPEN_PREFIX:
        if p.startswith(pre):
            return None
    if p.startswith('/api/auth/config') and session.get('auth_user'):
        return None
    if _logged_in(a):
        return None
    if p == '/api/auth/config':
        return jsonify({'success': False, 'message': _m('未登录', 'Not signed in'), 'need_login': True}), 401
    if _need_json():
        return jsonify({'success': False, 'message': _m('登录已失效，请重新登录', 'Session expired, please sign in again'),
                        'need_login': True}), 401
    nxt = p
    if request.query_string:
        try:
            nxt += '?' + request.query_string.decode('utf-8', 'ignore')
        except Exception:
            pass
    return redirect('/login?next=' + urllib.parse.quote(nxt, safe='/?=&'))


# ---------------------------------------------------------------- 初始化

def init_auth(app, config):
    """把认证能力挂到 Flask app 上。"""
    global _CONFIG, _APP
    _CONFIG = config
    _APP = app

    # 会话密钥：持久化保存，避免每次重启都把已登录状态顶掉
    sec_file = os.path.join(config.get('FRP_CONFIG_DIR', 'configs'), '.web_secret')
    key = ''
    try:
        if os.path.exists(sec_file):
            key = open(sec_file, 'r', encoding='utf-8').read().strip()
    except Exception:
        key = ''
    if len(key) < 16:
        key = secrets.token_hex(32)
        try:
            os.makedirs(os.path.dirname(sec_file), exist_ok=True)
            with open(sec_file, 'w', encoding='utf-8') as f:
                f.write(key)
        except Exception as e:
            print('[WARN] 会话密钥持久化失败: %s' % e)
    app.secret_key = key
    app.permanent_session_lifetime = timedelta(days=30)

    app.config['WEB_AUTH'] = {
        'load': lambda: load_auth_config(_CONFIG),
        'save': lambda patch: save_auth_config(patch, _CONFIG),
        'logged_in': _logged_in,
    }
    app.jinja_env.globals.setdefault('auth_enabled', lambda: load_auth_config(_CONFIG)['enabled'])

    ensure_default(_CONFIG)
    # 登录加固 / TOTP 端点（v1.15.0）：必须在 register_blueprint 之前加规则，
    # 一旦蓝图已注册，Flask 就不再允许追加 —— 那会让整段初始化抛异常、登录端点全部失效。
    # 注意：每个「规则×方法」都要有独立 endpoint。Flask 不允许同一个 endpoint
    # 挂两个不同函数，否则整段 register_blueprint 会抛 AssertionError，
    # 导致登录保护与所有端点一起失效。
    for rule, methods, view_map in SECURITY_ROUTES:
        for m in methods:
            ep = 'sec' + rule.replace('/', '_').strip('_') + '_' + m.lower()
            auth_bp.add_url_rule(rule, endpoint=ep, view_func=view_map[m], methods=[m])
    app.register_blueprint(auth_bp)

    # IP 白名单：在守卫最前置生效（白名单为空=不限制）。
    # 例外：登录页 / 验证码 / 登录接口 / 静态资源 永远可访问，避免把自己关在门外；
    # 另放开 /api/auth/security 与 TOTP 端点，便于误配后自行修正。
    _OPEN_PREFIX_extra = (
        # 登录加固 / TOTP：便于误配后自行修正
        '/api/auth/security', '/api/auth/totp/setup',
        '/api/auth/totp/enable', '/api/auth/totp/disable',
        # PWA 资源：必须免登录可访问，否则「添加到主屏幕」拿不到 manifest / sw.js
        '/sw.js', '/manifest.webmanifest', '/icon.svg',
    )

    def _guard_hardened():
        a = load_auth_config(_CONFIG)
        if not a['enabled']:
            return None
        p = request.path
        for pre in _OPEN_PREFIX + _OPEN_PREFIX_extra:
            if p.startswith(pre):
                return None
        # IP 白名单前置拦截（仅当启用了登录保护且配置非空）
        if a['ip_allowlist'] and not _ip_allowed(_client_ip(), a['ip_allowlist']):
            if _need_json() or p.startswith('/api/'):
                return jsonify({'success': False,
                               'message': _m('当前 IP 不在允许名单内', 'Your IP is not in the allowlist'),
                               'need_login': True}), 403
            # 以前这里写的是「403 + redirect」——两个语义互相打架的响应，
            # 浏览器拿到 403 不会跳转，用户只看到一片空白。改为给一个说明页。
            return redirect('/blocked', code=302)
        return _guard()

    app.before_request(_guard_hardened)
    return app


def auth_enabled(config=None):
    return load_auth_config(config or _CONFIG)['enabled']
# ---------------------------------------------------------------------------
# 页面模板
# ---------------------------------------------------------------------------
# 首页与登录页的完整 HTML 都放在 web/ 目录下（index.html / login.html），
# CSS 与 JS 已内联在里面 —— 换界面只需要替换那一个 html 文件，不用碰 Python。
# ---------------------------------------------------------------------------

def _app_version():
    """当前程序版本（登录页右上角显示用）。

    web_ui 会 import web_auth，所以这里运行时再取，避免循环导入。
    """
    try:
        import web_ui
        return web_ui.app_version()
    except Exception:
        return ''


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

