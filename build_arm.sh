#!/usr/bin/env bash
# ============================================================
#  FRP Manager - Linux 跨架构打包脚本（PyInstaller）
#
#  架构自适应：aarch64/arm64 -> arm64，armv7l/arm -> arm，
#             x86_64/amd64 -> amd64（即 Ubuntu x86_64 亦可）。
#  注意：PyInstaller 不支持交叉编译，必须在目标架构的机器上执行。
#
#  产物: dist/FRP-Manager/FRP-Manager
# ============================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

MACHINE="$(uname -m)"
case "$MACHINE" in
    aarch64|arm64|armv8l) FRP_ARCH="arm64" ;;
    armv7l|armv6l|arm)    FRP_ARCH="arm" ;;
    x86_64|amd64)         FRP_ARCH="amd64" ;;
    *) echo "[ERROR] 未知架构: $MACHINE"; exit 1 ;;
esac

echo "============================================================"
echo "      FRP Manager - Linux 打包 ($MACHINE -> linux_${FRP_ARCH})"
echo "============================================================"

command -v python3 >/dev/null 2>&1 || { echo "[ERROR] 未找到 python3"; exit 1; }

PY="${APP_DIR}/venv/bin/python"
if [[ ! -x "$PY" ]]; then
    echo "[INFO] 创建虚拟环境..."
    python3 -m venv "$APP_DIR/venv" 2>/dev/null || {
        sudo apt update && sudo apt install -y python3-venv python3-pip
        python3 -m venv "$APP_DIR/venv"
    }
fi

# 根据构建机 Python 版本选择依赖文件（与 install_arm.sh / main.py 保持一致）
PY_VER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)"
if [ "$(printf '%s\n' "$PY_VER" "3.7" | sort -V | head -1)" != "3.7" ]; then
    REQ_FILE="$APP_DIR/requirements-py36.txt"
    echo "[INFO] 检测到 Python $PY_VER (< 3.7)，使用兼容依赖 $REQ_FILE"
    sudo apt-get update -qq 2>/dev/null || true
    sudo apt-get install -y gcc python3-dev 2>/dev/null || true
else
    REQ_FILE="$APP_DIR/requirements.txt"
fi

echo "[INFO] 安装打包依赖..."
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$REQ_FILE" \
    -i "${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
"$APP_DIR/venv/bin/pip" install -q pyinstaller \
    -i "${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

# 校验 frp 二进制架构
FRPC="bin/frpc_linux_${FRP_ARCH}"
FRPS="bin/frps_linux_${FRP_ARCH}"
if [[ ! -f "$FRPC" || ! -f "$FRPS" ]]; then
    echo "[ERROR] 缺少 $FRPC / $FRPS"
    echo "[ERROR] 请先执行: ./install_arm.sh --no-service  或手动放入 bin/ 目录"
    exit 1
fi
chmod 755 "$FRPC" "$FRPS"
echo "[INFO] 校验二进制架构:"
file "$FRPC" "$FRPS" || true

echo "[INFO] 清理旧构建..."
rm -rf build dist

echo "[INFO] 开始打包..."
# 只把 configs/README.md 作为种子打包；app_settings.ini / web_auth.ini / .web_secret
# 等运行时配置由程序首次运行自动生成，绝不能打包进发布包 —— 否则会把构建机的
# 登录凭据哈希和 secret 带进二进制、污染所有用户环境（首次运行 seed_data 会因
# 「目标目录已存在」而跳过覆盖）。temp/ 同理是运行时目录，不打包。
PKG_CONFIGS="$(mktemp -d)"
cp -f "$APP_DIR/configs/README.md" "$PKG_CONFIGS/" 2>/dev/null || true
"$APP_DIR/venv/bin/pyinstaller" \
    --name=FRP-Manager \
    --onedir \
    --console \
    --noconfirm \
    --add-data "web_ui.py:." \
    --add-data "web_auth.py:." \
    --add-data "frp_manager.py:." \
    --add-data "$PKG_CONFIGS:configs" \
    --add-data "web:web" \
    --add-data "bin:bin" \
    --hidden-import=requests \
    --hidden-import=psutil \
    --hidden-import=flask \
    --hidden-import=markupsafe \
    --hidden-import=jinja2 \
    --hidden-import=werkzeug \
    --hidden-import=click \
    --hidden-import=itsdangerous \
    --hidden-import=blinker \
    main.py

if [[ -f "dist/FRP-Manager/FRP-Manager" ]]; then
    mkdir -p "dist/FRP-Manager/_internal/temp" \
             "dist/FRP-Manager/_internal/logs"
    cat > "dist/FRP-Manager/start.sh" <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec ./FRP-Manager "$@"
EOF
    chmod +x "dist/FRP-Manager/start.sh"

    echo
    echo "============================================================"
    echo "[SUCCESS] 打包完成"
    echo "[FILE] dist/FRP-Manager/FRP-Manager"
    echo "运行:  ./dist/FRP-Manager/start.sh"
    echo "自检:  ./dist/FRP-Manager/FRP-Manager --check"
    echo "============================================================"
    echo "[提示] 目标机器需具备 glibc >= 当前构建机版本"
    rm -rf "$PKG_CONFIGS"
else
    echo "[ERROR] 打包失败"
    exit 1
fi
