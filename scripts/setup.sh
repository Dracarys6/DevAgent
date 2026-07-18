#!/usr/bin/env bash

set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
    cat <<'EOF'
用法：scripts/setup.sh [选项]

创建 Python 虚拟环境，并安装后端与前端依赖。

选项：
  -h, --help   显示帮助

环境变量：
  PYTHON_BIN   创建虚拟环境所用的 Python 命令（默认 python3）
EOF
}

fail() {
    echo "环境初始化失败：$*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "未知参数：$1"
            ;;
    esac
done

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "未找到 Python：${PYTHON_BIN}"
command -v node >/dev/null 2>&1 || fail "未找到 Node.js"
command -v npm >/dev/null 2>&1 || fail "未找到 npm"

"$PYTHON_BIN" -c '
import sys

if sys.version_info < (3, 11):
    raise SystemExit("DevAgent 需要 Python 3.11 或更高版本")
' || fail "Python 版本不满足要求"

if [ ! -x "${VENV_DIR}/bin/python" ]; then
    echo "正在创建 Python 虚拟环境：${VENV_DIR}"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "正在安装 Python 依赖和 editable 项目..."
"${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_ROOT}/requirements.txt"
"${VENV_DIR}/bin/python" -m pip install -e "$PROJECT_ROOT"

echo "正在安装前端依赖..."
(
    cd "${PROJECT_ROOT}/frontend"
    npm ci
)

echo
echo "开发环境初始化完成。"
echo "运行 ./scripts/start.sh 启动项目。"
