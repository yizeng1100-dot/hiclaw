#!/bin/bash
# HiClaw One-Click Setup
# Usage: bash hiclaw/setup.sh
#
# This script sets up all HiClaw services:
# 1. Skills Git repo (/opt/hiclaw/skills-repo.git)
# 2. Gitea instance (/opt/hiclaw/gitea, port 3300)
# 3. Worker Manager (port 9090)
# 4. OpenHands App Server (port 3000)
#
# Prerequisites: Python 3.12+, pip, git

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HICLAW_DIR="/opt/hiclaw"

echo "=== HiClaw Setup ==="
echo "Project: $PROJECT_DIR"
echo "HiClaw data: $HICLAW_DIR"
echo ""

# ─── 1. Skills Git Repo ───
echo "[1/5] Setting up Skills Git repo..."
sudo mkdir -p "$HICLAW_DIR"
sudo chown "$(whoami)" "$HICLAW_DIR"

if [ ! -d "$HICLAW_DIR/skills-repo.git" ]; then
    git init --bare "$HICLAW_DIR/skills-repo.git"
    # Push initial skills
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
    echo "  Skills repo initialized with $(find "$SCRIPT_DIR/skills-init" -name SKILL.md | wc -l) skills"
else
    echo "  Skills repo already exists"
fi

# ─── 2. Gitea ───
RELEASE_URL="https://github.com/yizeng1100-dot/hiclaw/releases/download/deps-v1"

echo "[2/5] Setting up Gitea..."
if ! command -v gitea &>/dev/null; then
    echo "  Installing Gitea (from GitHub Release)..."
    curl -fSL "$RELEASE_URL/gitea" -o /tmp/gitea || \
    wget -q -O /tmp/gitea https://dl.gitea.com/gitea/1.22.6/gitea-1.22.6-linux-amd64
    chmod +x /tmp/gitea
    sudo mv /tmp/gitea /usr/local/bin/gitea
fi

mkdir -p "$HICLAW_DIR/gitea/custom/conf" "$HICLAW_DIR/gitea/data" "$HICLAW_DIR/gitea/repos" "$HICLAW_DIR/gitea/log"
cp "$SCRIPT_DIR/gitea-config/app.ini" "$HICLAW_DIR/gitea/custom/conf/app.ini"

# Create admin user if DB doesn't exist
if [ ! -f "$HICLAW_DIR/gitea/data/gitea.db" ]; then
    echo "  Creating Gitea admin user..."
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" gitea admin user create \
        --username hiclaw-admin --password HiClaw2026! \
        --email admin@hiclaw.local --admin \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" 2>/dev/null || true
fi
echo "  Gitea configured (port 3300, login: hiclaw-admin / HiClaw2026!)"

# ─── 3. Worker Manager deps ───
echo "[3/5] Setting up Worker Manager dependencies..."
MANAGER_DIR="$SCRIPT_DIR/agent-worker-manager"
if [ ! -d "$MANAGER_DIR/deps/wheels" ]; then
    echo "  Building offline dependency bundle..."
    mkdir -p "$MANAGER_DIR/deps"
    # Download from GitHub Release
    for f in code-server.tar.gz python3-standalone.tar.gz; do
        if [ ! -f "$MANAGER_DIR/deps/$f" ]; then
            echo "  Downloading $f from GitHub Release..."
            curl -fSL "$RELEASE_URL/$f" -o "$MANAGER_DIR/deps/$f" 2>/dev/null || echo "  Warning: $f not available, offline deploy may fail"
        fi
    done
    # Build wheels
    if [ ! -d "$MANAGER_DIR/deps/wheels" ]; then
        echo "  Downloading Python wheels..."
        pip download openhands-agent-server==1.14 openhands-sdk==1.14 openhands-tools==1.14 \
            --dest "$MANAGER_DIR/deps/wheels/" 2>/dev/null || echo "  Warning: wheel download failed"
    fi
fi

# Install manager Python deps
pip install -q asyncssh httpx fastapi uvicorn pydantic sse-starlette 2>/dev/null || true
echo "  Worker Manager ready"

# ─── 4. Push skills to Gitea ───
echo "[4/5] Syncing skills to Gitea..."
# Start Gitea temporarily
GITEA_WORK_DIR="$HICLAW_DIR/gitea" gitea web --config "$HICLAW_DIR/gitea/custom/conf/app.ini" &
GITEA_PID=$!
sleep 10

# Create repo and push skills
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

# Keep Gitea running (will be managed by start.sh)
echo "  Skills synced to Gitea"

# ─── 5. Summary ───
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Services:"
echo "  Gitea (Skills UI):     http://localhost:3300  (hiclaw-admin / HiClaw2026!)"
echo "  Worker Manager:        http://localhost:9090"
echo "  OpenHands App Server:  http://localhost:3000"
echo ""
echo "To start all services:"
echo "  bash hiclaw/start.sh"
echo ""
echo "To stop all services:"
echo "  bash hiclaw/stop.sh"

# Stop the temp Gitea
kill $GITEA_PID 2>/dev/null
