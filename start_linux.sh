#!/usr/bin/env bash
# ============================================================
#  FRP Manager - Linux 跨架构启动脚本（ARM64 / ARM32 / x86_64 / x86）
#  用法: ./start_linux.sh [--port 5000]
# ============================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

PORT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *) shift ;;
    esac
done

echo "============================================================"
echo "         FRP Manager - 跨平台版"
echo "============================================================"
echo "架构: $(uname -m)"

# 选择 Python 解释器：优先虚拟环境
if [[ -x "$APP_DIR/venv/bin/python" ]]; then
    PY="$APP_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    echo "[错误] 未找到 python3，请先执行: sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

# 缺少依赖时自动安装（虚拟环境/系统环境均尝试）
# 依赖文件按 Python 版本选择，与 build_arm.sh / install_arm.sh / main.py 保持一致
if ! "$PY" -c "import flask, requests, psutil" >/dev/null 2>&1; then
    echo "[信息] 正在安装依赖..."
    PY_VER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)"
    if [ "$(printf '%s\n' "$PY_VER" "3.7" | sort -V | head -1)" != "3.7" ]; then
        REQ_FILE="$APP_DIR/requirements-py36.txt"
        echo "[信息] 检测到 Python $PY_VER (< 3.7)，使用兼容依赖 $REQ_FILE"
    else
        REQ_FILE="$APP_DIR/requirements.txt"
    fi
    if [[ -x "$APP_DIR/venv/bin/pip" ]]; then
        "$APP_DIR/venv/bin/pip" install -r "$REQ_FILE" \
            -i https://pypi.tuna.tsinghua.edu.cn/simple
    else
        "$PY" -m pip install -r "$REQ_FILE" --break-system-packages \
            -i https://pypi.tuna.tsinghua.edu.cn/simple \
        || "$PY" -m pip install -r "$REQ_FILE" \
            -i https://pypi.tuna.tsinghua.edu.cn/simple
    fi
fi

# 确保 frp 二进制存在且有执行权限
mkdir -p bin logs temp
MACHINE="$(uname -m)"
case "$MACHINE" in
    aarch64|arm64|armv8l) FRP_ARCH="arm64" ;;
    armv7l|armv6l|arm)    FRP_ARCH="arm" ;;
    x86_64|amd64)         FRP_ARCH="amd64" ;;
    *)                    FRP_ARCH="amd64" ;;
esac
if [[ ! -f "bin/frpc_linux_${FRP_ARCH}" ]]; then
    echo "[警告] 未找到 bin/frpc_linux_${FRP_ARCH}，程序启动后会尝试自动下载"
    echo "[警告] 也可手动放入该文件（frp 官方 linux_${FRP_ARCH} 包的 frpc / frps）"
else
    chmod +x "bin/frpc_linux_${FRP_ARCH}" "bin/frps_linux_${FRP_ARCH}" 2>/dev/null || true
fi

echo "[信息] 启动 FRP Manager..."
echo

if [[ -n "$PORT" ]]; then
    exec "$PY" "$APP_DIR/main.py" --port "$PORT"
else
    exec "$PY" "$APP_DIR/main.py"
fi
