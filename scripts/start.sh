#!/usr/bin/env bash

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="${DEVAGENT_BACKEND_PORT:-8000}"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="${DEVAGENT_FRONTEND_PORT:-5173}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"
OPEN_BROWSER=true
BACKEND_PID=""
FRONTEND_PID=""
SHUTTING_DOWN=false

usage() {
    cat <<'EOF'
用法：scripts/start.sh [选项]

同时启动 DevAgent FastAPI 后端和 Vite 前端。

选项：
  --open       启动成功后打开浏览器（默认）
  --no-open    启动成功后不打开浏览器
  -h, --help   显示帮助

环境变量：
  DEVAGENT_BACKEND_PORT   后端端口（默认 8000）
  DEVAGENT_FRONTEND_PORT  前端端口（默认 5173）
EOF
}

fail() {
    echo "启动失败：$*" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

port_is_in_use() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_url() {
    local name="$1"
    local url="$2"
    local attempts="${3:-60}"
    local attempt=1

    while [ "$attempt" -le "$attempts" ]; do
        if curl --silent --fail --output /dev/null "$url"; then
            return 0
        fi

        if [ -n "$BACKEND_PID" ] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
            return 1
        fi
        if [ -n "$FRONTEND_PID" ] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
            return 1
        fi

        sleep 0.5
        attempt=$((attempt + 1))
    done

    echo "${name}未在预期时间内就绪：${url}" >&2
    return 1
}

open_browser() {
    if command_exists open; then
        open "about:blank" >/dev/null 2>&1
        return
    fi

    if command_exists xdg-open; then
        xdg-open "about:blank" >/dev/null 2>&1
        return
    fi

    echo "未找到 open 或 xdg-open，无法自动打开浏览器。"
}

cleanup() {
    local exit_code="${1:-0}"

    if [ "$SHUTTING_DOWN" = true ]; then
        return
    fi
    SHUTTING_DOWN=true

    echo
    echo "正在停止 DevAgent..."

    if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi

    [ -z "$FRONTEND_PID" ] || wait "$FRONTEND_PID" 2>/dev/null || true
    [ -z "$BACKEND_PID" ] || wait "$BACKEND_PID" 2>/dev/null || true

    echo "DevAgent 已停止。"
    exit "$exit_code"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --open)
            OPEN_BROWSER=true
            ;;
        --no-open)
            OPEN_BROWSER=false
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "未知参数：$1"
            ;;
    esac
    shift
done

VENV_UVICORN="${PROJECT_ROOT}/.venv/bin/uvicorn"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
VITE_BIN="${FRONTEND_DIR}/node_modules/.bin/vite"

[ -x "$VENV_UVICORN" ] || fail "缺少 ${VENV_UVICORN}，请先安装 Python 依赖和项目"
[ -f "${FRONTEND_DIR}/package.json" ] || fail "缺少 frontend/package.json"
[ -x "$VITE_BIN" ] || fail "缺少前端依赖，请先执行：cd frontend && npm install"
command_exists node || fail "未找到 Node.js"
command_exists npm || fail "未找到 npm"
command_exists curl || fail "未找到 curl"
command_exists lsof || fail "未找到 lsof"

port_is_in_use "$BACKEND_PORT" && fail "端口 ${BACKEND_PORT} 已被占用"
port_is_in_use "$FRONTEND_PORT" && fail "端口 ${FRONTEND_PORT} 已被占用"

trap 'cleanup 130' INT TERM
trap 'cleanup $?' EXIT

echo "正在启动 DevAgent..."
echo "后端：${BACKEND_URL}"
echo "前端：${FRONTEND_URL}"
echo "按 Ctrl+C 可同时停止前后端。"
echo

(
    cd "$PROJECT_ROOT" || exit 1
    exec "$VENV_UVICORN" devagent.api.app:app \
        --reload \
        --host "$BACKEND_HOST" \
        --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

(
    cd "$FRONTEND_DIR" || exit 1
    exec npm run dev -- \
        --host "$FRONTEND_HOST" \
        --port "$FRONTEND_PORT" \
        --strictPort
) &
FRONTEND_PID=$!

if ! wait_for_url "后端" "${BACKEND_URL}/health"; then
    fail "后端启动失败，请查看上方日志"
fi

if ! wait_for_url "前端" "$FRONTEND_URL"; then
    fail "前端启动失败，请查看上方日志"
fi

echo
echo "DevAgent 已启动：${FRONTEND_URL}"

if [ "$OPEN_BROWSER" = true ]; then
    open_browser
fi

while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        wait "$BACKEND_PID" 2>/dev/null
        status=$?
        echo "后端进程已退出，状态码：${status}" >&2
        cleanup "$status"
    fi

    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        wait "$FRONTEND_PID" 2>/dev/null
        status=$?
        echo "前端进程已退出，状态码：${status}" >&2
        cleanup "$status"
    fi

    sleep 1
done
