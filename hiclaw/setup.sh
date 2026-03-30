#!/bin/bash
# HiClaw One-Click Setup
#
# Usage:
#   1. git clone -b test https://github.com/yizeng1100-dot/hiclaw.git && cd hiclaw
#   2. Put hiclaw-deps.tar.gz in hiclaw/ directory (same level as this script)
#   3. bash hiclaw/setup.sh
#   4. bash hiclaw/start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HICLAW_DIR="/opt/hiclaw"
GITEA_PORT="${HICLAW_GITEA_PORT:-3300}"
GITEA_USER="${HICLAW_GITEA_USER:-hiclaw-admin}"
GITEA_PASS="${HICLAW_GITEA_PASSWORD:-HiClaw2026!}"
DEPS_BUNDLE="$SCRIPT_DIR/hiclaw-deps.tar.gz"
PYTHON_ENV_BUNDLE="$SCRIPT_DIR/hiclaw-python-env.tar.gz"
MANAGER_DIR="$SCRIPT_DIR/agent-worker-manager"

echo "=== HiClaw Setup ==="
echo "Project: $PROJECT_DIR"
echo ""

# ─── 0. Offline Python environment (if bundle exists) ───
if [ -f "$PYTHON_ENV_BUNDLE" ]; then
    echo "[0] Found Python environment bundle, installing offline..."
    PYENV_TMP=$(mktemp -d)
    tar xzf "$PYTHON_ENV_BUNDLE" -C "$PYENV_TMP"

    # Install Python standalone if system doesn't have 3.12
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3,12) else 1)" 2>/dev/null; then
        if [ -f "$PYENV_TMP/python3-standalone.tar.gz" ]; then
            echo "  Installing Python 3.12 standalone..."
            tar xzf "$PYENV_TMP/python3-standalone.tar.gz" -C /usr/local/
            ln -sf /usr/local/python/bin/python3.12 /usr/local/bin/python3.12
            ln -sf /usr/local/python/bin/python3.12 /usr/local/bin/python3
            ln -sf /usr/local/python/bin/pip3.12 /usr/local/bin/pip3
        fi
    fi

    # Create venv and install all deps offline
    echo "  Creating venv and installing packages offline (380+ packages)..."
    python3 -m venv "$HICLAW_DIR/venv" 2>/dev/null || python3.12 -m venv "$HICLAW_DIR/venv"
    "$HICLAW_DIR/venv/bin/pip" install --no-index \
        --find-links "$PYENV_TMP/wheels/" \
        -r "$PYENV_TMP/requirements-clean.txt" 2>&1 | tail -3

    # Make the venv available for poetry
    echo "  Python env installed: $("$HICLAW_DIR/venv/bin/python" --version), $(ls $PYENV_TMP/wheels/ | wc -l) packages"
    export PATH=""$HICLAW_DIR/venv/bin":$PATH"

    rm -rf "$PYENV_TMP"
    echo ""
fi

# ─── Prerequisites check ───
echo "[Pre] Checking prerequisites..."
MISSING=""

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "  ✗ $1 not found"
        MISSING="$MISSING $1"
    else
        echo "  ✓ $1 ($($1 --version 2>&1 | head -1))"
    fi
}

check_cmd python3
check_cmd pip3
check_cmd git
check_cmd node
check_cmd npm

# Check Python version >= 3.12
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if python3 -c "import sys; exit(0 if sys.version_info >= (3,12) else 1)" 2>/dev/null; then
        echo "  ✓ Python version $PY_VER (>= 3.12)"
    else
        echo "  ✗ Python $PY_VER too old, need >= 3.12"
        MISSING="$MISSING python3.12"
    fi
fi

