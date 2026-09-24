#!/usr/bin/env bash
# ============================================================
#  FRP Manager - 跨架构一键安装脚本（ARM64 / ARM32 / x86_64 / x86）
#  支持: aarch64 (ARM64) / armv7l (ARM32) / x86_64 (AMD64) / i386
#
#  用法:
#    ./install_arm.sh              # 安装依赖 + 下载对应架构 frp
#    ./install_arm.sh --service    # 额外安装 systemd 服务并开机自启
#    ./install_arm.sh --port 8080  # 指定 Web 端口（默认 5000）
# ============================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

WEB_PORT=""
INSTALL_SERVICE=0
FRP_VERSION="${FRP_VERSION:-0.71.0}"
VENV_DIR="$APP_DIR/venv"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service) INSTALL_SERVICE=1; shift ;;
        --port)    WEB_PORT="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -20
            exit 0 ;;
        *) echo "[WARN] 未知参数: $1"; shift ;;
    esac
done

info()  { echo -e "\033[32m[INFO]\033[0m $*"; }
warn()  { echo -e "\033[33m[WARN]\033[0m $*"; }
error() { echo -e "\033[31m[ERROR]\033[0m $*"; }

echo "============================================================"
echo "      FRP Manager - 跨架构安装脚本（ARM64 / ARM32 / x86_64 / x86）"
echo "============================================================"

# ---------- 1. 识别架构 ----------
MACHINE="$(uname -m)"
case "$MACHINE" in
    aarch64|arm64|armv8l) FRP_ARCH="arm64" ;;
    armv7l|armv7|armv6l|arm) FRP_ARCH="arm" ;;
    x86_64|amd64)         FRP_ARCH="amd64" ;;
    i386|i686)            FRP_ARCH="386" ;;
    *)
        error "暂不支持的架构: $MACHINE"
        error "可手动下载 frpc/frps 放入 $APP_DIR/bin/ 后重试"
        exit 1 ;;
esac
FRP_PLATFORM="linux_${FRP_ARCH}"
info "当前架构: $MACHINE  ->  frp 发布包: $FRP_PLATFORM"

# ---------- 2. Python 环境 ----------
if command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    info "未检测到 python3，正在通过 apt 安装..."
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv
    PY="$(command -v python3)"
fi
info "Python: $($PY --version 2>&1)  ($PY)"

# 低版本 Python（如 3.6，Ubuntu 18.04 默认）会自动选用兼容的旧版依赖
REQ_FILE="$APP_DIR/requirements.txt"
PY_VER="$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)"
if [ "$(printf '%s\n' "$PY_VER" "3.7" | sort -V | head -1)" != "3.7" ]; then
    warn "检测到 Python $PY_VER (< 3.7)，将安装兼容旧版依赖（Flask 1.1.x 全纯 Python wheel 链路）"
    warn "注意：ARM aarch64 上该链路需本地编译 MarkupSafe / psutil，请确保已装 gcc 与 python3-dev"
    warn "如需新版特性，强烈建议升级到 Python 3.8+（Ubuntu 20.04+ 默认即为 3.8+），升级后可直接用普通 requirements.txt"
    REQ_FILE="$APP_DIR/requirements-py36.txt"
    # 本地编译 C 扩展（MarkupSafe / psutil）所需的工具链
    info "安装编译依赖: gcc python3-dev python3-venv"
    sudo apt-get update -qq
    sudo apt-get install -y gcc python3-dev python3-venv
fi

info "创建虚拟环境: $VENV_DIR"
if [[ ! -d "$VENV_DIR" ]]; then
    $PY -m venv "$VENV_DIR" 2>/dev/null || {
        warn "创建虚拟环境失败，正在安装 python3-venv..."
        sudo apt update && sudo apt install -y python3-venv python3-pip
        $PY -m venv "$VENV_DIR"
    }
fi

info "安装 Python 依赖..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$REQ_FILE" \
    -i "${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
info "依赖安装完成（使用 $REQ_FILE）"

# ---------- 3. 下载对应架构的 frp ----------
mkdir -p "$APP_DIR/bin" "$APP_DIR/logs" "$APP_DIR/temp"
FRPC="$APP_DIR/bin/frpc_${FRP_PLATFORM}"
FRPS="$APP_DIR/bin/frps_${FRP_PLATFORM}"

