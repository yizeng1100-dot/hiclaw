#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# HiClaw One-Click Setup (No sudo required)
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage:
#   1. git clone -b test https://github.com/yizeng1100-dot/hiclaw.git && cd hiclaw
#   2. Put these files in deploy/ directory:
#      - hiclaw-runtime.tar.gz  — App Server: Python 3.12 + all deps
#      - hiclaw-deps.tar.gz     — Remote terminal deps + Gitea
#   3. bash deploy/setup.sh
#   4. bash deploy/start.sh pro
#
# All files installed to $HICLAW_DIR (default: ~/.hiclaw), NO sudo needed.
# ═══════════════════════════════════════════════════════════════════════════

# NO set -e — we handle errors explicitly with logging
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HICLAW_DIR="${HICLAW_DIR:-$HOME/.hiclaw}"
GITEA_PORT="${HICLAW_GITEA_PORT:-3300}"
GITEA_USER="${HICLAW_GITEA_USER:-hiclaw-admin}"
GITEA_PASS="${HICLAW_GITEA_PASSWORD:-HiClaw2026!}"
MANAGER_DIR="$PROJECT_DIR/agent-worker-manager"
RUNTIME_DIR="$HICLAW_DIR/runtime"

log()  { echo "  $*"; }
ok()   { echo "  ✓ $*"; }
warn() { echo "  ⚠ $*"; }
fail() { echo "  ✗ $*"; }

echo "=== HiClaw Setup ==="
echo "  Install dir: $HICLAW_DIR"
echo "  Project dir: $PROJECT_DIR"
echo ""

mkdir -p "$HICLAW_DIR"

# ═══════════════════════════════════════════════════════════════════════════
# [0/5] Python Runtime
# ═══════════════════════════════════════════════════════════════════════════
echo "[0/5] Python Runtime..."
RUNTIME_BUNDLE="$SCRIPT_DIR/hiclaw-runtime.tar.gz"

if [ -f "$RUNTIME_DIR/hiclaw-python" ]; then
    ok "Already installed: $($RUNTIME_DIR/hiclaw-python --version 2>&1)"
elif [ -f "$RUNTIME_BUNDLE" ]; then
    log "Extracting hiclaw-runtime.tar.gz..."
    mkdir -p "$RUNTIME_DIR"
    if tar xzf "$RUNTIME_BUNDLE" -C "$RUNTIME_DIR"; then
        ok "Extracted"
        log "Testing: $($RUNTIME_DIR/hiclaw-python --version 2>&1)"
        VERIFY="$($RUNTIME_DIR/hiclaw-python -c 'import uvicorn,fastapi;print("OK")' 2>&1)"
        if [ "$VERIFY" = "OK" ]; then
            ok "All imports OK"
        else
            fail "Import test failed: $VERIFY"
        fi
    else
        fail "Failed to extract hiclaw-runtime.tar.gz"
        exit 1
    fi
else
    fail "hiclaw-runtime.tar.gz not found in $SCRIPT_DIR/"
    echo "  Place it in the deploy/ directory and re-run setup."
    exit 1
fi

PYTHON="$RUNTIME_DIR/hiclaw-python"

# ═══════════════════════════════════════════════════════════════════════════
# [1/5] Skills Git Repo
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "[1/5] Skills Git Repo..."

if [ -d "$HICLAW_DIR/skills-repo.git" ]; then
    ok "Already exists"
else
    log "Initializing bare repo..."
    git init --bare "$HICLAW_DIR/skills-repo.git" || { fail "git init --bare failed"; }

    if [ -d "$SCRIPT_DIR/skills-init" ]; then
        log "Populating with initial skills..."
        TMPDIR="$(mktemp -d)"
        if git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills" 2>&1; then
            cd "$TMPDIR/skills"
            git config user.email "hiclaw@system"
            git config user.name "HiClaw"
            cp -r "$SCRIPT_DIR/skills-init/"* . 2>/dev/null
            git add -A
            git commit -m "init: add default skills" 2>&1 || warn "Nothing to commit"
            git push origin master 2>&1 || warn "Push failed"
            cd "$PROJECT_DIR"
            ok "Skills repo initialized"
        else
            warn "Could not clone skills repo"
        fi
        rm -rf "$TMPDIR"
    else
        warn "No skills-init/ directory found, repo is empty"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════
