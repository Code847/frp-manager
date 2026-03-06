import subprocess
import sys
import os
import shutil
import time

# 确保 temp 目录存在
os.makedirs('temp', exist_ok=True)

# 使用时间戳创建新的输出目录避免冲突
timestamp = time.strftime('%Y%m%d_%H%M%S')
output_name = f'FRP-Manager-{timestamp}'
dist_path = f'dist/{output_name}'

cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--name', output_name,
    '--onedir',
    '--windowed',
    '--distpath', 'dist',
    '--add-data', 'web_ui.py;.',
    '--add-data', 'frp_manager.py;.',
    '--add-data', 'system_tray.py;.',
    '--add-data', 'configs;configs',
    '--add-data', 'static;static',
    '--add-data', 'bin;bin',
    '--add-data', 'temp;temp',
    '--hidden-import', 'requests',
    '--hidden-import', 'psutil',
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
    'main.py'
]

print('Building FRP-Manager...')
result = subprocess.run(cmd)

# 打包后创建 temp 目录
if result.returncode == 0:
    temp_dir = os.path.join(dist_path, '_internal', 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    print(f'[INFO] Created temp directory: {temp_dir}')
    print(f'[SUCCESS] Build complete: dist/{output_name}/FRP-Manager-{timestamp}.exe')

sys.exit(result.returncode)
