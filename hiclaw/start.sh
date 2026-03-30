#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# HiClaw — Start all services
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage: bash hiclaw/start.sh
#
# ─── Architecture ───
#
#   App Server (本机)                         远程终端 (用户的计算云)
#   ┌─────────────────────────┐              ┌─────────────────────────┐
#   │ OpenHands    :3000      │  SSH tunnel  │ agent-server   :8000    │
#   │ Worker Mgr   :9090      │ ──────────►  │ code-server    :8443    │
#   │ Gitea        :3300      │              │                         │
#   └─────────────────────────┘              └─────────────────────────┘
#
# ─── Python 环境 ───
#
#   App Server:
#     venv: /opt/hiclaw/venv/  (由 setup.sh + hiclaw-python-env.tar.gz 离线安装)
#     包:   380+ 个 (OpenHands 全套 + Worker Manager 依赖)
#     来源: hiclaw-python-env.tar.gz → wheels/ → pip install --no-index
#
#   远程终端:
#     venv: /opt/agent-venv/  (由 Provisioner 自动安装)
#     包:   180+ 个 (openhands-agent-server + SDK + tools)
#     来源: 有网 → pip install from aliyun mirror
#           没网 → hiclaw-deps.tar.gz 内的 wheels.tar.gz → pip install --no-index
#
# ─── 离线部署包 ───
#
#   hiclaw-python-env.tar.gz (380MB) → App Server 用
#     ├── python3-standalone.tar.gz   (20MB)  Python 3.12
#     ├── wheels/ (380 files)         (368MB) 所有 pip 依赖
#     ├── requirements-clean.txt              包列表
#     └── install.sh                          一键安装脚本
#
#   hiclaw-deps.tar.gz (283MB) → 远程终端 + Gitea 用
#     ├── gitea                       (143MB) Gitea 二进制
#     ├── agent-deps/wheels.tar.gz    (95MB)  agent-server SDK wheels
#     ├── agent-deps/code-server.tar.gz(105MB) VS Code
#     └── agent-deps/python3-standalone(20MB) Python 3.12 (远程没 Python 时)
#
# ─── 日志位置 ───
#
#   App Server:
#     ~/openhands.log                    OpenHands 主服务 (会话创建/API)
#     /tmp/manager.log                   Worker Manager (SSH/隧道/provisioning)
#     /opt/hiclaw/gitea/log/gitea.log    Gitea (skill 管理 UI)
#
#   远程终端:
#     /tmp/agent-server-{id}.log         agent-server (LLM 调用/工具执行/错误)
#     {workspace}/logs/completions/      LLM 原始 request/response JSON
#     {workspace}/workspace/conversations/  会话事件历史
#
# ─── 环境变量 ───
#
#   HICLAW_DIR          数据目录           默认: /opt/hiclaw
#   HICLAW_GITEA_PORT   Gitea 端口         默认: 3300
#   HICLAW_MANAGER_PORT Worker Manager 端口 默认: 9090
#   HICLAW_APP_PORT     OpenHands 端口      默认: 3000
#   HICLAW_APP_IP       App Server IP      默认: 自动检测 (内网必须手动设)
#   HICLAW_GITEA_USER   Gitea 管理员       默认: hiclaw-admin
#   HICLAW_GITEA_PASSWORD Gitea 密码       默认: HiClaw2026!
#   HICLAW_LLM_DEBUG    LLM debug 日志     默认: 关闭 (设为1开启)
#
# ═══════════════════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HICLAW_DIR="${HICLAW_DIR:-/opt/hiclaw}"
GITEA_PORT="${HICLAW_GITEA_PORT:-3300}"
MANAGER_PORT="${HICLAW_MANAGER_PORT:-9090}"
APP_PORT="${HICLAW_APP_PORT:-3000}"
GITEA_USER="${HICLAW_GITEA_USER:-hiclaw-admin}"
GITEA_PASS="${HICLAW_GITEA_PASSWORD:-HiClaw2026!}"
MANAGER_DIR="$SCRIPT_DIR/agent-worker-manager"

# ─── Python 环境 (统一使用 /opt/hiclaw/venv/) ───
VENV_DIR="$HICLAW_DIR/venv"
if [ ! -d "$VENV_DIR/bin" ]; then
    echo "ERROR: Python venv not found at $VENV_DIR/"
    echo "Run 'bash hiclaw/setup.sh' first to install Python environment."
    exit 1
fi
PYTHON="$VENV_DIR/bin/python3"
UVICORN="$VENV_DIR/bin/uvicorn"
export PATH="$VENV_DIR/bin:$PATH"

echo "=== Starting HiClaw Services ==="
echo "  Python: $($PYTHON --version)"
echo "  Data:   $HICLAW_DIR"
echo ""

# 1. Gitea (Skills 管理 UI)
if ! ss -tlnp | grep -q ":$GITEA_PORT "; then
    echo "[1/3] Starting Gitea (port $GITEA_PORT)..."
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" gitea web \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
        > "$HICLAW_DIR/gitea/log/startup.log" 2>&1 &
    disown
    sleep 5
else
    echo "[1/3] Gitea already running (port $GITEA_PORT)"
fi

# 2. Worker Manager (SSH 连接/隧道/Provisioning)
if ! ss -tlnp | grep -q ":$MANAGER_PORT "; then
    echo "[2/3] Starting Worker Manager (port $MANAGER_PORT)..."
    cd "$MANAGER_DIR" && $PYTHON run.py > /tmp/manager.log 2>&1 &
    disown
    cd "$PROJECT_DIR"
    sleep 2
else
    echo "[2/3] Worker Manager already running (port $MANAGER_PORT)"
fi

# 3. OpenHands App Server (主服务)
if ! ss -tlnp | grep -q ":$APP_PORT "; then
    echo "[3/3] Starting OpenHands App Server (port $APP_PORT)..."
    cd "$PROJECT_DIR" && $UVICORN openhands.server.listen:app \
        --host 0.0.0.0 --port $APP_PORT \
        > ~/openhands.log 2>&1 &
    disown
    cd "$PROJECT_DIR"
else
    echo "[3/3] OpenHands already running (port $APP_PORT)"
fi

# ─── 等待并验证 ───
echo ""
echo "Waiting for services to start..."
sleep 15

echo ""
echo "=== Service Status ==="
for port_name in "$APP_PORT:OpenHands" "$GITEA_PORT:Gitea" "$MANAGER_PORT:WorkerManager"; do
    port="${port_name%%:*}"
    name="${port_name##*:}"
    if ss -tlnp | grep -q ":$port "; then
        echo "  ✓ $name (port $port)"
    else
        echo "  ✗ $name (port $port) — NOT RUNNING, check logs"
    fi
done

echo ""
echo "=== URLs ==="
echo "  App:    http://localhost:$APP_PORT"
echo "  Skills: http://localhost:$APP_PORT/skill-management"
echo "  Gitea:  http://localhost:$GITEA_PORT ($GITEA_USER / $GITEA_PASS)"
echo ""
echo "=== Logs ==="
echo "  App Server:     tail -f ~/openhands.log"
echo "  Worker Manager: tail -f /tmp/manager.log"
echo "  Gitea:          tail -f $HICLAW_DIR/gitea/log/gitea.log"
echo "  Agent Server:   ssh <remote> 'tail -f /tmp/agent-server-*.log'"
