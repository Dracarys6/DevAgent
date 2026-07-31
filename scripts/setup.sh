#!/usr/bin/env bash

set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
用法：scripts/setup.sh [选项]

使用 uv 创建 Python 虚拟环境，并安装后端与前端依赖。

选项：
  -h, --help   显示帮助

Python 版本由项目根目录的 .python-version 管理；uv 会在需要时安装它。
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

command -v uv >/dev/null 2>&1 || fail "未找到 uv，请先安装：https://docs.astral.sh/uv/getting-started/installation/"
command -v node >/dev/null 2>&1 || fail "未找到 Node.js"
command -v npm >/dev/null 2>&1 || fail "未找到 npm"

echo "正在通过 uv 同步 Python、依赖和 editable 项目..."
(
    cd "$PROJECT_ROOT"
    uv sync --locked
)

echo "正在安装前端依赖..."
(
    cd "${PROJECT_ROOT}/frontend"
    npm ci
)

echo
echo "开发环境初始化完成。"
echo "运行 ./scripts/start.sh 启动项目。"
