#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# HiClaw One-Click Setup (No sudo required)
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage:
#   1. git clone -b test https://github.com/yizeng1100-dot/hiclaw.git && cd hiclaw
#   2. Put these files in deploy/ directory:
#      - hiclaw-runtime.tar.gz  (478MB) — App Server: Python 3.12 + all deps
#      - hiclaw-deps.tar.gz     (283MB) — Remote terminal deps + Gitea
#   3. bash deploy/setup.sh
#   4. bash deploy/start.sh
#
# All files installed to $HICLAW_DIR (default: ~/.hiclaw), NO sudo needed.
# ═══════════════════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HICLAW_DIR="${HICLAW_DIR:-$HOME/.hiclaw}"
GITEA_PORT="${HICLAW_GITEA_PORT:-3300}"
GITEA_USER="${HICLAW_GITEA_USER:-hiclaw-admin}"
GITEA_PASS="${HICLAW_GITEA_PASSWORD:-HiClaw2026!}"
MANAGER_DIR="$PROJECT_DIR/agent-worker-manager"

echo "=== HiClaw Setup ==="
echo "  Install dir: $HICLAW_DIR"
echo "  Project dir: $PROJECT_DIR"
echo ""

mkdir -p "$HICLAW_DIR"

# ─── 0. Python Runtime ───
RUNTIME_BUNDLE="$SCRIPT_DIR/hiclaw-runtime.tar.gz"
RUNTIME_DIR="$HICLAW_DIR/runtime"

if [ -f "$RUNTIME_DIR/hiclaw-python" ]; then
    echo "[0/5] Runtime already installed"
    echo "  Python: $($RUNTIME_DIR/hiclaw-python --version 2>&1)"
elif [ -f "$RUNTIME_BUNDLE" ]; then
    echo "[0/5] Installing self-contained runtime..."
    mkdir -p "$RUNTIME_DIR"
    tar xzf "$RUNTIME_BUNDLE" -C "$RUNTIME_DIR"
    # No path fixing needed — uses PYTHONPATH, no venv, no absolute paths
    echo "  Python: $($RUNTIME_DIR/hiclaw-python --version 2>&1)"
    echo "  Verify: $($RUNTIME_DIR/hiclaw-python -c 'import uvicorn,socketio,browsergym;print("All imports OK")' 2>&1)"
else
    echo "[0/5] ERROR: hiclaw-runtime.tar.gz not found in $SCRIPT_DIR/"
    echo "  This file contains Python 3.12 + all dependencies."
    echo "  Place it in the deploy/ directory and re-run setup."
    exit 1
fi

# Set PATH for rest of setup
PYTHON="$RUNTIME_DIR/bin/hiclaw-python"
export LD_LIBRARY_PATH="$RUNTIME_DIR/python/lib:$LD_LIBRARY_PATH"
export PATH="$RUNTIME_DIR/venv/bin:$RUNTIME_DIR/bin:$PATH"

# ─── 1. Skills Git Repo ───
echo "[1/5] Setting up Skills Git repo..."
if [ ! -d "$HICLAW_DIR/skills-repo.git" ]; then
    git init --bare "$HICLAW_DIR/skills-repo.git"
    TMPDIR=$(mktemp -d)
    if git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills"; then
        cd "$TMPDIR/skills"
        git config user.email "hiclaw@system"
        git config user.name "HiClaw"
        cp -r "$SCRIPT_DIR/skills-init/"* .
        git add -A
        git commit -m "init: add default skills"
        git push origin master
        cd "$PROJECT_DIR"
        echo "  Skills repo initialized"
    else
        echo "  Warning: Failed to clone skills repo"
    fi
    rm -rf "$TMPDIR"
else
    echo "  Skills repo already exists"
fi

# ─── 2. Gitea ───
echo "[2/5] Setting up Gitea..."
GITEA_BIN="$HICLAW_DIR/bin/gitea"

# Extract deps bundle (Gitea + remote terminal deps)
DEPS_BUNDLE="$SCRIPT_DIR/hiclaw-deps.tar.gz"
if [ -f "$DEPS_BUNDLE" ] && { [ ! -f "$GITEA_BIN" ] || [ ! -d "$MANAGER_DIR/deps/wheels" ]; }; then
    echo "  Extracting deps bundle..."
    DEPS_TMP=$(mktemp -d)
    tar xzf "$DEPS_BUNDLE" -C "$DEPS_TMP"
    # Gitea binary
    if [ ! -f "$GITEA_BIN" ] && [ -f "$DEPS_TMP/gitea" ]; then
        mkdir -p "$HICLAW_DIR/bin"
        mv "$DEPS_TMP/gitea" "$GITEA_BIN"
        chmod +x "$GITEA_BIN"
    fi
    # Remote terminal deps (wheels, code-server, python standalone)
    if [ -d "$DEPS_TMP/agent-deps" ]; then
        mkdir -p "$MANAGER_DIR/deps"
        cp "$DEPS_TMP/agent-deps/"* "$MANAGER_DIR/deps/" 2>/dev/null || true
        if [ -f "$MANAGER_DIR/deps/wheels.tar.gz" ]; then
            tar xzf "$MANAGER_DIR/deps/wheels.tar.gz" -C "$MANAGER_DIR/deps/"
            rm -f "$MANAGER_DIR/deps/wheels.tar.gz"
        fi
    fi
    rm -rf "$DEPS_TMP"
