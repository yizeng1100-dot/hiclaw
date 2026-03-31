#!/bin/bash
# HiClaw — Stop all services
echo "=== Stopping HiClaw Services ==="
pkill -f "uvicorn openhands.server.listen" 2>/dev/null && echo "  Stopped OpenHands" || echo "  OpenHands not running"
pkill -f "run.py.*manager" 2>/dev/null || pkill -f "agent-worker-manager" 2>/dev/null && echo "  Stopped Worker Manager" || echo "  Worker Manager not running"
pkill -f "gitea web" 2>/dev/null && echo "  Stopped Gitea" || echo "  Gitea not running"
sleep 2
echo "Done."