# [2/5] Gitea + Remote Terminal Deps
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "[2/5] Gitea + Agent Deps..."
GITEA_BIN="$HICLAW_DIR/bin/gitea"
DEPS_BUNDLE="$SCRIPT_DIR/hiclaw-deps.tar.gz"

# Extract deps bundle if needed
if [ -f "$DEPS_BUNDLE" ]; then
    NEED_EXTRACT=false
    [ ! -f "$GITEA_BIN" ] && NEED_EXTRACT=true
    [ ! -d "$MANAGER_DIR/deps/wheels" ] && NEED_EXTRACT=true

    if $NEED_EXTRACT; then
        log "Extracting hiclaw-deps.tar.gz..."
        DEPS_TMP="$(mktemp -d)"
        if tar xzf "$DEPS_BUNDLE" -C "$DEPS_TMP"; then
            # Gitea binary
            if [ ! -f "$GITEA_BIN" ] && [ -f "$DEPS_TMP/gitea" ]; then
                mkdir -p "$HICLAW_DIR/bin"
                mv "$DEPS_TMP/gitea" "$GITEA_BIN"
                chmod +x "$GITEA_BIN"
                ok "Gitea binary installed"
            fi
            # Agent deps
            if [ -d "$DEPS_TMP/agent-deps" ]; then
                mkdir -p "$MANAGER_DIR/deps"
                cp "$DEPS_TMP/agent-deps/"* "$MANAGER_DIR/deps/" 2>/dev/null
                if [ -f "$MANAGER_DIR/deps/wheels.tar.gz" ]; then
                    log "Extracting wheels..."
                    tar xzf "$MANAGER_DIR/deps/wheels.tar.gz" -C "$MANAGER_DIR/deps/"
                    rm -f "$MANAGER_DIR/deps/wheels.tar.gz"
                    ok "Agent deps extracted ($(ls "$MANAGER_DIR/deps/wheels/" 2>/dev/null | wc -l) wheels)"
                fi
            else
                warn "No agent-deps/ in bundle"
            fi
        else
            fail "Failed to extract hiclaw-deps.tar.gz"
        fi
        rm -rf "$DEPS_TMP"
    else
        ok "Gitea and agent deps already present"
    fi
else
    warn "hiclaw-deps.tar.gz not found — will try online download"
fi

# Download Gitea if still missing
if [ ! -f "$GITEA_BIN" ]; then
    log "Downloading Gitea..."
    mkdir -p "$HICLAW_DIR/bin"
    RELEASE_URL="https://github.com/yizeng1100-dot/hiclaw/releases/download/deps-v1"
    if curl -fSL "$RELEASE_URL/gitea" -o "$GITEA_BIN" 2>/dev/null; then
        chmod +x "$GITEA_BIN"
        ok "Gitea downloaded"
    elif curl -fSL "https://dl.gitea.com/gitea/1.22.6/gitea-1.22.6-linux-amd64" -o "$GITEA_BIN" 2>/dev/null; then
        chmod +x "$GITEA_BIN"
        ok "Gitea downloaded (fallback)"
    else
        fail "Could not download Gitea"
    fi
fi

# Gitea config
log "Generating Gitea config..."
mkdir -p "$HICLAW_DIR/gitea/custom/conf" "$HICLAW_DIR/gitea/data" "$HICLAW_DIR/gitea/repos" "$HICLAW_DIR/gitea/log"
GITEA_TEMPLATE="$SCRIPT_DIR/gitea-config/app.ini.template"
if [ -f "$GITEA_TEMPLATE" ]; then
    sed -e "s|__USER__|$(whoami)|g" \
        -e "s|__HICLAW_DIR__|$HICLAW_DIR|g" \
        -e "s|__GITEA_PORT__|$GITEA_PORT|g" \
        -e "s|__APP_PORT__|${HICLAW_APP_PORT:-3000}|g" \
        "$GITEA_TEMPLATE" > "$HICLAW_DIR/gitea/custom/conf/app.ini"
    ok "Config generated"
else
    warn "app.ini.template not found"
fi

# SSH dir
mkdir -p ~/.ssh 2>/dev/null; touch ~/.ssh/authorized_keys 2>/dev/null || true

