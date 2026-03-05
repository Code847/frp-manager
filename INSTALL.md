# FRP Manager 安装指南

## 系统要求

- **Windows**: Windows 7/8/10/11, Python 3.7+
- **Linux**: Ubuntu/Debian/CentOS, Python 3.7+
- **内存**: 至少 512MB RAM
- **磁盘**: 至少 100MB 可用空间

## 快速安装

### Windows 用户

1. 下载本项目
2. 双击运行 `start_windows.bat`
3. 程序会自动：
   - 检查Python环境
   - 创建虚拟环境
   - 安装依赖包
   - 下载FRP二进制文件
   - 启动Web界面

### Linux 用户

1. 下载本项目
2. 给启动脚本添加执行权限：
   ```bash
   chmod +x start_linux.sh
   ```
3. 运行启动脚本：
   ```bash
   ./start_linux.sh
   ```

## 手动安装

### 1. 安装Python

**Windows:**
- 访问 [Python官网](https://www.python.org/downloads/)
- 下载Python 3.7+ 安装包
- 安装时勾选 "Add Python to PATH"

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip -y
```

**Linux (CentOS/RHEL):**
```bash
sudo yum install python3 python3-pip -y
```

### 2. 下载项目

```bash
# 使用git克隆
git clone https://github.com/your-repo/frp-manager.git
cd frp-manager

# 或者直接下载ZIP包并解压
```

### 3. 安装依赖

```bash
# 创建并激活虚拟环境
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 安装依赖包
pip install -r requirements.txt
```

### 4. 运行程序

```bash
python main.py
```

访问 http://localhost:8080 打开配置界面

## 防火墙配置

### Windows 防火墙
1. 打开"Windows Defender 防火墙"
2. 点击"允许应用或功能通过防火墙"
3. 点击"允许其他应用"
4. 浏览到 `frp-manager\bin\frpc.exe` 和 `frp-manager\bin\frps.exe`
5. 勾选"专用"和"公用"网络

### Linux 防火墙
```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 8080/tcp  # Web界面端口
sudo ufw allow 7000/tcp  # FRP默认端口

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --permanent --add-port=7000/tcp
sudo firewall-cmd --reload
```

## 使用说明

### 首次运行
1. 程序会自动下载FRP二进制文件
2. 访问 http://localhost:8080 打开Web界面
3. 在"快速配置"中填写服务器信息
4. 点击"生成配置"
5. 点击"保存配置"
6. 选择运行模式（客户端/服务端）
7. 点击"启动FRP"

### 配置说明
- **客户端模式**: 用于将本地服务暴露到公网
- **服务端模式**: 用于搭建FRP服务器
- **配置文件**: 支持ini格式，语法与官方FRP一致

### 常见问题

#### 1. 下载FRP失败
- 检查网络连接
- 手动下载FRP二进制文件：
  - Windows: 下载 `frpc_windows_amd64.exe` 和 `frps_windows_amd64.exe`
  - Linux: 下载 `frpc_linux_amd64` 和 `frps_linux_amd64`
  - 放到 `frp-manager/bin/` 目录下
  - Linux系统需要给二进制文件添加执行权限：`chmod +x bin/frpc bin/frps`

#### 2. Web界面无法访问
- 检查端口8080是否被占用
- 检查防火墙设置
- 尝试使用 `http://127.0.0.1:8080`

#### 3. FRP连接失败
- 检查服务器地址和端口是否正确
- 检查token是否一致
- 检查防火墙是否放行相应端口
- 查看日志文件获取详细错误信息

#### 4. 程序无法启动
- 检查Python版本是否为3.7+
- 检查依赖包是否安装成功
- 查看控制台输出的错误信息

## 目录结构

```
frp-manager/
├── main.py              # 主程序入口
├── web_ui.py           # Web界面服务
├── frp_manager.py      # FRP管理核心
├── requirements.txt    # Python依赖
├── start_windows.bat   # Windows启动脚本
├── start_linux.sh      # Linux启动脚本
├── README.md           # 说明文档
├── INSTALL.md          # 安装指南
├── static/            # Web静态文件
│   ├── index.html
│   ├── style.css
│   └── script.js
├── configs/           # 配置文件目录
│   ├── frpc.example.ini
│   └── frps.example.ini
├── bin/              # FRP二进制文件目录
├── logs/             # 日志目录
└── temp/             # 临时文件目录
```

## 更新说明

要更新FRP Manager到最新版本：

1. 停止当前运行的FRP服务
2. 下载最新版本代码
3. 重新运行 `start_windows.bat` 或 `start_linux.sh`
4. 程序会自动更新FRP二进制文件

## 技术支持

如有问题，请：
1. 查看日志文件获取详细信息
2. 检查防火墙和网络设置
3. 参考官方FRP文档：https://gofrp.org/docs/

## 许可证

本项目基于 MIT 许可证开源。