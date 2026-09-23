# FRP Manager - Cross-Platform FRP Management Tool

<div align="right">

[简体中文](README.md) | **English**

</div>

A clean and efficient cross-platform FRP management tool with a Web UI for configuration and control.

> **ARM Ubuntu (aarch64 / armv7l) is supported** — see [ARM / Ubuntu Deployment](#arm--ubuntu-deployment).
> One-line install: `./install_arm.sh --service`

![FRP Manager](https://img.shields.io/badge/FRP-Manager-blue)
![Python-3.7+-green](https://img.shields.io/badge/Python-3.7+-green)
![License-MIT-yellow](https://img.shields.io/badge/License-MIT-yellow)
![Platform-Windows%20%7C%20Linux%20%7C%20ARM%20%7C%20macOS-9cf](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20ARM%20%7C%20macOS-9cf)

## 🖼️ Screenshots

> Real rendered UI, captured with demo data (no real configs or secrets).

**Dashboard · Light theme**

![Dashboard · Light](docs/screenshots/01-dashboard-light.png)

**Dashboard · Dark theme**

![Dashboard · Dark](docs/screenshots/02-dashboard-dark.png)

| Config & Download | System Settings |
| :---: | :---: |
| ![Config & Download](docs/screenshots/03-settings-light.png) | ![System Settings](docs/screenshots/04-system-light.png) |
| **Security Center** | **Audit Log** |
| ![Security Center](docs/screenshots/05-security-light.png) | ![Audit Log](docs/screenshots/06-audit-light.png) |

## ✨ Features

- ✅ **Web UI management** - intuitive browser-based configuration
- ✅ **One-click start/stop** - quick control of FRP services
- ✅ **Real-time status monitoring** - process info and live status
- ✅ **Log viewer** - live logs including raw frp errors
- ✅ **Responsive design** - works on phone, tablet and desktop
- ✅ **Cross-platform** - Windows / Linux(x86_64) / **ARM Linux(ARM64/ARM32)** / macOS
- ✅ **Architecture auto-detection** - downloads the right frpc/frps for your CPU
- ✅ **Boot autostart** - one-click registration per OS (Windows registry / systemd / launchd), plus "start FRPC / FRPS with app"
- ✅ **Download progress** - live progress bar for binary downloads, with China mirror support (ghfast / gh-proxy etc.)
- ✅ **Watchdog self-healing** - auto-restarts crashed frpc / frps; stops and alerts after repeated crashes to avoid avalanche
- ✅ **Scheduled restart** - automatically restart frpc / frps every N hours or at a daily time (new in v1.13.0)
- ✅ **Config security scan** - detects exposed dashboards, missing auth token, wrong server_addr, with fix suggestions
- ✅ **Log rotation & export** - size-based rotation with history, manual rotate and per-file download
- ✅ **Offline package import** - install official frp archives (.zip / .tar.gz) without internet
- ✅ **Audit log** - records start / stop / restart / config save / import / settings changes with source IP
- ✅ **Downtime alerts** - Webhook (DingTalk / Feishu / WeCom) or email on failure events
- ✅ **Config snapshots & rollback** - auto snapshot on every save, diff and one-click rollback
- ✅ **Token / encryption wizard** - generate strong tokens, quick-add STCP / SUDP secure tunnels
- ✅ **Form-based proxy editor** - type-aware fields, serialized to `[[proxies]]`
- ✅ **Standalone audit page** - filter / stats / export
- ✅ **Light & dark themes** - consistent styling across controls
- ✅ **Per-page lazy loading** - only the current page fetches data; polling skipped when hidden
- ✅ **Bilingual UI** - built-in Chinese / English switch (🌐 in the top bar)

## 🚀 Quick Start

### Requirements

- Python 3.7+
- Flask, requests, psutil (`pip install -r requirements.txt`)

### Install & Run

```bash
git clone https://github.com/Code847/frp-manager.git
cd frp-manager

pip install -r requirements.txt

# Download frp binaries (bin/ is NOT in the repo, required on first run)
python download_frp.py

python main.py

# Open the Web UI (port auto-increments if taken; check console output)
# http://localhost:5000
```

> **Why is `bin/` not in the repo?** The frpc / frps binaries are ~143MB combined.
> Run `python download_frp.py` after cloning (China mirrors built in), or download/switch
> versions graphically in "System Settings → frp Version".

### Windows

Double-click `start.bat` (visible console mode; errors stay on screen).
The panel also provides a **system tray icon**:

| Icon color | Meaning |
|------|------|
| 🟢 Green | frps + frpc both running |
| 🟠 Orange | only one running |
| 🔴 Red | both stopped |

Right-click menu groups Start / Restart / Stop for FRPS, FRPC and All, plus
Open Web UI / Refresh / Exit. Status syncs every 3 seconds.

### Linux / ARM Ubuntu

```bash
chmod +x install_arm.sh start_linux.sh build_arm.sh

./install_arm.sh                 # environment only
sudo ./install_arm.sh --service  # install + systemd autostart (recommended)

./start_linux.sh                 # or run in foreground
python3 main.py --check          # environment self-check
```

## 🔐 Web Login

The panel is protected by an optional login page (tech-style glassmorphism with particle background).
Credentials live in `configs/web_auth.ini`:

```ini
[auth]
enabled         = true      # login protection on/off
username        = admin
password        = admin     # plain text or werkzeug pbkdf2 hash
captcha         = true      # SVG captcha (pure Python, no Pillow)
session_minutes = 0         # 0 = expire when browser closes
remember_days   = 7         # "remember this device" days
```

Default account `admin` / `admin` — change it in "Web Settings → Login" or by editing the ini.

## ⚙️ Configuration

Client config lives at `configs/client.toml` (server: `configs/server.toml`):

```ini
[common]
server_addr = your-frp-server
server_port = 7000
token = your-auth-token

[proxy1]
type = tcp
local_ip = 127.0.0.1
local_port = 80
remote_port = 6080
```

## 🔄 Updating frpc / frps

Three ways — none of them touch your existing config:

1. **In the UI (recommended)** — "Config & Download → FRP Download / Update", with live progress and China mirrors.
2. **Manual replace** — drop binaries into `bin/` named `frpc_<os>_<arch>` / `frps_<os>_<arch>` (or plain `frpc`/`frps`). Existing files are never overwritten.
3. **Version switching** — "frp Version" panel scans `bin/`, `bin/versions/` and unpacked archives; old versions are archived automatically before switching.

## 🕐 Scheduled Restart (v1.13.0)

"System Settings → Guard & Alerts → Scheduled Restart" automatically restarts frpc / frps:

- **Interval mode** - every N hours (1–720)
- **Daily mode** - at a fixed time each day (HH:MM)
- frpc and frps can be toggled independently
- Only restarts processes that are **running or registered with the watchdog** — it never starts frp on its own
- Failures are written to the `[Panel]` event log and trigger alert pushes
- Stored in `configs/app_settings.ini` under `[restart]`; API: `GET/POST /api/settings/autorestart`

## 🔧 API Overview

| Endpoint | Method | Description |
|------|------|------|
| `/api/status` | GET | frpc / frps running status & port mapping |
| `/api/info` | GET | platform, arch, binary paths & versions, data dirs |
| `/api/start` `/api/stop` `/api/restart` | POST | control FRP (`mode=client\|server`) |
| `/api/config/<client\|server>` | GET/POST | read/write the authoritative config |
| `/api/log` | GET | merged logs (`mode=all\|client\|server\|webui`) |
| `/api/links` | GET | HTTP link reachability (panel / frps API / tunnels) |
| `/api/download-frp` | POST | background binary download (optional `version` / `mirror`) |
| `/api/download-frp/progress` | GET | download progress polling |
| `/api/bin/versions` `/api/bin/switch` | GET/POST | list / switch local frp versions |
| `/api/settings/autostart` | GET/POST | boot autostart settings |
| `/api/settings/monitor` | GET/POST | watchdog settings |
| `/api/settings/autorestart` | GET/POST | scheduled restart settings (v1.13.0) |
| `/api/settings/alert` | GET/POST | downtime alert settings |
| `/api/snapshots/<type>` etc. | GET/POST/DELETE | config snapshots & rollback |
| `/api/security/token` etc. | POST | token wizard / secure proxy |
| `/login` `/logout` `/api/login` `/api/captcha` | GET/POST | authentication |

### frps Admin API

Enable `webServer` in `configs/server.toml`:

```toml
[webServer]
addr = "0.0.0.0"
port = 7500
user = "admin"
password = "change-me"
```

> Known pitfall: in legacy `.ini` server config, a `[webServer]` section is **silently ignored**
> by frp — use `dashboard_*` keys in `[common]` instead (the UI offers a one-click fix).

## 📁 Project Layout

```
frp-manager/
├── main.py                # entry point (cross-platform, tray included)
├── frp_manager.py         # FRP core (arch detection, watchdog, scheduled restart)
├── web_ui.py              # Flask routes & business APIs
├── web_auth.py            # login auth (password / SVG captcha / sessions)
├── download_frp.py        # standalone frp downloader
├── web/                   # UI: single-file index.html + login.html (all inline)
├── bin/                   # frp binaries (not in repo) + versions/ archive
├── configs/               # runtime configs (client.toml / server.toml / app_settings.ini ...)
├── logs/                  # frp / manager / audit logs
└── temp/                  # runtime temp (downloads, lock, pid)
```

## 📦 ARM / Ubuntu Deployment

Adapted for **ARM Ubuntu** (aarch64 / armv7l): Raspberry Pi, Kunpeng, Phytium, RK3588, ARM cloud instances.

| Problem (original) | Fix |
|------|------|
| Hardcoded `frpc_linux_amd64` | auto-mapped `linux_arm64` / `linux_arm` / `linux_amd64` / `linux_386` |
| Windows-only download URL | per-platform package name, auto extract + `chmod +x` |
| `subprocess.CREATE_NO_WINDOW` crash | unified `_creation_flags()` |
| `tasklist` process probing | `psutil` (also detects externally started frpc/frps) |
| `pkill -f frpc` mis-kills | `psutil` enumerate + terminate |
| headless `input()` blocking | `threading.Event` wait, systemd-friendly |
| PEP 668 pip block | venv aware, `--break-system-packages` fallback, Tsinghua mirror |

```bash
cd /opt/frp-manager
chmod +x install_arm.sh start_linux.sh build_arm.sh
sudo ./install_arm.sh --service --port 5000
```

For Python 3.6 (Ubuntu 18.04 aarch64) the installer auto-switches to `requirements-py36.txt`
(Flask 1.1.x, pure-Python chain); upgrading to Python 3.8+ is recommended.

### systemd (Linux servers)

```ini
[Unit]
Description=FRP Manager - Web Panel
After=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/frp-manager
ExecStart=/opt/frp-manager/venv/bin/python /opt/frp-manager/main.py --no-tray
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now frp-manager
journalctl -u frp-manager -f
```

### CLI Options

```
python main.py [--host ADDR] [--port N] [--no-tray] [--force] [--check] [--download-frp] [--version]
```

## ❓ FAQ

**1. `FRP binary not found` on start** — run `./install_arm.sh` or place `frpc_linux_arm64` / `frps_linux_arm64` (chmod 755) into `bin/`.

**2. `Exec format error`** — wrong-architecture binary; verify with `file bin/frpc_linux_arm64`.

**3. frps dashboard unreachable (Connection refused)** — likely the ini `[webServer]` pitfall above; use the one-click fix or switch to TOML, then restart frps.

**4. frpc fails to start** — check the raw frp error in "Logs"; usually `server_addr` / `token` missing or server unreachable.

**5. pip `externally-managed-environment`** — use a venv, or let the installer add `--break-system-packages`.

## ☕ Support the Project

If this project helps you, buying the author a coffee is appreciated —
**your donation keeps development going!**

<div align="center">

<img src="docs/donate-wechat.jpg" alt="WeChat donation QR" width="280">

*WeChat scan to donate · every bit is appreciated ❤️*

</div>

## 🤝 Contributing

Issues and Pull Requests are welcome!

## 📄 License

MIT License.

## 🙏 Thanks

- [FRP](https://github.com/fatedier/frp) - the great reverse-proxy / tunnel tool
- [Flask](https://flask.palletsprojects.com/) - lightweight web framework