# Create admin user
if [ -f "$GITEA_BIN" ] && [ ! -f "$HICLAW_DIR/gitea/data/gitea.db" ]; then
    log "Creating Gitea admin user..."
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" admin user create \
        --username "$GITEA_USER" --password "$GITEA_PASS" \
        --email admin@hiclaw.local --admin \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" 2>&1 || warn "Admin user creation had issues"
fi
ok "Gitea ready ($GITEA_USER / $GITEA_PASS)"

# ═══════════════════════════════════════════════════════════════════════════
# [3/5] Worker Manager Deps
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "[3/5] Worker Manager..."
if [ -d "$MANAGER_DIR/deps/wheels" ]; then
    ok "Agent deps present ($(ls "$MANAGER_DIR/deps/wheels/" | wc -l) wheels)"
elif [ -f "$MANAGER_DIR/deps/code-server.tar.gz" ]; then
    ok "Agent deps present (code-server only, no wheels)"
else
    warn "No agent deps. Remote offline install won't work (online install OK)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# [4/5] Sync Skills to Gitea
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "[4/5] Syncing skills to Gitea..."

if [ ! -f "$GITEA_BIN" ]; then
    warn "Gitea not installed, skipping sync"
elif [ ! -d "$HICLAW_DIR/skills-repo.git" ]; then
    warn "Skills repo not found, skipping sync"
else
    log "Starting Gitea temporarily..."
    mkdir -p "$HICLAW_DIR/gitea/log"
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" web \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
        > "$HICLAW_DIR/gitea/log/setup-startup.log" 2>&1 &
    GITEA_PID=$!
    log "Waiting for Gitea to start (PID $GITEA_PID)..."
    sleep 15

    # Check if Gitea started
    if curl -s --max-time 3 "http://localhost:$GITEA_PORT" >/dev/null 2>&1; then
        ok "Gitea started"

        # Create repo
        log "Creating skills repo in Gitea..."
        curl -s -X POST "http://localhost:$GITEA_PORT/api/v1/user/repos" \
            -H "Content-Type: application/json" \
            -u "$GITEA_USER:$GITEA_PASS" \
            -d '{"name":"skills","description":"HiClaw Skills Repository","default_branch":"master","auto_init":false}' \
            >/dev/null 2>&1 || true

        # Push skills
        log "Pushing skills..."
        TMPDIR="$(mktemp -d)"
        if git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills" 2>/dev/null; then
            cd "$TMPDIR/skills"
            git remote add gitea "http://$GITEA_USER:$GITEA_PASS@localhost:$GITEA_PORT/$GITEA_USER/skills.git" 2>/dev/null || true
            if git push gitea master --force 2>&1; then
                ok "Skills pushed to Gitea"
            else
                warn "Push to Gitea failed"
            fi
            cd "$PROJECT_DIR"
        else
            warn "Could not clone skills repo for Gitea sync"
        fi
        rm -rf "$TMPDIR"
    else
        warn "Gitea failed to start — check $HICLAW_DIR/gitea/log/setup-startup.log"
    fi

    # Stop temp Gitea
    log "Stopping temporary Gitea..."
    kill "$GITEA_PID" 2>/dev/null
    wait "$GITEA_PID" 2>/dev/null || true
fi

# ═══════════════════════════════════════════════════════════════════════════
# [5/5] Build Frontend
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "[5/5] Frontend..."
if [ -f "$PROJECT_DIR/frontend/build/client/index.html" ]; then
    ok "Already built"
elif [ -d "$PROJECT_DIR/frontend" ] && command -v npm &>/dev/null; then
    log "Running npm install + build..."
    cd "$PROJECT_DIR/frontend"
    if npm install 2>&1 | tail -1; then
        if npm run build 2>&1 | tail -3; then
            ok "Frontend built"
        else
            warn "npm run build failed"
        fi
    else
        warn "npm install failed"
    fi
    cd "$PROJECT_DIR"
else
    warn "Skipped (no Node.js or no frontend dir)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "=== Setup Complete ==="
echo ""
echo "  Install dir:  $HICLAW_DIR"
echo "  Runtime:      $RUNTIME_DIR/hiclaw-python"
echo "  Gitea:        ${GITEA_BIN:-not installed}"
echo "  Skills repo:  $HICLAW_DIR/skills-repo.git"
echo "  Agent deps:   $MANAGER_DIR/deps/"
echo ""
echo "To start:  bash deploy/start.sh pro"
echo "To stop:   bash deploy/stop.sh"
