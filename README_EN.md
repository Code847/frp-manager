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
- ✅ **Login hardening** - failed-login rate limiting, IP allowlist (CIDR), optional TOTP 2FA (RFC6238)
- ✅ **Per-platform binary downloads** - 9 OS/arch targets, SHA256 verification, resume support, "download only, don't install"
- ✅ **PWA** - add to Home Screen / desktop icon; shell works offline, live data always from network
- ✅ **Keyboard shortcuts** - `?` help, `/` focus filter, `Esc` close, `Ctrl+S` save, `Ctrl+D` refresh
- ✅ **Accessibility** - skip link, `focus-visible` rings, aria / role semantics
- ✅ **Single-file exe distribution** - `python build_exe.py` produces a standalone exe (no Python needed on the target machine); `build_installer.bat` wraps it into an installer with optional autostart and desktop shortcut

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

### 🛡️ Login Hardening (v1.15.0)

A `[security]` section in the same file, **all off by default, applied immediately, no restart needed**:

```ini
[security]
login_rate_limit = false   # master switch for failed-login limiting
max_fails         = 5      # failures inside the window
fail_window_min   = 15     # statistics window (minutes)
lock_min          = 30     # lock duration after triggering (minutes)
ip_allowlist      =        # comma-separated IPs, CIDR supported
totp_enabled      = false  # TOTP 2FA master switch
totp_secret       =        # generated by the UI, do not hand-edit
```

UI: **Security Center → Login Hardening** (same page as the account settings).

| Option | Description |
|------|-------------|
| **Failed-login limiting** | Counts failures per IP; after `max_fails` inside the window, that IP is rejected for `lock_min` minutes. Counters live in memory and reset on restart. |
| **IP allowlist (CIDR)** | Accepts `192.168.1.0/24`, `10.0.0.0/8` and friends. Allowlisted IPs **bypass everything, even the failure counter**, so a bad config can never lock you out. |
| **TOTP 2FA** | RFC6238 implemented in pure Python (no third-party package). "Set up TOTP" shows a secret plus an `otpauth://` URI for Authenticator / 1Password; once enabled, a 6-digit code is required at login. |

> Back up the TOTP secret after enabling — losing it means disabling 2FA and re-binding.

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

**Three capabilities added in v1.15.0:**

| Capability | Notes |
|------------|-------|
| SHA256 verification | Fetches the official `checksums.txt`; a mismatch discards the package and marks the download failed. If no checksum is available the step is **skipped**, not failed — friendly for offline / self-hosted release pages. |
| Resume support | Downloads continue from `.part` via HTTP `Range`; if the server ignores Range and returns 200 the partial file is discarded and restarted; on failure the `.part` is kept for the next attempt. |
| Per-platform downloads | Pick a target other than the running one (e.g. a Linux ARM64 build for an SBC). The archive lands in `packages/` for you to copy — **your local `bin/` is untouched**. The progress bar shows `checksum / verified` and the final SHA256. |

Nine targets are available: Windows (x86_64 / ARM64 / 32-bit), Linux (x86_64 / ARM64 / ARMv7 / 32-bit) and macOS (x86_64 / Apple Silicon).
`linux_arm64`, `linux-arm64` and `linux/arm64` are all accepted.

## 📱 Install as an App (PWA, v1.15.0)

The panel ships a web app manifest, a service worker and an icon, so Chrome / Edge can offer
**"Install" or "Add to Home Screen"** — it then runs in its own window, independent of the browser tab.

- Service worker caches the shell only; `/api/*` and `/login` are **never** cached, so status is always live.
- Registration only happens on https or localhost. Over plain http on your LAN the browser would refuse it, so the panel silently degrades instead of throwing errors.
- `/sw.js`, `/manifest.webmanifest` and `/icon.svg` are served **without** the login guard — otherwise an unauthenticated browser could never fetch the manifest.

## 🔼 Panel Self-Update (v1.14.0)

The web panel can upgrade **itself** ("Panel Update" in the sidebar) — `main.py`, `web/index.html`, `frp_manager.py`, `web_ui.py`, etc.