fi

if [ ! -f "$GITEA_BIN" ]; then
    echo "  Downloading Gitea..."
    mkdir -p "$HICLAW_DIR/bin"
    RELEASE_URL="https://github.com/yizeng1100-dot/hiclaw/releases/download/deps-v1"
    curl -fSL "$RELEASE_URL/gitea" -o "$GITEA_BIN" 2>/dev/null || \
    curl -fSL "https://dl.gitea.com/gitea/1.22.6/gitea-1.22.6-linux-amd64" -o "$GITEA_BIN"
    chmod +x "$GITEA_BIN"
fi

# Gitea config
mkdir -p "$HICLAW_DIR/gitea/custom/conf" "$HICLAW_DIR/gitea/data" "$HICLAW_DIR/gitea/repos" "$HICLAW_DIR/gitea/log"
GITEA_TEMPLATE="$SCRIPT_DIR/gitea-config/app.ini.template"
if [ -f "$GITEA_TEMPLATE" ]; then
    sed -e "s|__USER__|$(whoami)|g" \
        -e "s|__HICLAW_DIR__|$HICLAW_DIR|g" \
        -e "s|__GITEA_PORT__|$GITEA_PORT|g" \
        -e "s|__APP_PORT__|${HICLAW_APP_PORT:-3000}|g" \
        "$GITEA_TEMPLATE" > "$HICLAW_DIR/gitea/custom/conf/app.ini"
fi

# Fix SSH dir (Gitea needs it)
mkdir -p ~/.ssh 2>/dev/null && touch ~/.ssh/authorized_keys 2>/dev/null || true

# Create admin user if DB doesn't exist
if [ ! -f "$HICLAW_DIR/gitea/data/gitea.db" ]; then
    echo "  Creating Gitea admin user..."
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" admin user create \
        --username "$GITEA_USER" --password "$GITEA_PASS" \
        --email admin@hiclaw.local --admin \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" 2>/dev/null || true
fi
echo "  Gitea ready ($GITEA_USER / $GITEA_PASS)"

# ─── 3. Worker Manager deps ───
echo "[3/5] Setting up Worker Manager..."
if [ ! -d "$MANAGER_DIR/deps/wheels" ] && [ ! -f "$MANAGER_DIR/deps/code-server.tar.gz" ]; then
    echo "  No agent deps found. Remote terminal offline install may not work."
    echo "  (Will use online install if remote has internet)"
fi
echo "  Worker Manager ready"

# ─── 4. Push skills to Gitea ───
echo "[4/5] Syncing skills to Gitea..."
GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" web \
    --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
    > "$HICLAW_DIR/gitea/log/startup.log" 2>&1 &
GITEA_PID=$!
sleep 15

curl -s -X POST "http://localhost:$GITEA_PORT/api/v1/user/repos" \
    -H "Content-Type: application/json" \
    -u "$GITEA_USER:$GITEA_PASS" \
    -d '{"name":"skills","description":"HiClaw Skills Repository","default_branch":"master","auto_init":false}' >/dev/null 2>&1 || true

TMPDIR=$(mktemp -d)
if git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills" 2>/dev/null; then
    cd "$TMPDIR/skills"
    git remote add gitea "http://$GITEA_USER:$GITEA_PASS@localhost:$GITEA_PORT/$GITEA_USER/skills.git" 2>/dev/null || true
    git push gitea master --force 2>/dev/null || true
    cd "$PROJECT_DIR"
    echo "  Skills synced to Gitea"
else
    echo "  Warning: Could not clone skills repo, skipping Gitea sync"
fi
rm -rf "$TMPDIR"

kill $GITEA_PID 2>/dev/null
wait $GITEA_PID 2>/dev/null || true

# ─── 5. Build frontend ───
echo "[5/5] Building frontend..."
if [ -d "$PROJECT_DIR/frontend" ] && command -v npm &>/dev/null; then
    cd "$PROJECT_DIR/frontend"
    npm install --silent 2>/dev/null || true
    npm run build 2>/dev/null || echo "  Warning: frontend build failed (need Node.js)"
    cd "$PROJECT_DIR"
else
    echo "  Skipped (no Node.js or no frontend dir)"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "  Install dir:  $HICLAW_DIR"
echo "  Runtime:      $RUNTIME_DIR/bin/hiclaw-python"
echo "  Gitea:        $HICLAW_DIR/bin/gitea"
echo "  Skills repo:  $HICLAW_DIR/skills-repo.git"
echo ""
echo "To start:  bash deploy/start.sh"
echo "To stop:   bash deploy/stop.sh"
