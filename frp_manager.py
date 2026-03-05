import os
import sys
import platform
import subprocess
import threading
import time
import requests
import json
from pathlib import Path

class FRPManager:
    def __init__(self, config):
        self.config = config
        self.system = platform.system().lower()
        self.arch = platform.machine().lower()
        self.frp_process = None
        self.frp_version = None
        self.frp_binary_path = None
        
        # 根据系统架构设置二进制文件名
        if self.system == 'windows':
            self.frpc_bin_name = 'frpc_windows_amd64.exe'
            self.frps_bin_name = 'frps_windows_amd64.exe'
        elif self.system == 'linux':
            self.frpc_bin_name = 'frpc_linux_amd64'
            self.frps_bin_name = 'frps_linux_amd64'
        else:
            # 其他系统使用Linux版本
            self.frpc_bin_name = 'frpc_linux_amd64'
            self.frps_bin_name = 'frps_linux_amd64'
    
    def get_latest_version(self):
        """获取最新FRP版本"""
        try:
            # 尝试获取最新版本
            response = requests.get('https://api.github.com/repos/fatedier/frp/releases/latest', timeout=15, verify=False)
            if response.status_code == 200:
                data = response.json()
                self.frp_version = data.get('tag_name', '').lstrip('v')
                return self.frp_version
        except Exception as e:
            print(f"[ERROR] 获取最新版本失败: {e}")
        
        # 如果获取失败，使用已知的最新稳定版本
        self.frp_version = "0.52.3"
        return self.frp_version
    
    def download_frp(self):
        """下载FRP二进制文件"""
        try:
            # 获取最新版本
            if not self.frp_version:
                self.get_latest_version()
                
            # 下载ZIP包而不是单个exe文件
            zip_filename = f"frp_{self.frp_version}_windows_amd64.zip"
            zip_url = f"https://github.com/fatedier/frp/releases/download/v{self.frp_version}/{zip_filename}"
            zip_path = os.path.join(self.config['TEMP_DIR'], zip_filename)
            
            print(f"[INFO] 正在下载 FRP 压缩包: {zip_url}")
            response = requests.get(zip_url, stream=True, verify=False, timeout=60)
            
            if response.status_code == 200:
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                print(f"[INFO] 下载完成: {zip_filename}")
                
                # 解压ZIP包
                import zipfile
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(self.config['TEMP_DIR'])
                
                # 找到解压后的文件
                extract_dir = os.path.join(self.config['TEMP_DIR'], f"frp_{self.frp_version}_windows_amd64")
                
                if os.path.exists(extract_dir):
                    # 复制frpc.exe和frps.exe到bin目录
                    source_frpc = os.path.join(extract_dir, "frpc.exe")
                    source_frps = os.path.join(extract_dir, "frps.exe")
                    
                    if os.path.exists(source_frpc):
                        import shutil
                        shutil.copy(source_frpc, os.path.join(self.config['FRP_BIN_DIR'], 'frpc_windows_amd64.exe'))
                    
                    if os.path.exists(source_frps):
                        shutil.copy(source_frps, os.path.join(self.config['FRP_BIN_DIR'], 'frps_windows_amd64.exe'))
                    
                    # 清理临时文件
                    shutil.rmtree(extract_dir)
                    os.remove(zip_path)
                    
                    return True
                else:
                    print(f"[ERROR] 解压后的目录不存在: {extract_dir}")
                    return False
                
            else:
                print(f"[ERROR] 下载文件失败: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"[ERROR] 下载FRP失败: {e}")
            return False
            version = self.get_latest_version()
            if not version:
                return False
            
            # 构建下载URL
            base_url = f"https://github.com/fatedier/frp/releases/download/v{version}"
            
            # 下载客户端
            frpc_url = f"{base_url}/{self.frpc_bin_name}"
            frpc_path = os.path.join(self.config['FRP_BIN_DIR'], 'frpc')
            if self.system == 'windows':
                frpc_path += '.exe'
            
            print(f"[INFO] 正在下载 FRP 客户端: {frpc_url}")
            self._download_file(frpc_url, frpc_path)
            
            # 下载服务端
            frps_url = f"{base_url}/{self.frps_bin_name}"
            frps_path = os.path.join(self.config['FRP_BIN_DIR'], 'frps')
            if self.system == 'windows':
                frps_path += '.exe'
            
            print(f"[INFO] 正在下载 FRP 服务端: {frps_url}")
            self._download_file(frps_url, frps_path)
            
            # 设置执行权限（Linux）
            if self.system == 'linux':
                os.chmod(frpc_path, 0o755)
                os.chmod(frps_path, 0o755)
            
            return True
            
        except Exception as e:
            print(f"[ERROR] 下载FRP失败: {e}")
            return False
    
    def _download_file(self, url, filepath):
        """下载文件"""
        try:
            # 禁用SSL验证，避免下载失败
            response = requests.get(url, stream=True, timeout=60, verify=False)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            sys.stdout.write(f"\r下载进度: {percent:.1f}% ({downloaded}/{total_size} bytes)")
                            sys.stdout.flush()
            
            print()  # 换行
            
            # 验证下载的文件大小
            if total_size > 0:
                actual_size = os.path.getsize(filepath)
                if actual_size >= total_size * 0.9:  # 允许10%的误差
                    return True
                else:
                    print(f"[ERROR] 文件下载不完整，预期大小: {total_size}, 实际大小: {actual_size}")
                    os.remove(filepath)
                    return False
            
            return True
            
        except Exception as e:
            print(f"[ERROR] 下载文件失败: {e}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return False
    
    def check_frp_binary(self):
        """检查FRP二进制文件是否存在"""
        # 检查两种文件名格式
        frpc_paths = [
            os.path.join(self.config['FRP_BIN_DIR'], 'frpc'),
            os.path.join(self.config['FRP_BIN_DIR'], self.frpc_bin_name.split('.')[0])
        ]
        frps_paths = [
            os.path.join(self.config['FRP_BIN_DIR'], 'frps'),
            os.path.join(self.config['FRP_BIN_DIR'], self.frps_bin_name.split('.')[0])
        ]
        
        if self.system == 'windows':
            frpc_paths = [path + '.exe' for path in frpc_paths]
            frps_paths = [path + '.exe' for path in frps_paths]
        
        # 检查所有可能的文件路径
        frpc_exists = any(os.path.exists(path) for path in frpc_paths)
        frps_exists = any(os.path.exists(path) for path in frps_paths)
        
        return frpc_exists and frps_exists
    
    def get_frp_binary(self, mode='client'):
        """获取FRP二进制文件路径"""
        if mode == 'client':
            binary_names = ['frpc', self.frpc_bin_name.split('.')[0]]
        else:
            binary_names = ['frps', self.frps_bin_name.split('.')[0]]
        
        # 尝试找到存在的文件
        for binary_name in binary_names:
            binary_path = os.path.join(self.config['FRP_BIN_DIR'], binary_name)
            if self.system == 'windows':
                binary_path += '.exe'
            
            if os.path.exists(binary_path):
                return binary_path
        
        # 如果都找不到，返回默认路径
        binary_path = os.path.join(self.config['FRP_BIN_DIR'], binary_names[0])
        if self.system == 'windows':
            binary_path += '.exe'
        return binary_path
    
    def start_frp(self, config_path, mode='client'):
        """启动FRP"""
        try:
            # 停止已运行的进程
            self.stop_frp()
            
            # 获取二进制文件路径
            binary_path = self.get_frp_binary(mode)
            if not os.path.exists(binary_path):
                print(f"[ERROR] FRP二进制文件不存在: {binary_path}")
                return False
            
            # 构建命令
            if self.system == 'windows':
                cmd = [binary_path, '-c', config_path]
            else:
                cmd = [binary_path, '-c', config_path]
            
            # 启动进程
            log_file = os.path.join(self.config['FRP_LOG_DIR'], f'frp_{mode}_{int(time.time())}.log')
            with open(log_file, 'w') as log_f:
                self.frp_process = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if self.system == 'windows' else 0
                )
            
            print(f"[INFO] FRP {mode} 已启动 (PID: {self.frp_process.pid})")
            print(f"[INFO] 日志文件: {log_file}")
            return True
            
        except Exception as e:
            print(f"[ERROR] 启动FRP失败: {e}")
            return False
    
    def stop_frp(self):
        """停止FRP"""
        if self.frp_process and self.frp_process.poll() is None:
            try:
                self.frp_process.terminate()
                self.frp_process.wait(timeout=5)
                print(f"[INFO] FRP进程已停止")
            except Exception as e:
                print(f"[WARN] 停止FRP进程时出错: {e}")
                try:
                    self.frp_process.kill()
                except:
                    pass
            finally:
                self.frp_process = None
        return True
    
    def get_frp_status(self):
        """获取FRP状态"""
        # 检查内部进程
        if self.frp_process and self.frp_process.poll() is None:
            return {
                'running': True,
                'pid': self.frp_process.pid,
                'returncode': self.frp_process.poll(),
                'message': '通过Web UI启动'
            }
        
        # 检查系统中的FRP进程
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'frpc' in proc.info['name'].lower():
                        cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                        return {
                            'running': True,
                            'pid': proc.info['pid'],
                            'returncode': None,
                            'message': f'通过命令行启动: {cmdline[:100]}'
                        }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            return {
                'running': False,
                'pid': None,
                'returncode': None,
                'message': f'检测进程时出错: {e}'
            }
        
        return {
            'running': False,
            'pid': None,
            'returncode': None,
            'message': 'FRP未运行'
        }
    
    def read_frp_log(self, lines=100):
        """读取FRP日志"""
        try:
            log_files = sorted(Path(self.config['FRP_LOG_DIR']).glob('frp_*.log'))
            if not log_files:
                return "暂无日志"
            
            latest_log = log_files[-1]
            with open(latest_log, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 返回最后lines行
            lines_list = content.strip().split('\n')
            return '\n'.join(lines_list[-lines:])
        except Exception as e:
            return f"读取日志失败: {e}"
    
    def save_config(self, config_type, config_content):
        """保存配置文件"""
        try:
            config_file = os.path.join(self.config['FRP_CONFIG_DIR'], f'{config_type}.ini')
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)
            return config_file
        except Exception as e:
            print(f"[ERROR] 保存配置文件失败: {e}")
            return None
    
    def load_config(self, config_type):
        """加载配置文件"""
        try:
            # 支持三种配置类型
            config_files = [
                os.path.join(self.config['FRP_CONFIG_DIR'], f'{config_type}.ini'),
                os.path.join(self.config['FRP_CONFIG_DIR'], f'{config_type}.toml'),
                os.path.join(self.config['FRP_CONFIG_DIR'], f'{config_type}.json')
            ]
            
            # 找到第一个存在的配置文件
            config_file = None
            for file_path in config_files:
                if os.path.exists(file_path):
                    config_file = file_path
                    break
            
            if config_file:
                with open(config_file, 'r', encoding='utf-8') as f:
                    return f.read()
            return ''
        except Exception as e:
            print(f"[ERROR] 加载配置文件失败: {e}")
            return ''