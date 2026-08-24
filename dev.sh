#!/usr/bin/env bash
# aiChatBot 一键启动/停止脚本（开发环境）
# 用法：./dev.sh {start|stop|status|restart}

set -u

cd "$(dirname "$0")"

RUN_DIR=".run"          # PID 文件目录（不入库）
LOG_DIR="logs"          # 日志目录（不入库）
SERVICES=("agent" "bot" "admin")
PORTS=("8100" "" "8200")  # 与服务一一对应的监听端口（bot 为 Long Polling，无端口）

mkdir -p "$RUN_DIR" "$LOG_DIR"

log()  { echo "[dev] $*"; }
warn() { echo "[dev] ⚠ $*"; }
err()  { echo "[dev] ✗ $*" >&2; }

# ---------- 环境检查 ----------
check_env() {
    source "$HOME/.local/bin/env" 2>/dev/null || true
    if ! command -v uv >/dev/null 2>&1; then
        err "未找到 uv，请先安装：curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    if [ ! -d ".venv" ]; then
        log "首次运行，安装依赖……"
        uv sync || exit 1
    fi
    if [ ! -f ".env" ]; then
        err "缺少 .env 配置文件，请先：cp .env.example .env 并填写配置"
        exit 1
    fi
}

service_pid() {
    [ -f "$RUN_DIR/$1.pid" ] && cat "$RUN_DIR/$1.pid" 2>/dev/null || echo ""
}

is_running() {
    local pid; pid=$(service_pid "$1")
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_one() {
    local svc="$1"
    if is_running "${svc}"; then
        log "${svc} 已在运行 (PID $(service_pid "${svc}"))，跳过"
        return
    fi
    # bot 缺少 Token 时跳过并提示
    if [ "${svc}" = "bot" ] && ! grep -q '^TELEGRAM_BOT_TOKEN=.\+' .env 2>/dev/null; then
        warn "未配置 TELEGRAM_BOT_TOKEN，跳过 bot-api 启动"
        return
    fi
    log "启动 ${svc} ......"
    nohup uv run python -m "${svc}" >> "${LOG_DIR}/${svc}.log" 2>&1 &
    echo $! > "${RUN_DIR}/${svc}.pid"
    sleep 1
    if is_running "${svc}"; then
        log "${svc} 已启动（PID $(service_pid "${svc}")，日志：${LOG_DIR}/${svc}.log）"
    else
        err "${svc} 启动失败，请查看 ${LOG_DIR}/${svc}.log"
    fi
}

stop_one() {
    local svc="$1"
    local pid; pid=$(service_pid "${svc}")
    if ! is_running "${svc}"; then
        rm -f "${RUN_DIR}/${svc}.pid"
        return
    fi
    log "停止 ${svc} (PID ${pid}) ..."
    kill "${pid}" 2>/dev/null
    for _ in $(seq 1 10); do
        is_running "${svc}" || break
        sleep 0.5
    done
    if is_running "${svc}"; then
        warn "${svc} 未响应 SIGTERM，强制结束"
        kill -9 "${pid}" 2>/dev/null
    fi
    rm -f "${RUN_DIR}/${svc}.pid"
}

cmd_start() {
    check_env
    for svc in "${SERVICES[@]}"; do
        start_one "$svc"
    done
    log "完成。管理后台：http://127.0.0.1:8200 ，ai-agent 接口文档：http://127.0.0.1:8100/docs"
}

cmd_stop() {
    for ((i=${#SERVICES[@]}-1; i>=0; i--)); do
        stop_one "${SERVICES[$i]}"
    done
    log "全部服务已停止"
}

cmd_status() {
    local all_stopped=1
    for svc in "${SERVICES[@]}"; do
        if is_running "${svc}"; then
            log "${svc} 运行中 (PID $(service_pid "${svc}"))"
            all_stopped=0
        else
            log "${svc} 未运行"
        fi
    done
    return "$all_stopped"
}

case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    status)  cmd_status ;;
    *)       echo "用法：$0 {start|stop|status|restart}"; exit 1 ;;
esac
