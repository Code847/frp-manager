# FRP Manager - 跨平台FRP管理工具

一个简洁高效的跨平台FRP管理工具，提供Web界面进行配置和管理。

![FRP Manager](https://img.shields.io/badge/FRP-Manager-blue)
![Python-3.7+-green](https://img.shields.io/badge/Python-3.7+-green)
![License-MIT-yellow](https://img.shields.io/badge/License-MIT-yellow)

## ✨ 功能特性

- ✅ **Web界面管理** - 直观易用的网页配置界面
- ✅ **一键启动/停止** - 快速控制FRP服务
- ✅ **实时状态监控** - 查看运行状态和进程信息
- ✅ **日志查看** - 实时查看运行日志
- ✅ **响应式设计** - 支持手机、平板、电脑自适应
- ✅ **跨平台支持** - Windows/Linux 均可使用

## 🚀 快速开始

### 环境要求

- Python 3.7+
- Flask
- requests
- psutil

### 安装运行

```bash
# 克隆项目
git clone https://github.com/yourusername/frp-manager.git
cd frp-manager

# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py

# 访问Web界面
# http://localhost:5000
```

### Windows 快速启动

双击运行 `start.bat` 或在命令行执行：

```batch
start.bat
```
### Windows 单文件启动（无需下载项目，直接执行单文件）

请下载最新版：

https://github.com/Code847/frp-manager/releases
# 点击运行，右下角（时钟角表旁）会有程序，包括启动停止退出等
# 注：文件会自动生成配置目录和执行目录



## 📁 项目结构

```
frp-manager/
├── main.py              # 主程序入口
├── web_ui.py            # Web界面服务
├── frp_manager.py       # FRP管理核心
├── requirements.txt     # Python依赖
├── start.bat            # Windows启动脚本
├── README.md            # 项目说明
├── bin/                 # FRP二进制文件(可从frp官网下载最新的替换)
│   ├── frpc_windows_amd64.exe
│   └── frps_windows_amd64.exe
├── configs/             # 配置文件目录
│   └── client_simple.ini
├── static/              # Web静态资源
│   ├── script.js
│   └── style.css
└── logs/                # 日志目录
```

## ⚙️ 配置说明

默认配置文件 `configs/client_simple.ini`：

```ini
[common]
server_addr = 你的FRP服务器地址
server_port = 7000
token = 你的认证令牌

[代理名称1]
type = tcp
local_ip = 127.0.0.1
local_port = 本地端口
remote_port = 远程端口

[代理名称2]
type = tcp
local_ip = 127.0.0.1
local_port = 本地端口
remote_port = 远程端口
```

## 📱 界面预览
<img width="1026" height="768" alt="ScreenShot_2026-03-05_163550_608" src="https://github.com/user-attachments/assets/08f1681c-ace5-4a56-a159-8d4cc2caf862" />

### 桌面端
- 三列状态卡片
- 完整功能展示
- 宽松布局设计

### 移动端
- 单列自适应布局
- 紧凑元素设计
- 触屏优化交互

## 🔧 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | 获取FRP运行状态 |
| `/api/start` | POST | 启动FRP服务 |
| `/api/stop` | POST | 停止FRP服务 |
| `/api/config/client` | GET/POST | 客户端配置 |
| `/api/log` | GET | 获取运行日志 |

## 📝 更新日志

### v1.0.0 (2026-03-05)
- 初始版本发布
- Web界面管理
- 一键启动/停止
- 响应式设计
- 支持端口修改（修改后需要重启）

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！
哈哈哈

## 📄 许可证

MIT License - 欢迎使用和修改

## 🙏 感谢

- [FRP](https://github.com/fatedier/frp) - 优秀的内网穿透工具
- [Flask](https://flask.palletsprojects.com/) - 轻量级Web框架
