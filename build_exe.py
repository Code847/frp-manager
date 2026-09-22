import subprocess
import sys
import os
import time

# 确保 temp 目录存在
os.makedirs('temp', exist_ok=True)

# 使用时间戳创建新的输出目录避免冲突
timestamp = time.strftime('%Y%m%d_%H%M%S')
output_name = f'FRP-Manager-{timestamp}'
dist_path = f'dist/{output_name}'

# 获取 Python 路径
python_dir = os.path.dirname(sys.executable)
# Python 3.14 是 python314.dll，Python 3.13 是 python313.dll
python_version = f'python{sys.version_info.major}{sys.version_info.minor}.dll'
python_dll = os.path.join(python_dir, python_version)
python3_dll = os.path.join(python_dir, 'python3.dll')

cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--name', output_name,
    '--onefile',
    '--windowed',
    '--distpath', 'dist',
    '--add-data', 'web_ui.py;.',
    '--add-data', 'web_auth.py;.',
    '--add-data', 'frp_manager.py;.',
    '--add-data', 'configs;configs',
    '--add-data', 'web;web',
    '--add-data', 'bin;bin',
]

# 添加 Python DLL 如果存在
if os.path.exists(python_dll):
    cmd.extend(['--add-binary', f'{python_dll};.'])
    print(f'[INFO] Added python313.dll')
elif os.path.exists(python3_dll):
    cmd.extend(['--add-binary', f'{python3_dll};.'])
    print(f'[INFO] Added python3.dll')

# 添加其他选项
cmd.extend([
    '--collect-all', 'flask',
    '--collect-all', 'jinja2',
    '--collect-all', 'werkzeug',
    '--collect-all', 'markupsafe',
    '--hidden-import', 'requests',
    '--hidden-import', 'psutil',
    '--hidden-import', 'web_auth',
    '--hidden-import', 'flask',
    '--hidden-import', 'markupsafe',
    '--hidden-import', 'jinja2',
    '--hidden-import', 'werkzeug',
    '--hidden-import', 'click',
    '--hidden-import', 'itsdangerous',
    '--hidden-import', 'blinker',
    '--hidden-import', 'pystray',
    '--hidden-import', 'PIL',
    '--hidden-import', 'Pillow',
    '--noconfirm',
    '--clean',
    'main.py'
])

print('Building FRP-Manager...')
print(f'[INFO] Using Python: {sys.executable}')
print(f'[INFO] Python dir: {python_dir}')
result = subprocess.run(cmd)

# temp 目录改由程序运行时在可写数据目录自动创建，无需在此预建
if result.returncode == 0:
    print(f'[SUCCESS] Build complete: dist/{output_name}.exe')

sys.exit(result.returncode)
