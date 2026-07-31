#!/usr/bin/env bash

set -eu

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_BACKEND=true
RUN_FRONTEND=false

usage() {
    cat <<'EOF'
用法：scripts/test.sh [选项] [pytest 参数]

默认运行后端测试；未识别的参数会原样传给 pytest。

选项：
  --backend    只运行后端测试（默认）
  --frontend   只运行前端 lint 和生产构建
  --all        运行后端测试、前端 lint 和生产构建
  -h, --help   显示帮助

示例：
  ./scripts/test.sh
  ./scripts/test.sh tests/api/test_health.py -q
  ./scripts/test.sh --all
EOF
}

run_backend() {
    command -v uv >/dev/null 2>&1 || {
        echo "缺少 uv，请先运行 ./scripts/setup.sh" >&2
        exit 1
    }

    echo "==> 运行后端测试"
    (
        cd "$PROJECT_ROOT"
        uv run --locked pytest "$@"
    )
}

run_frontend() {
    [ -x "${PROJECT_ROOT}/frontend/node_modules/.bin/eslint" ] || {
        echo "缺少前端依赖，请先运行 ./scripts/setup.sh" >&2
        exit 1
    }

    echo "==> 运行前端 lint"
    (
        cd "${PROJECT_ROOT}/frontend"
        npm run lint
    )

    echo "==> 运行前端生产构建"
    (
        cd "${PROJECT_ROOT}/frontend"
        npm run build
    )
}

PYTEST_ARGS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --backend)
            RUN_BACKEND=true
            RUN_FRONTEND=false
            ;;
        --frontend)
            RUN_BACKEND=false
            RUN_FRONTEND=true
            ;;
        --all)
            RUN_BACKEND=true
            RUN_FRONTEND=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            ;;
    esac
    shift
done

if [ "$RUN_BACKEND" = false ] && [ "${#PYTEST_ARGS[@]}" -gt 0 ]; then
    echo "--frontend 模式不接受 pytest 参数" >&2
    exit 2
fi

if [ "$RUN_BACKEND" = true ]; then
    if [ "${#PYTEST_ARGS[@]}" -gt 0 ]; then
        run_backend "${PYTEST_ARGS[@]}"
    else
        run_backend
    fi
fi

if [ "$RUN_FRONTEND" = true ]; then
    run_frontend
fi

echo
echo "测试与检查完成。"
