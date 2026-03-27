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
DEPS_BUNDLE="$SCRIPT_DIR/hiclaw-deps.tar.gz"
MANAGER_DIR="$SCRIPT_DIR/agent-worker-manager"

echo "=== HiClaw Setup ==="
echo "Project: $PROJECT_DIR"
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
        --username hiclaw-admin --password HiClaw2026! \
        --email admin@hiclaw.local --admin \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" 2>/dev/null || true
fi
echo "  Gitea ready (login: hiclaw-admin / HiClaw2026!)"

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

curl -s -X POST http://localhost:3300/api/v1/user/repos \
    -H "Content-Type: application/json" \
    -u "hiclaw-admin:HiClaw2026!" \
    -d '{"name":"skills","description":"HiClaw Skills Repository","default_branch":"master","auto_init":false}' >/dev/null 2>&1 || true

TMPDIR=$(mktemp -d)
git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills" 2>/dev/null
cd "$TMPDIR/skills"
git remote add gitea "http://hiclaw-admin:HiClaw2026!@localhost:3300/hiclaw-admin/skills.git" 2>/dev/null || true
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
echo "  Gitea      http://localhost:3300  (hiclaw-admin / HiClaw2026!)"
echo "  Manager    http://localhost:9090"
