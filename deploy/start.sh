#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# HiClaw — Start all services
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage:
#   bash deploy/start.sh pro    — 生产模式 (hiclaw-runtime.tar.gz)
#   bash deploy/start.sh dev    — 开发模式 (Poetry venv)
#   bash deploy/start.sh        — 自动检测
#
# ─── 环境变量 ───
#   HICLAW_DIR            数据目录         默认: ~/.hiclaw
#   HICLAW_GITEA_PORT     Gitea 端口       默认: 3300
#   HICLAW_MANAGER_PORT   Manager 端口     默认: 9090
#   HICLAW_APP_PORT       OpenHands 端口   默认: 3000
#   HICLAW_APP_IP         App Server IP   默认: 自动检测
#   HICLAW_GITEA_USER     Gitea 管理员     默认: hiclaw-admin
#   HICLAW_GITEA_PASSWORD Gitea 密码       默认: HiClaw2026!
#   HICLAW_LLM_DEBUG      LLM debug 日志   默认: 关闭 (设为1开启)
# ═══════════════════════════════════════════════════════════════════════════

set -e
MODE="${1:-auto}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HICLAW_DIR="${HICLAW_DIR:-$HOME/.hiclaw}"
GITEA_PORT="${HICLAW_GITEA_PORT:-3300}"
MANAGER_PORT="${HICLAW_MANAGER_PORT:-9090}"
APP_PORT="${HICLAW_APP_PORT:-3000}"
GITEA_USER="${HICLAW_GITEA_USER:-hiclaw-admin}"
GITEA_PASS="${HICLAW_GITEA_PASSWORD:-HiClaw2026!}"
MANAGER_DIR="$PROJECT_DIR/agent-worker-manager"
LOG_DIR="$HICLAW_DIR/logs"

mkdir -p "$LOG_DIR"

# ─── Python 环境 ───
RUNTIME_DIR="$HICLAW_DIR/runtime"

select_pro() {
    if [ ! -f "$RUNTIME_DIR/hiclaw-python" ]; then
        echo "ERROR: Runtime not installed. Run: bash deploy/setup.sh"
        exit 1
    fi
    PYTHON="$RUNTIME_DIR/hiclaw-python"
    UVICORN="$RUNTIME_DIR/hiclaw-uvicorn"
    echo "  Mode: PRODUCTION (hiclaw-runtime)"
}

select_dev() {
    # Find Poetry venv
    POETRY_VENV="$(find "$HOME/.cache/pypoetry/virtualenvs" -name 'uvicorn' -path '*/bin/uvicorn' -type f 2>/dev/null | head -1)"
    if [ -n "$POETRY_VENV" ]; then
        POETRY_VENV="$(dirname "$(dirname "$POETRY_VENV")")"
        PYTHON="$POETRY_VENV/bin/python3"
        UVICORN="$POETRY_VENV/bin/uvicorn"
        export PATH="$POETRY_VENV/bin:$PATH"
        echo "  Mode: DEVELOPMENT (Poetry venv)"
    elif command -v uvicorn &>/dev/null; then
        PYTHON="python3"
        UVICORN="uvicorn"
        echo "  Mode: DEVELOPMENT (system Python)"
    else
        echo "ERROR: No Poetry venv or system uvicorn found."
        echo "  Run: cd $PROJECT_DIR && poetry install"
        exit 1
    fi
}

case "$MODE" in
    pro|prod|production)
        select_pro ;;
    dev|development)
        select_dev ;;
    auto|"")
        if [ -f "$RUNTIME_DIR/hiclaw-python" ]; then
            select_pro
        else
            select_dev
        fi ;;
    *)
        echo "Usage: bash deploy/start.sh [pro|dev]"
        exit 1 ;;
esac

echo "=== Starting HiClaw Services ==="
echo "  Python: $($PYTHON --version 2>&1)"
echo "  Data:   $HICLAW_DIR"
echo ""

# ─── Generate Gitea config from template ───
GITEA_CONF="$HICLAW_DIR/gitea/custom/conf/app.ini"
GITEA_TEMPLATE="$SCRIPT_DIR/gitea-config/app.ini.template"
if [ -f "$GITEA_TEMPLATE" ]; then
    mkdir -p "$(dirname "$GITEA_CONF")"
    sed -e "s|__USER__|$(whoami)|g" \
        -e "s|__HICLAW_DIR__|$HICLAW_DIR|g" \
        -e "s|__GITEA_PORT__|$GITEA_PORT|g" \
        -e "s|__APP_PORT__|$APP_PORT|g" \
        "$GITEA_TEMPLATE" > "$GITEA_CONF"
fi

# ─── 1. Gitea ───
if ! ss -tlnp | grep -q ":$GITEA_PORT "; then
    GITEA_BIN="$HICLAW_DIR/bin/gitea"
    [ ! -f "$GITEA_BIN" ] && GITEA_BIN="$(which gitea 2>/dev/null || echo gitea)"
    echo "[1/3] Starting Gitea (port $GITEA_PORT)..."
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" web \
        --config "$GITEA_CONF" \
        > "$LOG_DIR/gitea.log" 2>&1 &
    disown
    sleep 5
else
    echo "[1/3] Gitea already running (port $GITEA_PORT)"
fi

# ─── 2. Worker Manager ───
if ! ss -tlnp | grep -q ":$MANAGER_PORT "; then
    echo "[2/3] Starting Worker Manager (port $MANAGER_PORT)..."
    cd "$MANAGER_DIR" && $PYTHON run.py > "$LOG_DIR/manager.log" 2>&1 &
    disown
    cd "$PROJECT_DIR"
    sleep 2
else
    echo "[2/3] Worker Manager already running (port $MANAGER_PORT)"
fi

# ─── 3. OpenHands App Server ───
if ! ss -tlnp | grep -q ":$APP_PORT "; then
    echo "[3/3] Starting OpenHands App Server (port $APP_PORT)..."
    cd "$PROJECT_DIR" && $UVICORN openhands.server.listen:app \
        --host 0.0.0.0 --port $APP_PORT \
        > "$LOG_DIR/openhands.log" 2>&1 &
    disown
    cd "$PROJECT_DIR"
else
    echo "[3/3] OpenHands already running (port $APP_PORT)"
fi

# ─── 等待并验证 ───
echo ""
echo "Waiting for services to start..."
sleep 20

echo ""
echo "=== Service Status ==="
for port_name in "$APP_PORT:OpenHands" "$GITEA_PORT:Gitea" "$MANAGER_PORT:WorkerManager"; do
    port="${port_name%%:*}"
    name="${port_name##*:}"
    if ss -tlnp | grep -q ":$port "; then
        echo "  ✓ $name (port $port)"
    else
        echo "  ✗ $name (port $port) — NOT RUNNING"
    fi
done

echo ""
echo "=== URLs ==="
echo "  App:    http://localhost:$APP_PORT"
echo "  Skills: http://localhost:$APP_PORT/skill-management"
echo "  Gitea:  http://localhost:$GITEA_PORT ($GITEA_USER / $GITEA_PASS)"
echo ""
echo "=== Logs (all in $LOG_DIR/) ==="
echo "  tail -f $LOG_DIR/openhands.log"
echo "  tail -f $LOG_DIR/manager.log"
echo "  tail -f $LOG_DIR/gitea.log"
echo "  Remote: ssh <host> 'tail -f /tmp/agent-server-*.log'"