if [ -n "$MISSING" ]; then
    echo ""
    echo "Missing dependencies:$MISSING"
    echo ""
    echo "Install on Ubuntu/Debian:"
    echo "  sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3-pip git nodejs npm"
    echo "  pip3 install poetry"
    echo ""
    read -p "Try to install automatically? [y/N] " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        echo "Installing..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3.12 python3.12-venv python3-pip git 2>/dev/null || true
        # Node.js via NodeSource if not available
        if ! command -v node &>/dev/null; then
            curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - 2>/dev/null
            sudo apt-get install -y -qq nodejs 2>/dev/null || true
        fi
        pip3 install poetry 2>/dev/null || true
        echo "Dependencies installed. Re-checking..."
        for cmd in python3 pip3 git node npm; do
            if command -v "$cmd" &>/dev/null; then
                echo "  ✓ $cmd"
            else
                echo "  ✗ $cmd still missing — please install manually"
                exit 1
            fi
        done
    else
        echo "Please install the missing dependencies and re-run setup."
        exit 1
    fi
fi

echo ""

# ─── 0. Extract deps bundle ───
if [ -f "$DEPS_BUNDLE" ]; then
    echo "[0/5] Extracting deps bundle..."
    DEPS_TMP=$(mktemp -d)
    tar xzf "$DEPS_BUNDLE" -C "$DEPS_TMP"

    # Install Gitea
    if [ -f "$DEPS_TMP/gitea" ] && ! command -v gitea &>/dev/null; then
        echo "  Installing Gitea from bundle..."
        chmod +x "$DEPS_TMP/gitea"
        sudo mv "$DEPS_TMP/gitea" /usr/local/bin/gitea
    fi

    # Setup agent deps
    if [ -d "$DEPS_TMP/agent-deps" ]; then
        echo "  Setting up agent deps..."
        mkdir -p "$MANAGER_DIR/deps"
        cp "$DEPS_TMP/agent-deps/code-server.tar.gz" "$MANAGER_DIR/deps/" 2>/dev/null || true
        cp "$DEPS_TMP/agent-deps/python3-standalone.tar.gz" "$MANAGER_DIR/deps/" 2>/dev/null || true
        if [ -f "$DEPS_TMP/agent-deps/wheels.tar.gz" ]; then
            tar xzf "$DEPS_TMP/agent-deps/wheels.tar.gz" -C "$MANAGER_DIR/deps/"
        fi
    fi

    rm -rf "$DEPS_TMP"
    echo "  Deps extracted"
else
    echo "[0/5] No deps bundle found at $DEPS_BUNDLE"
    echo "  Will try to download from internet..."
fi

# ─── 1. Skills Git Repo ───
echo "[1/5] Setting up Skills Git repo..."
sudo mkdir -p "$HICLAW_DIR"
sudo chown "$(whoami)" "$HICLAW_DIR"

if [ ! -d "$HICLAW_DIR/skills-repo.git" ]; then
    git init --bare "$HICLAW_DIR/skills-repo.git"
    TMPDIR=$(mktemp -d)
    git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills"
    cd "$TMPDIR/skills"
    git config user.email "hiclaw@system"
    git config user.name "HiClaw"
    cp -r "$SCRIPT_DIR/skills-init/"* .
    git add -A
    git commit -m "init: add default skills"
    git push origin master
    cd "$PROJECT_DIR"
    rm -rf "$TMPDIR"
    echo "  Skills repo initialized"
else
    echo "  Skills repo already exists"
fi

# ─── 2. Gitea ───
RELEASE_URL="https://github.com/yizeng1100-dot/hiclaw/releases/download/deps-v1"

echo "[2/5] Setting up Gitea..."
if ! command -v gitea &>/dev/null; then
    echo "  Downloading Gitea..."
    curl -fSL "$RELEASE_URL/gitea" -o /tmp/gitea 2>/dev/null || \
    wget -q -O /tmp/gitea https://dl.gitea.com/gitea/1.22.6/gitea-1.22.6-linux-amd64
    chmod +x /tmp/gitea
    sudo mv /tmp/gitea /usr/local/bin/gitea
fi

