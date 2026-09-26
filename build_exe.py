# -*- coding: utf-8 -*-
"""Windows 单文件 exe 打包脚本（PyInstaller）。

用法::

    python build_exe.py                # --onefile --windowed，产出 dist/FRP-Manager-xxx.exe
    python build_exe.py --onedir       # 调试用，产出 dist/FRP-Manager-xxx/（启动快、便于排错）

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
import shutil
import subprocess
import sys
import tempfile
import time

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# 默认单文件；--onedir 用于调试（启动快、报错 stack 完整）
MODE_ONEFILE = '--onedir' not in sys.argv
if any(a in ('-h', '--help') for a in sys.argv[1:]):
    print(__doc__)
    sys.exit(0)

# frp 二进制候选（按本机架构优先顺序排列，取第一个真实存在的一组）
FRP_BINARY_CANDIDATES = {
    'win32': ['frpc_windows_amd64.exe', 'frps_windows_amd64.exe'],
    # Linux 常见 machine 名：aarch64(ARM) / x86_64、amd64(Amd64)
    'linux': ['frpc_linux_arm64', 'frps_linux_arm64',
              'frpc_linux_amd64', 'frps_linux_amd64'],
}

ARM_MACHINES = {'arm64', 'aarch64', 'armv7l', 'armv6l'}


def pick_frp_binaries():
    """按当前平台与架构挑选要打包的 frp 二进制，返回 (client, server) 或 None。"""
    key = 'win32' if sys.platform.startswith('win') else 'linux'
    machine = (platform.machine() or '').lower()
    names = FRP_BINARY_CANDIDATES[key]
    # ARM 机器先看 arm 组，否则先看 amd64 组（linux 有两组，win32 只有一组）
    if key == 'linux':
        order = [0, 2] if machine in ARM_MACHINES else [2, 0]
    else:
        order = [0]
    for i in order:
        pair = (names[i], names[i + 1])
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
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    output_name = 'FRP-Manager-%s' % timestamp
    dist_path = os.path.join(APP_ROOT, 'dist')

    # 平台化资源暂存目录（打包完删除，不留在项目里）
    pair = pick_frp_binaries()
    cfg_stage = stage_clean_configs()
    bin_stage = stage_platform_binaries(pair) if pair else None
    if not pair:
        print('[WARN] bin/ 下找不到当前平台的 frp 二进制，产物将不含离线 frp；'
              '运行时可由面板自行下载。')

    sep = ';' if os.name == 'nt' else ':'
    def add_data(src, dst):
        return ['--add-data', '%s%s%s' % (src, sep, dst)]

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', output_name,
        '--onefile' if MODE_ONEFILE else '--onedir',
        '--windowed' if MODE_ONEFILE else '--console',
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
        # 托盘：pystray 依赖 Pillow，仅 Windows 桌面需要
        '--hidden-import', 'pystray',
        '--hidden-import', 'PIL',
        '--noconfirm',
        '--clean',
        os.path.join(APP_ROOT, 'main.py'),
    ]

    print('[INFO] 平台          : %s (%s)' % (sys.platform, platform.machine()))
    print('[INFO] frp 二进制    : %s' % (
        ', '.join(os.path.join('bin', n) for n in (pair or ())) or '未包含'))
    print('[INFO] configs 种子  : 仅 configs/README.md（干净模板）')
    print('[INFO] 打包模式      : %s' % (
        '--onefile --windowed' if MODE_ONEFILE else '--onedir --console'))
    print('[INFO] Python        : %s' % sys.executable)

    stage_dirs = [cfg_stage] + ([bin_stage] if bin_stage else [])
    try:
        result = subprocess.run(cmd, cwd=APP_ROOT)
        if result.returncode == 0:
            print('[SUCCESS] 构建完成: dist/%s%s' % (
                output_name, '.exe' if MODE_ONEFILE else '/'))
        else:
            print('[ERROR] PyInstaller 退出码 %s' % result.returncode)
        return result.returncode
    finally:
        # 产物已复制进 exe，暂存目录可安全删除
        for d in stage_dirs:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