- **Two update sources** — by default the official GitHub Releases (anonymous download, no token needed); or set a custom manifest URL in settings (JSON: `{version, notes, url, sha256?}`) for intranet / private distribution or local verification.
- **Safe overlay** — the package is SHA256-verified (when the manifest provides one), then only code files are overlaid. Protected directories — `configs / logs / temp / bin / .git / .workbuddy / venv` — are **never** touched, so updating never loses your config or deletes downloaded binaries. Extraction uses `zipfile.extractall(filter='data')` (Python 3.12+) to block zip path traversal.
- **Auto-backup & rollback** — before every overlay the current version is backed up to `temp/backup/<timestamp>/`; if something goes wrong (or you just want to revert), click "Rollback" on the Panel Update page to restore the pre-update version.
- **In-place restart** — after apply / rollback the process is relaunched in place (`os.execv` / `Popen`, Windows uses `pythonw` with no console window); the whole flow runs in a background thread so Web requests never block.

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
| `/api/download-frp` | POST | background binary download (optional `version` / `mirror` / `target` / `verify`) |
| `/api/auth/security` | GET/POST | read / write login-hardening settings (rate limit, CIDR allowlist, TOTP flag) — public |
| `/api/auth/totp/setup` | POST | **public**. Generate a TOTP secret; returns `secret` and the `otpauth://` URI |
| `/api/auth/totp/enable` | POST | **public**. Verify a 6-digit code, then really enable TOTP (`{code}`) |
| `/api/auth/totp/disable` | POST | **public**. Turn TOTP off |
| `/manifest.webmanifest` `/sw.js` `/icon.svg` | GET | PWA assets — served without login |
| `/api/download-frp/progress` | GET | download progress polling |
| `/api/bin/versions` `/api/bin/switch` | GET/POST | list / switch local frp versions |
| `/api/settings/autostart` | GET/POST | boot autostart settings |
| `/api/settings/monitor` | GET/POST | watchdog settings |
| `/api/settings/autorestart` | GET/POST | scheduled restart settings (v1.13.0) |
| `/api/settings/alert` | GET/POST | downtime alert settings |
| `/api/snapshots/<type>` etc. | GET/POST/DELETE | config snapshots & rollback |
| `/api/security/token` etc. | POST | token wizard / secure proxy |
| `/login` `/logout` `/api/login` `/api/captcha` | GET/POST | authentication |
| `/api/update/check` | GET | check for panel update (version / notes / url) |
| `/api/update/source` | GET/POST | read / set update source (empty = official GitHub) |
| `/api/update/apply` | POST | apply update in background (download → backup → overlay → restart) |
| `/api/update/rollback` | POST | rollback to latest backup in background |

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
├── build_exe.py           # PyInstaller packaging (onefile exe; --onedir for debugging)
├── installer.iss          # Inno Setup 6 script for the Windows installer
├── build_installer.bat    # one-click installer build (version read from the exe)
├── dist/                  # build output (gitignored)
├── web/                   # UI: single-file index.html + login.html (all inline)
│   ├── manifest.webmanifest # PWA manifest
│   ├── sw.js                # service worker (static only; API and /login never cached)
│   └── icon.svg             # PWA icon (512x512)
├── bin/                   # frp binaries (not in repo) + versions/ archive
├── packages/              # per-platform archives pulled for other devices
├── configs/               # runtime configs (client.toml / server.toml / app_settings.ini / web_auth.ini)
├── logs/                  # frp / manager / audit logs
└── temp/                  # runtime temp (downloads, lock, pid)
```

## ⌨️ Keyboard Shortcuts (v1.15.0)

| Key | Action |
|-----|--------|
| `?` | Shortcut help dialog |
| `/` | Jump to the filter box on the current page |
| `Esc` | Close the topmost dialog / form |
| `Ctrl+S` | Save the section you are looking at |
| `Ctrl+D` | Refresh the current page |

Shortcuts are ignored while typing in an input, textarea or select.

## 📦 Windows Packaging (v1.16.0)

Build a standalone exe or a full installer:

```bash
pip install -r requirements.txt pyinstaller

python build_exe.py            # -> dist\FRP-Manager-<timestamp>.exe  (~34 MB)
python build_exe.py --onedir   # debug build: console output, faster startup

build_installer.bat            # -> Output\FRP-Manager-<version>-Setup.exe
```

The packaged resources are deliberately **clean**:

- Only `configs/README.md` is bundled as the seed. `seed_data()` copies bundled
  configs into the user data directory on first run, so shipping the build
  machine's own `web_auth.ini` / `.web_secret` / `client.toml` would leak its
  credentials and seed every user's first start with another's settings.
- Only the two frp binaries for the current platform are bundled. Cross-platform
  files also inflated the exe from ~34 MB to ~150 MB.
- The seeded layout is flat (`_MEIPASS/bin/frpc_windows_amd64.exe`). A nested
  `bin/bin/` made the launcher silently re-download frp from GitHub instead of
  failing loudly - which looks like "slow first start" and hides completely.

Runtime data (`configs/` `bin/` `logs/` `temp/`) is written next to the exe and
never removed by the uninstaller.

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
