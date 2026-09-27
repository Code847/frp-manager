# -*- coding: utf-8 -*-
"""单文件打包脚本（PyInstaller）。

用法::

    python build_exe.py                  # --onefile --windowed，产出 dist/FRP-Manager-xxx
    python build_exe.py --onedir         # 调试用（启动快、报错 stack 完整）
    python build_exe.py --list-targets   # 列出可打包的目标平台
    python build_exe.py --target linux-arm64   # 显式指定目标（须与当前机器一致）

关于 Linux / macOS 目标（重要）
------------------------------
PyInstaller **不支持交叉编译** —— 它把当前 Python 解释器打进产物，
所以在 Windows 上永远打不出 Linux 的 ELF，反之亦然；同理 amd64 机器打不出 arm64 包。

因此 `--target` 不是"想打哪个就打哪个"，而是**显式声明要带哪一组 frp 二进制**，
并在与当前机器不匹配时**直接报错退出**，绝不静默产出跑不起来的东西。
要出 Linux 包，请在 Linux 主机上运行本脚本，或交给 CI 矩阵（见 .github/workflows）。

为什么需要一份「干净的打包资源」
----------------------------------
`seed_data()` 在**首次运行时**会把打包资源里的 configs / bin 复制成用户数据目录的种子，
规则是「目标不存在才复制」。这意味着一旦把**构建机自己的**配置打进发布包，会同时犯两个错：

1. 泄露构建凭据：configs 里有 `.web_secret`（会话签名密钥）、`web_auth.ini`（口令哈希），
   装到别人机器上等于把自己的登录凭据和签名密钥一起发出去。
2. 污染用户环境：app_settings.ini / client.toml / server.ini 里是构建机的语言、端口、
   frp server 地址与 token，用户首次启动就会被播种成这些值。

所以本脚本只往包里放两类干净资源：
- configs 目录下仅 `README.md` 一个说明模板（其余由程序首次运行自动生成）；
- bin 目录下仅**当前平台**需要的那两个 frp 二进制，跨平台文件一律不打包。

（这套约束与 build_arm.sh 保持一致——那边早就这么做了，Windows 侧漏了。）

另外：PyInstaller 的 onefile 模式已内嵌 Python 运行时，早期版本里手动
`--add-binary python3xx.dll` 的做法会让解释器在解压目录里多出一份 DLL，属于多余且易冲突。
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# 默认单文件；--onedir 用于调试（启动快、报错 stack 完整）
MODE_ONEFILE = '--onedir' not in sys.argv

# platform.machine() -> frp 官方发布包里的架构后缀
ARCH_MAP = {
    'x86_64': 'amd64', 'amd64': 'amd64', 'x64': 'amd64', 'em64t': 'amd64',
    'aarch64': 'arm64', 'arm64': 'arm64', 'armv8l': 'arm64', 'armv8': 'arm64',
    'armv7l': 'arm', 'armv7': 'arm', 'armv6l': 'arm', 'armv6': 'arm', 'arm': 'arm',
    'i386': '386', 'i486': '386', 'i586': '386', 'i686': '386', 'x86': '386',
}

# 可打包的目标平台。键 = --target 可填的值，值 = 展示名。
BUILD_TARGETS = (
    ('windows_amd64', 'Windows x86_64'),
    ('windows_arm64', 'Windows ARM64'),
    ('windows_386', 'Windows 32-bit'),
    ('linux_amd64', 'Linux x86_64'),
    ('linux_arm64', 'Linux ARM64'),
    ('linux_arm', 'Linux ARMv7'),
    ('linux_386', 'Linux 32-bit'),
    ('darwin_amd64', 'macOS x86_64'),
    ('darwin_arm64', 'macOS Apple Silicon'),
)


def _arg_value(flag):
    """取 --flag value 形式的值；写成 --flag=value 也能识别。"""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == flag:
            return argv[i + 1] if i + 1 < len(argv) else None
        if a.startswith(flag + '='):
            return a.split('=', 1)[1]
    return None


# 连字符与下划线都接受：CLI 习惯打 --target linux-arm64，
# 而内部（以及 frp 官方包名）用的是 linux_arm64。
TARGET_ARG = (_arg_value('--target') or 'auto').strip().lower().replace('-', '_')

if any(a in ('-h', '--help') for a in sys.argv[1:]):
    print(__doc__)
    sys.exit(0)

if '--list-targets' in sys.argv[1:]:
    print('可选 --target（须与当前机器一致，PyInstaller 不支持交叉编译）：')
    for k, label in BUILD_TARGETS:
        print('  %-16s %s' % (k, label))
    print('  %-16s %s' % ('auto', '按当前机器自动判断（默认）'))
    sys.exit(0)


def _current_target():
    """当前机器对应的目标串，如 windows_amd64 / linux_arm64。"""
    s = sys.platform
    if s.startswith('win'):
        sysname = 'windows'
    elif s.startswith('linux'):
        sysname = 'linux'
    elif s.startswith('darwin'):
        sysname = 'darwin'
    else:
        sysname = re.sub(r'[^a-z0-9]', '', s.lower())
    m = (platform.machine() or '').lower()
    arch = ARCH_MAP.get(m, m or 'unknown')
    return '%s_%s' % (sysname, arch)


def _binary_names(target):
    """目标串 -> (frpc 文件名, frps 文件名)，按 frp 官方命名规则推导。"""
    sysname, _, arch = target.partition('_')
    ext = '.exe' if sysname == 'windows' else ''
    return ('frpc_%s_%s%s' % (sysname, arch, ext),
            'frps_%s_%s%s' % (sysname, arch, ext))


def resolve_target():
    """确定目标平台并在不匹配时**报错退出** —— 绝不静默产出跑不起来的产物。"""
    cur = _current_target()
    if TARGET_ARG in ('auto', '', None):
        return cur
    known = dict(BUILD_TARGETS)
    if TARGET_ARG not in known:
        print('[ERROR] 未知目标平台: %s' % TARGET_ARG)
        print('        可选: auto, ' + ', '.join(k for k, _ in BUILD_TARGETS))
        print('        （python build_exe.py --list-targets 可列出全部）')
        sys.exit(2)
    if TARGET_ARG != cur:
        print('[ERROR] 目标平台 %s 与当前机器 %s 不一致。' % (TARGET_ARG, cur))
        print('        PyInstaller 不支持交叉编译：它把当前 Python 解释器打进产物，')
        print('        所以在 %s 上打不出 %s 的可执行文件。' % (cur, TARGET_ARG))
        print('        请在该目标平台的机器上执行本脚本，或交给 CI 矩阵构建。')
        sys.exit(2)
    return TARGET_ARG


def pick_frp_binaries(target):
    """按目标平台挑选要打包的 frp 二进制，返回 (client, server) 或 None。"""
    pair = _binary_names(target)
    if all(os.path.isfile(os.path.join(APP_ROOT, 'bin', n)) for n in pair):
        return pair
    return None


def stage_clean_configs():
    """只复制 configs/README.md 到临时目录作为干净种子。"""
    d = tempfile.mkdtemp(prefix='frp-pkg-configs-')
    src = os.path.join(APP_ROOT, 'configs', 'README.md')
    if os.path.isfile(src):
        shutil.copy2(src, os.path.join(d, 'README.md'))
    else:
        # README.md 被误删时不要让打包静默产出空 configs：补一份说明兜底
        with open(os.path.join(d, 'README.md'), 'w', encoding='utf-8') as f:
            f.write('# configs\n\n运行时配置目录，首次启动自动生成。\n')
    return d


def stage_platform_binaries(pair):
    """只复制当前平台那两个 frp 二进制，返回目录**本身**即 bin 的内容。

    注意：不要把文件再塞进一层 `d/bin/` 再 `add-data d/bin;bin`——那样解压后会
    变成 `_MEIPASS/bin/bin/frpc_xxx.exe`，多套一层。程序找不到 frp 二进制时不会
    报错，而是静默去 GitHub 重新下载（首次启动慢到像卡死），极难察觉。
    """
    d = tempfile.mkdtemp(prefix='frp-pkg-bin-')
    for name in pair:
        src = os.path.join(APP_ROOT, 'bin', name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(d, name))
    return d if os.listdir(d) else None


def main():
    target = resolve_target()
    is_windows = target.startswith('windows')
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    # 产物名带平台：同一台机器上不会互相覆盖，分发时也不会拿错
    output_name = 'FRP-Manager-%s-%s' % (target, timestamp)
    dist_path = os.path.join(APP_ROOT, 'dist')

    # 平台化资源暂存目录（打包完删除，不留在项目里）
    pair = pick_frp_binaries(target)
    cfg_stage = stage_clean_configs()
    bin_stage = stage_platform_binaries(pair) if pair else None
    if not pair:
        print('[WARN] bin/ 下找不到当前平台的 frp 二进制，产物将不含离线 frp；'
              '运行时可由面板自行下载。')

    sep = ';' if os.name == 'nt' else ':'
    def add_data(src, dst):
        return ['--add-data', '%s%s%s' % (src, sep, dst)]

    # --windowed 只给 Windows：Linux 服务器大多是 headless（systemd / ssh），
    # 隐藏控制台后一旦起不来就没有任何输出可查，等于自断排错路径。
    windowed = MODE_ONEFILE and is_windows

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', output_name,
        '--onefile' if MODE_ONEFILE else '--onedir',
        '--windowed' if windowed else '--console',
        '--distpath', dist_path,
        '--workpath', os.path.join(APP_ROOT, 'build'),
        '--specpath', os.path.join(APP_ROOT, 'build'),
        # 模块本体：main.py 依赖 web_ui / web_auth / frp_manager，需随包分发
    ] + add_data(os.path.join(APP_ROOT, 'web_ui.py'), '.') \
      + add_data(os.path.join(APP_ROOT, 'web_auth.py'), '.') \
      + add_data(os.path.join(APP_ROOT, 'frp_manager.py'), '.') \
      + add_data(cfg_stage, 'configs') \
      + add_data(os.path.join(APP_ROOT, 'web'), 'web')

    if bin_stage:
        cmd += add_data(bin_stage, 'bin')

    cmd += [
        '--collect-all', 'flask',
        '--collect-all', 'jinja2',
        '--collect-all', 'werkzeug',
        '--hidden-import', 'requests',
        '--hidden-import', 'psutil',
        '--hidden-import', 'web_auth',
        '--hidden-import', 'click',
        '--hidden-import', 'itsdangerous',
        '--hidden-import', 'blinker',
        # gzip：响应压缩在 after_request 里 import，PyInstaller 静态分析可能漏掉
        '--hidden-import', 'gzip',
        # 托盘：pystray 依赖 Pillow，仅桌面平台需要（headless Linux 装了也没用）
        '--hidden-import', 'pystray',
        '--hidden-import', 'PIL',
        '--noconfirm',
        '--clean',
        os.path.join(APP_ROOT, 'main.py'),
    ]

    print('[INFO] 目标平台      : %s（当前机器 %s / %s）'
          % (target, sys.platform, platform.machine()))
    print('[INFO] frp 二进制    : %s' % (
        ', '.join(os.path.join('bin', n) for n in (pair or ())) or '未包含'))
    print('[INFO] configs 种子  : 仅 configs/README.md（干净模板）')
    print('[INFO] 打包模式      : %s' % (
        ('--onefile' if MODE_ONEFILE else '--onedir')
        + (' --windowed' if windowed else ' --console')))
    print('[INFO] Python        : %s' % sys.executable)

    ext = '.exe' if (is_windows and MODE_ONEFILE) else ('/' if not MODE_ONEFILE else '')
    stage_dirs = [cfg_stage] + ([bin_stage] if bin_stage else [])
    try:
        result = subprocess.run(cmd, cwd=APP_ROOT)
        if result.returncode == 0:
            print('[SUCCESS] 构建完成: dist/%s%s' % (output_name, ext))
        else:
            print('[ERROR] PyInstaller 退出码 %s' % result.returncode)
        return result.returncode
    finally:
        # 产物已复制进 exe，暂存目录可安全删除
        for d in stage_dirs:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
