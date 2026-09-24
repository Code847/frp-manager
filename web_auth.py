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

import hashlib
import io
import os
import random
import secrets
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
        'file': auth_file(cfg), '_ver': 'x',
    }
    path = ensure_default(cfg)
    cp = configparser.RawConfigParser()
    try:
        cp.read(path, encoding='utf-8')
    except Exception as e:
        print('[WARN] 读取 %s 失败: %s' % (path, e))
        return out

    sec = 'auth' if cp.has_section('auth') else (cp.sections()[0] if cp.sections() else None)
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
    ) % (
        'true' if new['enabled'] else 'false',
        new['username'],
        new['password'],
        'true' if new['captcha'] else 'false',
        new['session_minutes'],
        new['remember_days'],
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

    d = request.get_json(silent=True) or request.form or {}
    user = str(d.get('user') or '').strip()
    pwd = str(d.get('pwd') or '')
    code = str(d.get('code') or '').strip().upper()
    remember = str(d.get('remember') or '') in ('1', 'true', 'True', 'on')

    time.sleep(0.35)   # 轻微限速，降低暴力破解可行性

    if not secrets.compare_digest(user, a['username']) or not password_ok(a['password'], pwd):
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
    app.register_blueprint(auth_bp)
    app.before_request(_guard)
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