if [[ -x "$FRPC" && -x "$FRPS" ]]; then
    info "已存在 $FRP_PLATFORM 的 frpc/frps，跳过下载"
else
    ARCHIVE="frp_${FRP_VERSION}_${FRP_PLATFORM}.tar.gz"
    TMPDIR="$(mktemp -d)"
    MIRRORS=(
        "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${ARCHIVE}"
        "https://ghfast.top/https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${ARCHIVE}"
        "https://gh-proxy.com/https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${ARCHIVE}"
        "https://ghproxy.net/https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${ARCHIVE}"
    )

    OK=0
    for URL in "${MIRRORS[@]}"; do
        info "下载 $URL"
        if curl -fL --connect-timeout 15 --retry 3 --progress-bar \
                -o "$TMPDIR/$ARCHIVE" "$URL"; then
            OK=1
            break
        fi
        warn "该镜像失败，尝试下一个..."
    done

    if [[ $OK -eq 1 ]]; then
        tar -xzf "$TMPDIR/$ARCHIVE" -C "$TMPDIR"
        SRC_DIR="$TMPDIR/frp_${FRP_VERSION}_${FRP_PLATFORM}"
        cp -f "$SRC_DIR/frpc" "$FRPC"
        cp -f "$SRC_DIR/frps" "$FRPS"
        chmod 755 "$FRPC" "$FRPS"
        rm -rf "$TMPDIR"
        info "frp 二进制安装完成: bin/frpc_${FRP_PLATFORM}  bin/frps_${FRP_PLATFORM}"
    else
        rm -rf "$TMPDIR"
        warn "自动下载失败（网络受限）"
        warn "请手动把 frpc / frps 放到: $APP_DIR/bin/"
        warn "并重命名为: frpc_${FRP_PLATFORM} / frps_${FRP_PLATFORM}，再执行 chmod +x"
        warn "官方下载页: https://github.com/fatedier/frp/releases"
    fi
fi

# ---------- 4. Web 端口 ----------
if [[ -n "$WEB_PORT" ]]; then
    echo "port = $WEB_PORT" > "$APP_DIR/configs/web_port.ini"
    info "Web 端口已设为 $WEB_PORT"
fi

# ---------- 5. 自检 ----------
info "运行环境自检："
"$VENV_DIR/bin/python" "$APP_DIR/main.py" --check || true

# ---------- 6. systemd 服务（可选） ----------
if [[ $INSTALL_SERVICE -eq 1 ]]; then
    SERVICE_NAME="frp-manager"
    RUN_USER="${SUDO_USER:-$(id -un)}"
    UNIT="/etc/systemd/system/${SERVICE_NAME}.service"

    info "安装 systemd 服务: $UNIT (运行用户: $RUN_USER)"
    sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=FRP Manager - Web 管理面板
Documentation=https://github.com/fatedier/frp
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/main.py --no-tray
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=15
StandardOutput=append:${APP_DIR}/logs/service.log
StandardError=append:${APP_DIR}/logs/service.log

# 基础加固
NoNewPrivileges=true
PrivateTmp=false

[Install]
WantedBy=multi-user.target
EOF

    # frpc 需要监听本地端口并对外连接，给它 setuid 能力无需 root
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2
    sudo systemctl --no-pager --lines=10 status "$SERVICE_NAME" || true

    PORT_NOW="$(grep -o '[0-9]\+' "$APP_DIR/configs/web_port.ini" 2>/dev/null | head -1 || echo 5000)"
    echo
    info "服务已启动。访问: http://<本机IP>:${PORT_NOW:-5000}"
    info "管理命令: sudo systemctl {start|stop|restart|status|disable} ${SERVICE_NAME}"
else
    echo
    info "安装完成。启动方式："
    echo "    ./start_linux.sh              # 前台启动"
    echo "    ./install_arm.sh --service    # 安装为 systemd 服务（推荐）"
fi
echo
info "如需放行 Web 端口: sudo ufw allow ${WEB_PORT:-5000}/tcp"
