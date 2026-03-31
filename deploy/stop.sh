#!/bin/bash
# HiClaw — Stop all services

echo "=== Stopping HiClaw Services ==="

# Helper: kill process by port
kill_by_port() {
    local port=$1
    local name=$2
    local pids=$(ss -tlnp | grep ":$port " | grep -oP 'pid=\K\d+' | sort -u)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null
        echo "  ✓ Stopped $name (port $port, PID: $(echo $pids | tr '\n' ' '))"
    else
        echo "  - $name not running (port $port)"
    fi
}

kill_by_port 3000 "OpenHands"
kill_by_port 9090 "Worker Manager"
kill_by_port "${HICLAW_GITEA_PORT:-3300}" "Gitea"

sleep 2
echo "Done."
