#!/bin/bash
# HiClaw — Stop all services
echo "=== Stopping HiClaw Services ==="

echo "Stopping OpenHands..."
pkill -f "uvicorn openhands.server.listen" 2>/dev/null || true

echo "Stopping Worker Manager..."
pkill -f "run.py" 2>/dev/null || true

echo "Stopping Gitea..."
pkill -f "gitea web" 2>/dev/null || true

sleep 2
echo "All services stopped."
