#!/bin/bash
# HiClaw — Start all services
# Usage: bash hiclaw/start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HICLAW_DIR="/opt/hiclaw"
GITEA_PORT="${HICLAW_GITEA_PORT:-3300}"
GITEA_USER="${HICLAW_GITEA_USER:-hiclaw-admin}"
GITEA_PASS="${HICLAW_GITEA_PASSWORD:-HiClaw2026!}"
MANAGER_DIR="$SCRIPT_DIR/agent-worker-manager"

# Use offline venv if available, otherwise use system Python
if [ -d "$HICLAW_DIR/venv/bin" ]; then
    export PATH="$HICLAW_DIR/venv/bin:$PATH"
    PYTHON="$HICLAW_DIR/venv/bin/python3"
    UVICORN="$HICLAW_DIR/venv/bin/uvicorn"
else
    PYTHON="python3"
    UVICORN="uvicorn"
fi

echo "=== Starting HiClaw Services ==="

# 1. Gitea
if ! ss -tlnp | grep -q ":3300 "; then
    echo "[1/3] Starting Gitea (port 3300)..."
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" gitea web \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
        > "$HICLAW_DIR/gitea/log/startup.log" 2>&1 &
    disown
    sleep 5
else
    echo "[1/3] Gitea already running"
fi

# 2. Worker Manager
if ! ss -tlnp | grep -q ":9090 "; then
    echo "[2/3] Starting Worker Manager (port 9090)..."
    cd "$MANAGER_DIR" && $PYTHON run.py > /tmp/manager.log 2>&1 &
    disown
    cd "$PROJECT_DIR"
    sleep 2
else
    echo "[2/3] Worker Manager already running"
fi

# 3. OpenHands App Server
if ! ss -tlnp | grep -q ":3000 "; then
    echo "[3/3] Starting OpenHands App Server (port 3000)..."
    cd "$PROJECT_DIR" && $UVICORN openhands.server.listen:app \
        --host 0.0.0.0 --port 3000 \
        > ~/openhands.log 2>&1 &
    disown
    cd "$PROJECT_DIR"
else
    echo "[3/3] OpenHands already running"
fi

# Wait and verify
echo ""
echo "Waiting for services to start..."
sleep 15

echo ""
echo "=== Service Status ==="
for port_name in "3000:OpenHands" "3300:Gitea" "9090:WorkerManager"; do
    port="${port_name%%:*}"
    name="${port_name##*:}"
    if ss -tlnp | grep -q ":$port "; then
        echo "  ✓ $name (port $port)"
    else
        echo "  ✗ $name (port $port) — NOT RUNNING"
    fi
done

echo ""
echo "URLs:"
echo "  App:    http://localhost:3000"
echo "  Skills: http://localhost:3000/skill-management"
echo "  Gitea:  http://localhost:$GITEA_PORT ($GITEA_USER / $GITEA_PASS)"
