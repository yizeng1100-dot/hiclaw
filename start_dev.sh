#!/bin/bash
# HiClaw dev startup script
cd "$(dirname "$0")"

export OH_SECRET_KEY="069711e0f91f41879c0db3643637eb31470f846f86f03ddcd275176dde6ebb40"
export SANDBOX_VOLUMES="$HOME/.openhands/sandbox-data:/workspace/conversations:rw,$HOME/workspace/OpenHands/custom:/workspace/custom:ro,$HOME/workspace/test_traces:/workspace/test_traces:ro"

case "${1:-}" in
  stop)
    pkill -f "uvicorn openhands.server.listen" 2>/dev/null && echo "Backend stopped" || echo "Backend not running"
    ;;
  backend)
    echo "Starting backend on port 12000..."
    nohup .venv/bin/uvicorn openhands.server.listen:app --host 0.0.0.0 --port 12000 > /tmp/openhands-12000.log 2>&1 &
    echo "PID: $!"
    ;;
  frontend)
    echo "Starting frontend on port 12001..."
    cd frontend
    VITE_BACKEND_HOST="127.0.0.1:12000" VITE_FRONTEND_PORT="12001" npx react-router dev
    ;;
  *)
    echo "Starting backend on port 12000..."
    nohup .venv/bin/uvicorn openhands.server.listen:app --host 0.0.0.0 --port 12000 > /tmp/openhands-12000.log 2>&1 &
    echo "Backend PID: $!"
    sleep 2
    echo "Starting frontend on port 12001..."
    cd frontend
    VITE_BACKEND_HOST="127.0.0.1:12000" VITE_FRONTEND_PORT="12001" nohup npx react-router dev > /tmp/openhands-frontend-12001.log 2>&1 &
    echo "Frontend PID: $!"
    echo "Backend: http://127.0.0.1:12000  Frontend: http://127.0.0.1:12001"
    ;;
esac