mkdir -p "$HICLAW_DIR/gitea/custom/conf" "$HICLAW_DIR/gitea/data" "$HICLAW_DIR/gitea/repos" "$HICLAW_DIR/gitea/log"

# Fix SSH dir permissions (Gitea needs this)
mkdir -p ~/.ssh 2>/dev/null && touch ~/.ssh/authorized_keys 2>/dev/null || true

cp "$SCRIPT_DIR/gitea-config/app.ini" "$HICLAW_DIR/gitea/custom/conf/app.ini"

if [ ! -f "$HICLAW_DIR/gitea/data/gitea.db" ]; then
    echo "  Creating Gitea admin user..."
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" gitea admin user create \
        --username "$GITEA_USER" --password "$GITEA_PASS" \
        --email admin@hiclaw.local --admin \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" 2>/dev/null || true
fi
echo "  Gitea ready (login: $GITEA_USER / $GITEA_PASS)"

# ─── 3. Worker Manager deps ───
echo "[3/5] Setting up Worker Manager..."
if [ ! -d "$MANAGER_DIR/deps/wheels" ] && [ ! -f "$MANAGER_DIR/deps/code-server.tar.gz" ]; then
    echo "  No deps found, downloading..."
    mkdir -p "$MANAGER_DIR/deps"
    for f in code-server.tar.gz python3-standalone.tar.gz; do
        curl -fSL "$RELEASE_URL/$f" -o "$MANAGER_DIR/deps/$f" 2>/dev/null || \
        echo "  Warning: failed to download $f"
    done
    if [ ! -d "$MANAGER_DIR/deps/wheels" ]; then
        pip download openhands-agent-server==1.14 openhands-sdk==1.14 openhands-tools==1.14 \
            --dest "$MANAGER_DIR/deps/wheels/" 2>/dev/null || echo "  Warning: wheel download failed"
    fi
else
    echo "  Deps already present"
fi

pip install -q asyncssh httpx fastapi uvicorn pydantic sse-starlette aiosqlite 2>/dev/null || true
echo "  Worker Manager ready"

# ─── 4. Push skills to Gitea ───
echo "[4/5] Syncing skills to Gitea..."
GITEA_WORK_DIR="$HICLAW_DIR/gitea" gitea web \
    --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
    > "$HICLAW_DIR/gitea/log/startup.log" 2>&1 &
GITEA_PID=$!
sleep 15

curl -s -X POST http://localhost:$GITEA_PORT/api/v1/user/repos \
    -H "Content-Type: application/json" \
    -u "$GITEA_USER:$GITEA_PASS" \
    -d '{"name":"skills","description":"HiClaw Skills Repository","default_branch":"master","auto_init":false}' >/dev/null 2>&1 || true

TMPDIR=$(mktemp -d)
git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills" 2>/dev/null
cd "$TMPDIR/skills"
git remote add gitea "http://$GITEA_USER:$GITEA_PASS@localhost:$GITEA_PORT/$GITEA_USER/skills.git" 2>/dev/null || true
git push gitea master --force 2>/dev/null || true
cd "$PROJECT_DIR"
rm -rf "$TMPDIR"

kill $GITEA_PID 2>/dev/null
wait $GITEA_PID 2>/dev/null || true
echo "  Skills synced to Gitea"

# ─── 5. Build frontend ───
echo "[5/5] Building frontend..."
if [ -d "$PROJECT_DIR/frontend" ]; then
    cd "$PROJECT_DIR/frontend"
    npm install --silent 2>/dev/null || true
    npm run build 2>/dev/null || echo "  Warning: frontend build failed"
    cd "$PROJECT_DIR"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start:  bash hiclaw/start.sh"
echo "To stop:   bash hiclaw/stop.sh"
echo ""
echo "Services:"
echo "  OpenHands  http://localhost:3000"
echo "  Gitea      http://localhost:$GITEA_PORT  ($GITEA_USER / $GITEA_PASS)"
echo "  Manager    http://localhost:${HICLAW_MANAGER_PORT:-9090}"
