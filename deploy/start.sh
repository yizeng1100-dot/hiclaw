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

# ─── Bypass proxy for localhost (corporate networks) ───
export no_proxy="${no_proxy:+$no_proxy,}localhost,127.0.0.1"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}localhost,127.0.0.1"

# ─── LLM model info for models not in LiteLLM's database ───
# Without this, context window shows 0/0 and token-based condensation won't trigger.
# Add custom models here as needed. Format: {"model_name": {max_tokens, max_input_tokens, ...}}
export LITELLM_LOCAL_MODEL_COST_MAP="${LITELLM_LOCAL_MODEL_COST_MAP:-$(cat <<'COSTMAP'
{"qianfan-code-latest": {"max_tokens": 131072, "max_input_tokens": 204800, "max_output_tokens": 131072, "input_cost_per_token": 0.000001, "output_cost_per_token": 0.000002, "litellm_provider": "openai"}, "glm-4.7": {"max_tokens": 4096, "max_input_tokens": 131072, "max_output_tokens": 4096, "input_cost_per_token": 0.000001, "output_cost_per_token": 0.000002, "litellm_provider": "openai"}}
COSTMAP
)}"

# ─── Auto-detect app-server IP for internal networks ───
# Remote agent-servers need this IP to callback to app-server (MCP, webhooks)
# Priority: env var > ip route default > hostname -I
if [ -z "$HICLAW_APP_IP" ]; then
    HICLAW_APP_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
    [ -z "$HICLAW_APP_IP" ] && HICLAW_APP_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$HICLAW_APP_IP" ] && HICLAW_APP_IP="127.0.0.1"
fi
export HICLAW_APP_IP
echo "  App IP: $HICLAW_APP_IP"

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

# ─── Build frontend if source changed ───
if [ -d "$PROJECT_DIR/frontend" ] && command -v npm &>/dev/null; then
    FRONTEND_BUILD="$PROJECT_DIR/frontend/build/client/index.html"
    FRONTEND_SRC="$PROJECT_DIR/frontend/src"
    # Rebuild if no build exists or source is newer than build
    if [ ! -f "$FRONTEND_BUILD" ] || [ -n "$(find "$FRONTEND_SRC" -newer "$FRONTEND_BUILD" -print -quit 2>/dev/null)" ]; then
        echo "[0/3] Building frontend..."
        cd "$PROJECT_DIR/frontend" && npm run build 2>&1 | tail -3
        cd "$PROJECT_DIR"
    fi
fi

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

# ─── DB schema migration (add HiClaw custom columns) ───
OH_DB="$HOME/.openhands/openhands.db"
if [ -f "$OH_DB" ]; then
    $PYTHON -c "
import sqlite3
conn = sqlite3.connect('$OH_DB')
cols = [r[1] for r in conn.execute('PRAGMA table_info(conversation_metadata)').fetchall()]
if 'remote_agent_url' not in cols:
    conn.execute('ALTER TABLE conversation_metadata ADD COLUMN remote_agent_url TEXT')
    conn.commit()
    print('  DB migration: added remote_agent_url column')
conn.close()
" 2>/dev/null
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
