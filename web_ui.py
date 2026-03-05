import os
import sys
import subprocess
import time
import threading
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_from_directory

# 导入FRP管理器
from frp_manager import FRPManager

app = Flask(__name__)

# 配置
config = {
    'WEB_PORT': 5000,
    'FRP_BIN_DIR': os.path.join(os.path.dirname(__file__), 'bin'),
    'FRP_CONFIG_DIR': os.path.join(os.path.dirname(__file__), 'configs'),
    'FRP_LOG_DIR': os.path.join(os.path.dirname(__file__), 'logs'),
    'TEMP_DIR': os.path.join(os.path.dirname(__file__), 'temp')
}

# 创建必要的目录
for dir_path in [config['FRP_LOG_DIR'], config['TEMP_DIR']]:
    os.makedirs(dir_path, exist_ok=True)

# 初始化FRP管理器
manager = FRPManager(config)
app.config['FRP_MANAGER'] = manager
app.config['CONFIG'] = config

# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FRP Manager - 跨平台版</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 10px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 1.8em;
            margin-bottom: 5px;
        }
        
        .header p {
            font-size: 0.9em;
            opacity: 0.9;
        }
        
        .content {
            padding: 15px;
        }
        
        .section {
            margin-bottom: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .section h2 {
            margin-bottom: 15px;
            color: #333;
            font-size: 1.2em;
        }
        
        .status-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
        }
        
        .status-item {
            background: white;
            padding: 12px;
            border-radius: 5px;
            border-left: 4px solid #667eea;
            text-align: center;
        }
        
        .status-label {
            font-weight: 600;
            color: #666;
            margin-bottom: 5px;
            font-size: 0.85em;
        }
        
        .status-value {
            font-size: 1em;
            color: #333;
        }
        
        .control-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: center;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: 600;
            transition: all 0.3s;
            flex: 1;
            min-width: 100px;
            max-width: 150px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        
        .btn-success {
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            color: white;
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            color: white;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        
        .form-group {
            margin-bottom: 12px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
            color: #333;
            font-size: 0.9em;
        }
        
        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 0.9em;
        }
        
        .form-group textarea {
            min-height: 150px;
            font-family: 'Courier New', monospace;
            resize: vertical;
        }
        
        .log-content {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 10px;
            border-radius: 5px;
            min-height: 200px;
            max-height: 300px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 0.8em;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        
        .log-controls {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }
        
        .log-controls select {
            padding: 5px;
            font-size: 0.85em;
        }
        
        footer {
            text-align: center;
            padding: 15px;
            background: #f8f9fa;
            color: #666;
            font-size: 0.85em;
        }
        
        /* 竖屏手机适配 */
        @media screen and (max-width: 480px) {
            body {
                padding: 5px;
            }
            
            .header {
                padding: 15px;
            }
            
            .header h1 {
                font-size: 1.4em;
            }
            
            .header p {
                font-size: 0.8em;
            }
            
            .content {
                padding: 10px;
            }
            
            .section {
                padding: 12px;
                margin-bottom: 10px;
            }
            
            .section h2 {
                font-size: 1.1em;
                margin-bottom: 10px;
            }
            
            .status-grid {
                grid-template-columns: 1fr;
                gap: 8px;
            }
            
            .status-item {
                padding: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .status-label {
                margin-bottom: 0;
                font-size: 0.9em;
            }
            
            .status-value {
                font-size: 1em;
            }
            
            .control-group {
                flex-direction: column;
            }
            
            .btn {
                max-width: 100%;
                padding: 12px;
            }
            
            .form-group textarea {
                min-height: 120px;
            }
            
            .log-content {
                min-height: 150px;
                max-height: 200px;
                font-size: 0.75em;
            }
        }
        
        /* 横屏模式 */
        @media screen and (orientation: landscape) and (max-height: 500px) {
            body {
                padding: 10px;
            }
            
            .header {
                padding: 12px 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            
            .header h1 {
                font-size: 1.3em;
                margin-bottom: 0;
            }
            
            .header p {
                font-size: 0.75em;
                margin: 0;
            }
            
            .content {
                padding: 10px;
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 10px;
            }
            
            .section {
                padding: 12px;
                margin-bottom: 0;
            }
            
            .section h2 {
                font-size: 1em;
                margin-bottom: 10px;
                padding-bottom: 5px;
                border-bottom: 1px solid #ddd;
            }
            
            .status-grid {
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
            }
            
            .status-item {
                padding: 8px;
            }
            
            .status-label {
                font-size: 0.75em;
            }
            
            .status-value {
                font-size: 0.85em;
            }
            
            .btn {
                padding: 8px 12px;
                font-size: 0.85em;
            }
            
            .form-group {
                margin-bottom: 8px;
            }
            
            .form-group label {
                font-size: 0.8em;
            }
            
            .form-group textarea {
                min-height: 100px;
            }
            
            .log-content {
                min-height: 120px;
                max-height: 150px;
                font-size: 0.7em;
            }
            
            footer {
                padding: 8px;
                font-size: 0.75em;
            }
        }
        
        /* 平板竖屏 */
        @media screen and (min-width: 481px) and (max-width: 768px) {
            .header h1 {
                font-size: 1.6em;
            }
            
            .status-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .content {
                padding: 15px;
            }
            
            .section {
                padding: 15px;
            }
        }
        
        /* 桌面横屏 */
        @media screen and (min-width: 1024px) {
            body {
                padding: 20px;
            }
            
            .header {
                padding: 30px;
            }
            
            .header h1 {
                font-size: 2.5em;
                margin-bottom: 10px;
            }
            
            .header p {
                font-size: 1.1em;
            }
            
            .content {
                padding: 30px;
            }
            
            .section {
                padding: 20px;
                margin-bottom: 30px;
            }
            
            .section h2 {
                font-size: 1.5em;
                margin-bottom: 20px;
            }
            
            .status-grid {
                grid-template-columns: repeat(3, 1fr);
                gap: 20px;
            }
            
            .status-item {
                padding: 15px;
            }
            
            .status-label {
                font-size: 1em;
            }
            
            .status-value {
                font-size: 1.2em;
            }
            
            .btn {
                padding: 12px 24px;
                font-size: 1em;
                max-width: none;
            }
            
            .form-group {
                margin-bottom: 15px;
            }
            
            .form-group textarea {
                min-height: 200px;
            }
            
            .log-content {
                min-height: 300px;
                max-height: 500px;
                font-size: 0.9em;
            }
            
            footer {
                padding: 20px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>FRP Manager</h1>
            <p>跨平台版 - 系统信息: {{ system_info }}</p>
        </div>
        
        <div class="content">
            <div class="section">
                <h2>运行状态</h2>
                <div class="status-grid">
                    <div class="status-item">
                        <div class="status-label">FRP状态</div>
                        <div id="frpStatusText" class="status-value">检查中...</div>
                    </div>
                    <div class="status-item">
                        <div class="status-label">Web UI</div>
                        <div class="status-value">运行中</div>
                    </div>
                    <div class="status-item">
                        <div class="status-label">系统平台</div>
                        <div class="status-value">{{ system_info }}</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>控制中心</h2>
                <div class="control-group">
                    <button id="startBtn" class="btn btn-success">启动FRP</button>
                    <button id="stopBtn" class="btn btn-danger">停止FRP</button>
                </div>
            </div>
            
            <div class="section">
                <h2>配置编辑器</h2>
                <div class="form-group">
                    <label>配置类型:</label>
                    <select id="configType">
                        <option value="client">客户端配置</option>
                        <option value="server">服务端配置</option>
                    </select>
                </div>
                <div class="control-group">
                    <button id="loadBtn" class="btn btn-primary">加载配置</button>
                    <button id="saveBtn" class="btn btn-success">保存配置</button>
                    <button id="testBtn" class="btn btn-secondary">测试配置</button>
                </div>
                <div class="form-group">
                    <textarea id="configEditor" placeholder="配置内容将显示在这里..."></textarea>
                </div>
            </div>
            
            <div class="log-section">
                <h2>运行日志</h2>
                <div class="log-controls">
                    <button id="clearLogBtn" class="btn btn-secondary">清空日志</button>
                    <select id="logLines">
                        <option value="50">显示50行</option>
                        <option value="100">显示100行</option>
                        <option value="200">显示200行</option>
                        <option value="all">显示全部</option>
                    </select>
                </div>
                <pre id="logContent" class="log-content"></pre>
            </div>
        </div>
        
        <footer>
            <p>FRP Manager 跨平台版 v1.0</p>
        </footer>
    </div>
    
    <script src="{{ url_for('static', filename='script.js') }}"></script>
</body>
</html>
'''

@app.route('/')
def index():
    import platform
    system_info = f"{platform.system()} {platform.machine()}"
    return render_template_string(HTML_TEMPLATE, system_info=system_info)

@app.route('/api/status')
def status():
    manager = app.config['FRP_MANAGER']
    status_info = manager.get_frp_status()
    
    # 额外检查系统中的FRP进程
    try:
        import subprocess
        output = subprocess.check_output('tasklist | findstr frpc', shell=True, timeout=5).decode()
        if 'frpc' in output:
            status_info['running'] = True
            status_info['pid'] = int(output.split()[1])
            status_info['message'] = '通过命令行启动的FRP进程'
    except:
        pass
    
    return jsonify(status_info)

@app.route('/api/config/<config_type>', methods=['GET', 'POST'])
def config(config_type):
    manager = app.config['FRP_MANAGER']
    
    if request.method == 'GET':
        print(f"[DEBUG] Loading config type: {config_type}")
        
        # 直接加载配置文件，不通过load_config
        config_dir = app.config['CONFIG']['FRP_CONFIG_DIR']
        config_content = ''
        
        # 对于client类型，优先加载INI格式的配置
        if config_type == 'client':
            # 优先加载client_simple.ini
            simple_config = os.path.join(config_dir, 'client_simple.ini')
            if os.path.exists(simple_config):
                print(f"[DEBUG] Loading {simple_config}")
                try:
                    with open(simple_config, 'r', encoding='utf-8') as f:
                        config_content = f.read()
                except Exception as e:
                    print(f"[ERROR] Failed to load {simple_config}: {e}")
            else:
                # 尝试其他配置文件
                for filename in ['frpc.ini', 'client.ini', 'frpc.toml', 'frpc_correct.toml']:
                    config_path = os.path.join(config_dir, filename)
                    if os.path.exists(config_path):
                        print(f"[DEBUG] Loading {config_path}")
                        try:
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config_content = f.read()
                            break
                        except Exception as e:
                            print(f"[ERROR] Failed to load {config_path}: {e}")
        elif config_type == 'server':
            for filename in ['frps.toml', 'frps.ini', 'server.toml', 'server.ini']:
                config_path = os.path.join(config_dir, filename)
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_content = f.read()
                        break
                    except Exception as e:
                        print(f"[ERROR] Failed to load {config_path}: {e}")
        
        print(f"[DEBUG] Config content length: {len(config_content)}")
        return jsonify({'content': config_content})
    elif request.method == 'POST':
        content = request.form.get('content', '')
        saved_file = manager.save_config(config_type, content)
        if saved_file:
            return jsonify({'success': True, 'message': '配置保存成功', 'file': saved_file})
        else:
            return jsonify({'success': False, 'message': '配置保存失败'}), 500

@app.route('/api/start', methods=['POST'])
def start():
    try:
        binary_path = os.path.join(app.config['CONFIG']['FRP_BIN_DIR'], 'frpc_windows_amd64.exe')
        print(f"[DEBUG] FRP binary: {binary_path}")
        
        if not os.path.exists(binary_path):
            return jsonify({'success': False, 'message': 'FRP二进制文件不存在'}), 500
        
        # 使用INI格式的配置文件（兼容性好）
        config_dir = app.config['CONFIG']['FRP_CONFIG_DIR']
        config_file = os.path.join(config_dir, 'client_simple.ini')
        
        # 如果配置文件不存在，创建它
        if not os.path.exists(config_file):
            print(f"[DEBUG] 创建配置文件: {config_file}")
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write('''[common]
server_addr = 114.132.239.35
server_port = 7000
token = Rmsz@0718

[hai]
type = tcp
local_ip = 127.0.0.1
local_port = 18789
remote_port = 18789

[remote-6035]
type = tcp
local_ip = 127.0.0.1
local_port = 6035
remote_port = 6035''')
        
        print(f"[DEBUG] 使用配置文件: {config_file}")
        
        # 创建日志文件
        log_file = os.path.join(app.config['CONFIG']['FRP_LOG_DIR'], f'frpc_start_{int(time.time())}.log')
        
        # 启动FRP
        print("[DEBUG] 正在启动FRP...")
        process = subprocess.Popen(
            [binary_path, '-c', config_file],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=open(log_file, 'w'),
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE
        )
        
        # 等待一会儿看是否启动成功
        time.sleep(2)
        
        # 检查进程是否还在运行
        if process.poll() is None:
            print(f"[DEBUG] FRP启动成功 (PID: {process.pid})")
            return jsonify({'success': True, 'message': f'FRP启动成功 (PID: {process.pid})'})
        else:
            # 读取日志查看错误信息
            error_msg = "启动失败，进程已退出"
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    log_content = f.read()
                error_msg = f"启动失败: {log_content[-200:]}" if log_content else error_msg
            except:
                pass
            
            print(f"[DEBUG] FRP启动失败: {error_msg}")
            return jsonify({'success': False, 'message': error_msg}), 500
    
    except Exception as e:
        print(f"[DEBUG] Error starting FRP: {e}")
        return jsonify({'success': False, 'message': f'FRP启动失败: {str(e)}'}), 500

@app.route('/api/stop', methods=['POST'])
def stop():
    manager = app.config['FRP_MANAGER']
    success = manager.stop_frp()
    
    # 额外杀死所有FRP进程
    stop_success = False
    try:
        if manager.system == 'windows':
            # 使用cmd命令来杀死进程
            result = subprocess.run(['cmd.exe', '/c', 'taskkill /f /im frpc_windows_amd64.exe'], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"Kill frpc result: {result.returncode}")
            if result.returncode == 0:
                stop_success = True
            
            result = subprocess.run(['cmd.exe', '/c', 'taskkill /f /im frps_windows_amd64.exe'], 
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"Kill frps result: {result.returncode}")
            if result.returncode == 0:
                stop_success = True
        else:
            subprocess.run(['pkill', '-f', 'frpc.*'], check=True)
            subprocess.run(['pkill', '-f', 'frps.*'], check=True)
            stop_success = True
    except Exception as e:
        print(f"Error killing FRP processes: {e}")
    
    success = success or stop_success
    

    
    if success:
        return jsonify({'success': True, 'message': 'FRP停止成功'})
    else:
        return jsonify({'success': False, 'message': 'FRP停止失败'})

@app.route('/api/log')
def log():
    lines = int(request.args.get('lines', 100))
    log_content = ""
    
    try:
        log_dir = app.config['CONFIG']['FRP_LOG_DIR']
        
        # 查找最新的日志文件
        log_files = []
        if os.path.exists(log_dir):
            for f in os.listdir(log_dir):
                if f.endswith('.log'):
                    log_files.append(os.path.join(log_dir, f))
        
        if log_files:
            # 按修改时间排序，取最新的
            latest_log = max(log_files, key=os.path.getmtime)
            
            with open(latest_log, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                all_lines = content.strip().split('\n')
                log_content = '\n'.join(all_lines[-lines:])
        
        # 如果没有日志内容，检查FRP进程状态
        if not log_content or log_content.strip() == "":
            try:
                import psutil
                frp_running = False
                frp_pid = None
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        if proc.info['name'] and 'frpc' in proc.info['name'].lower():
                            frp_running = True
                            frp_pid = proc.info['pid']
                            break
                    except:
                        continue
                
                if frp_running:
                    log_content = f"[INFO] FRP客户端正在运行中 (PID: {frp_pid})\n"
                    log_content += f"[INFO] 连接服务器: 114.132.239.35:7000\n"
                    log_content += f"[INFO] 代理配置已加载\n"
                    log_content += f"[INFO] 点击'停止FRP'可停止服务\n"
                else:
                    log_content = "[INFO] FRP客户端未运行\n[INFO] 请点击'启动FRP'按钮开始服务"
            except Exception as e:
                log_content = f"[INFO] 等待启动...\n"
    except Exception as e:
        log_content = f"[INFO] 等待启动...\n"
    
    return jsonify({'content': log_content})

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
    return send_from_directory('static', path)

def main():
    print(f"[INFO] FRP Manager 启动中...")
    print(f"[INFO] 系统平台: {manager.system} {manager.architecture}")
    print(f"[INFO] Web UI 将在 http://localhost:{config['WEB_PORT']} 启动")
    print(f"[INFO] 按 Ctrl+C 退出程序")
    print()
    
    try:
        app.run(host='0.0.0.0', port=config['WEB_PORT'], debug=False)
    except KeyboardInterrupt:
        print("\n[INFO] 程序已退出")

if __name__ == '__main__':
    main()