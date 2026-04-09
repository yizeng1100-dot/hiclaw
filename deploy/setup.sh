#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# HiClaw One-Click Setup (No sudo required)
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage:
#   1. git clone -b dev https://github.com/yizeng1100-dot/hiclaw.git && cd hiclaw
#   2. Put these files in deploy/ directory:
#      - hiclaw-runtime.tar.gz  (必需) Python 3.12 + 所有依赖 + Gitea + 浏览器
#      - hiclaw-deps.tar.gz    (远程worker需要) 远程 agent-worker 依赖
#   3. bash deploy/setup.sh
#   4. bash deploy/start.sh pro
#
# All files installed to $HICLAW_DIR (default: ~/.hiclaw), NO sudo needed.
#
# ─── 离线包说明 (均在有网机器上打包，传到内网) ───
#
# hiclaw-runtime.tar.gz (~777MB, 解压后 ~1.5GB)
#   内容: 一个包搞定本机所有运行依赖
#     ./hiclaw-python        — Python 3.12 可执行文件
#     ./hiclaw-uvicorn       — Uvicorn 可执行文件
#     ./packages/            — 所有 Python 依赖 (openhands-sdk 1.16.1, fastapi, playwright 等)
#     ./bin/gitea            — Gitea 1.22.6 (bindata, 内嵌 Web 资源)
#     ./ms-playwright/       — Chromium 浏览器二进制
#   解压到: ~/.hiclaw/runtime/
#   setup.sh 会自动:
#     - 把 bin/gitea 移到 ~/.hiclaw/bin/gitea
#     - 把 ms-playwright/ 移到 ~/.cache/ms-playwright/
#   验证: ~/.hiclaw/runtime/hiclaw-python -c 'import uvicorn,fastapi;print("OK")'
#
#   ⚠ 版本依赖（重打包时务必匹配）:
#     - openhands-sdk == openhands-tools == openhands-agent-server == 1.16.1
#     - 与 ghcr.io/openhands/agent-server:1.16.1-python Docker 镜像配套使用
#
#   打包方法 (在有网机器上):
#     1. 解压旧 runtime: tar xzf hiclaw-runtime.tar.gz -C /tmp/repack/
#     2. 加 Gitea:       cp gitea /tmp/repack/bin/gitea && chmod +x /tmp/repack/bin/gitea
#     3. 加浏览器:       cp -r ~/.cache/ms-playwright /tmp/repack/ms-playwright
#     4. 重新打包:       tar czf hiclaw-runtime.tar.gz -C /tmp/repack .
#
# hiclaw-deps.tar.gz (~219MB) [远程 worker 场景需要]
#   内容:
#     wheels/              — 187 个 Python wheel 包 (用于远程 agent-worker 离线安装)
#     python3-standalone.tar.gz (21MB) — 轻量 Python 3.12 (远程 worker 用)
#     code-server.tar.gz (109MB) — VS Code Server (远程代码编辑)
#   用途: 给远程 agent-worker 机器用，本机单机部署可不需要
#   解压到: agent-worker-manager/deps/
#
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

        # Install Gitea from runtime bundle (if included)
        if [ -f "$RUNTIME_DIR/bin/gitea" ]; then
            mkdir -p "$HICLAW_DIR/bin"
            mv "$RUNTIME_DIR/bin/gitea" "$HICLAW_DIR/bin/gitea"
            chmod +x "$HICLAW_DIR/bin/gitea"
            ok "Gitea installed from runtime bundle: $($HICLAW_DIR/bin/gitea --version 2>&1 | head -1)"
        fi

        # Install Playwright browsers from runtime bundle (if included)
        if [ -d "$RUNTIME_DIR/ms-playwright" ]; then
            # Detect where playwright expects browsers
            PW_BROWSER_PATH=$($RUNTIME_DIR/hiclaw-python -c "
from pathlib import Path; import os
print(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', str(Path.home() / '.cache' / 'ms-playwright')))
" 2>/dev/null || echo "$HOME/.cache/ms-playwright")
            mkdir -p "$(dirname "$PW_BROWSER_PATH")"
            # Remove old browsers if exist, then install new
            rm -rf "$PW_BROWSER_PATH"
            mv "$RUNTIME_DIR/ms-playwright" "$PW_BROWSER_PATH"
            ok "Playwright browsers installed to $PW_BROWSER_PATH"
        fi

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
# [0.5/5] Playwright (optional — for browser automation)
# ═══════════════════════════════════════════════════════════════════════════
PLAYWRIGHT_BUNDLE="$SCRIPT_DIR/playwright-bundle.tar.gz"
if [ -f "$PLAYWRIGHT_BUNDLE" ]; then
    # Check if already installed
    if $PYTHON -c "import playwright" 2>/dev/null; then
        ok "Playwright already installed"
    else
        echo "[0.5/5] Installing Playwright..."
        PW_TMP="$(mktemp -d)"
        if tar xzf "$PLAYWRIGHT_BUNDLE" -C "$PW_TMP"; then
            # Install Python wheels
            $PYTHON -m pip install --no-index --find-links="$PW_TMP/playwright-bundle/" playwright 2>&1 | tail -3
            ok "Playwright Python package installed"
            # Extract browsers
            if [ -f "$PW_TMP/playwright-bundle/browsers.tar.gz" ]; then
                tar xzf "$PW_TMP/playwright-bundle/browsers.tar.gz" -C "$HOME/.cache/"
                ok "Playwright browsers installed to ~/.cache/ms-playwright/"
            fi
        else
            warn "Failed to extract playwright-bundle.tar.gz"
        fi
        rm -rf "$PW_TMP"
    fi
else
    log "playwright-bundle.tar.gz not found — skipping (browser tools disabled)"
fi

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
            # Agent deps — support two layouts:
            # 1. Legacy: agent-deps/wheels.tar.gz nested
            # 2. Flat:   wheels/ directly in the root
            if [ -d "$DEPS_TMP/agent-deps" ]; then
                mkdir -p "$MANAGER_DIR/deps"
                cp "$DEPS_TMP/agent-deps/"* "$MANAGER_DIR/deps/" 2>/dev/null
                if [ -f "$MANAGER_DIR/deps/wheels.tar.gz" ]; then
                    log "Extracting wheels..."
                    tar xzf "$MANAGER_DIR/deps/wheels.tar.gz" -C "$MANAGER_DIR/deps/"
                    rm -f "$MANAGER_DIR/deps/wheels.tar.gz"
                    ok "Agent deps extracted ($(ls "$MANAGER_DIR/deps/wheels/" 2>/dev/null | wc -l) wheels)"
                fi
            elif [ -d "$DEPS_TMP/wheels" ]; then
                # Flat layout — wheels/ directly in tar root
                mkdir -p "$MANAGER_DIR/deps"
                cp -r "$DEPS_TMP/wheels" "$MANAGER_DIR/deps/"
                ok "Agent deps copied ($(ls "$MANAGER_DIR/deps/wheels/" 2>/dev/null | wc -l) wheels)"
            else
                warn "No agent-deps/ or wheels/ in bundle"
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
# [4/5] Gitea: Create User + Sync Skills (all in one step with Gitea running)
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "[4/5] Gitea user + skills sync..."

if [ ! -f "$GITEA_BIN" ]; then
    warn "Gitea not installed, skipping"
else
    # Kill any running Gitea first
    pkill -f "gitea web" 2>/dev/null; sleep 1

    # Clean Gitea data for fresh setup (ensures no stale must_change_password state)
    # Only clean if user/repo verification fails
    GITEA_DB="$HICLAW_DIR/gitea/data/gitea.db"
    NEED_FRESH=false
    if [ -f "$GITEA_DB" ]; then
        # Quick test: can we authenticate?
        # Start Gitea briefly to test
        GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" web \
            --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
            > "$HICLAW_DIR/gitea/log/setup-startup.log" 2>&1 &
        _TEST_PID=$!
        sleep 5
        _AUTH_TEST=$(curl -s --noproxy "*" --max-time 3 -u "$GITEA_USER:$GITEA_PASS" \
            "http://127.0.0.1:$GITEA_PORT/api/v1/user" 2>&1)
        kill $_TEST_PID 2>/dev/null; wait $_TEST_PID 2>/dev/null || true; sleep 1
        if echo "$_AUTH_TEST" | grep -qi "change.*password\|unauthorized"; then
            log "Existing Gitea has auth issues, doing fresh setup..."
            NEED_FRESH=true
        fi
    else
        NEED_FRESH=true
    fi

    if $NEED_FRESH; then
        log "Cleaning Gitea data for fresh initialization..."
        rm -rf "$HICLAW_DIR/gitea/data" "$HICLAW_DIR/gitea/repos" "$HICLAW_DIR/gitea/log"
        mkdir -p "$HICLAW_DIR/gitea/data" "$HICLAW_DIR/gitea/repos" "$HICLAW_DIR/gitea/log"
    fi

    # Step 1: Start Gitea to initialize database
    log "Starting Gitea temporarily (to initialize DB)..."
    mkdir -p "$HICLAW_DIR/gitea/log"
    GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" web \
        --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
        > "$HICLAW_DIR/gitea/log/setup-startup.log" 2>&1 &
    GITEA_PID=$!
    log "Waiting for Gitea to start (PID $GITEA_PID)..."

    # Wait up to 30 seconds for Gitea
    GITEA_READY=false
    for i in $(seq 1 30); do
        if curl -s --noproxy "*" --max-time 2 "http://127.0.0.1:$GITEA_PORT" >/dev/null 2>&1; then
            GITEA_READY=true
            break
        fi
        sleep 1
    done

    if $GITEA_READY; then
        ok "Gitea started (took ${i}s)"

        # Give Gitea a moment to fully initialize DB tables
        sleep 3

        # Step 2: Create admin user via CLI (DB is now initialized)
        log "Creating admin user '$GITEA_USER'..."
        CLI_OUTPUT=$(GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" admin user create \
            --username "$GITEA_USER" --password "$GITEA_PASS" \
            --email admin@hiclaw.local --admin --must-change-password=false \
            --config "$HICLAW_DIR/gitea/custom/conf/app.ini" 2>&1)
        CLI_EXIT=$?

        # Always clear must_change_password flag via SQLite, then restart Gitea
        # Gitea caches user state in memory, so DB change alone is not enough
        GITEA_DB="$HICLAW_DIR/gitea/data/gitea.db"
        if [ -f "$GITEA_DB" ]; then
            log "Clearing must_change_password flag..."
            if command -v sqlite3 &>/dev/null; then
                sqlite3 "$GITEA_DB" "UPDATE user SET must_change_password=0 WHERE lower_name='$(echo "$GITEA_USER" | tr '[:upper:]' '[:lower:]')';" 2>/dev/null
            else
                $PYTHON -c "
import sqlite3
conn = sqlite3.connect('$GITEA_DB')
conn.execute(\"UPDATE user SET must_change_password=0 WHERE lower_name=?\", ('$(echo "$GITEA_USER" | tr '[:upper:]' '[:lower:]')',))
conn.commit()
conn.close()
" 2>/dev/null
            fi

            # Restart Gitea so it picks up the DB change
            log "Restarting Gitea to apply changes..."
            kill "$GITEA_PID" 2>/dev/null
            wait "$GITEA_PID" 2>/dev/null || true
            sleep 2
            GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" web \
                --config "$HICLAW_DIR/gitea/custom/conf/app.ini" \
                > "$HICLAW_DIR/gitea/log/setup-startup.log" 2>&1 &
            GITEA_PID=$!
            # Wait for restart
            for j in $(seq 1 15); do
                if curl -s --noproxy "*" --max-time 2 "http://127.0.0.1:$GITEA_PORT" >/dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
            ok "Gitea restarted"
        fi

        if [ $CLI_EXIT -eq 0 ]; then
            ok "Admin user created via CLI"
        elif echo "$CLI_OUTPUT" | grep -qi "already exists"; then
            ok "Admin user already exists"
            # Reset password in case it's wrong
            GITEA_WORK_DIR="$HICLAW_DIR/gitea" "$GITEA_BIN" admin user change-password \
                --username "$GITEA_USER" --password "$GITEA_PASS" \
                --config "$HICLAW_DIR/gitea/custom/conf/app.ini" 2>&1 || true
        else
            warn "CLI user creation failed (exit=$CLI_EXIT): $CLI_OUTPUT"
            log "Trying API registration as fallback..."
            # Try sign-up form (works when registration is enabled)
            curl -s --noproxy "*" -X POST "http://127.0.0.1:$GITEA_PORT/user/sign_up" \
                -d "user_name=$GITEA_USER&password=$GITEA_PASS&retype=$GITEA_PASS&email=admin@hiclaw.local" 2>&1 || true
            sleep 1
        fi

        # Step 3: Verify user exists
        log "Verifying admin user..."
        USER_CHECK=$(curl -s --noproxy "*" --max-time 5 -u "$GITEA_USER:$GITEA_PASS" \
            "http://127.0.0.1:$GITEA_PORT/api/v1/user" 2>&1)
        if echo "$USER_CHECK" | grep -q '"login"'; then
            ok "Admin user verified (login OK)"
        else
            fail "Admin user NOT working. API response: $(echo "$USER_CHECK" | head -1)"
            fail "Manual fix: GITEA_WORK_DIR=$HICLAW_DIR/gitea $GITEA_BIN admin user create --username $GITEA_USER --password '$GITEA_PASS' --email admin@hiclaw.local --admin --config $HICLAW_DIR/gitea/custom/conf/app.ini"
        fi

        # Step 4: Create skills repo (only if user is working)
        if echo "$USER_CHECK" | grep -q '"login"'; then
            log "Creating skills repo..."
            REPO_CHECK=$(curl -s --noproxy "*" --max-time 5 -u "$GITEA_USER:$GITEA_PASS" \
                "http://127.0.0.1:$GITEA_PORT/api/v1/repos/$GITEA_USER/skills" 2>&1)
            if echo "$REPO_CHECK" | grep -q '"full_name"'; then
                ok "Skills repo already exists"
            else
                REPO_CREATE=$(curl -s --noproxy "*" -X POST "http://127.0.0.1:$GITEA_PORT/api/v1/user/repos" \
                    -H "Content-Type: application/json" \
                    -u "$GITEA_USER:$GITEA_PASS" \
                    -d '{"name":"skills","description":"HiClaw Skills Repository","default_branch":"master","auto_init":true}' 2>&1)
                if echo "$REPO_CREATE" | grep -q '"full_name"'; then
                    ok "Skills repo created"
                else
                    fail "Could not create skills repo: $(echo "$REPO_CREATE" | head -1)"
                fi
            fi

            # Also create extensions repo
            log "Creating extensions repo..."
            EXT_CHECK=$(curl -s --noproxy "*" --max-time 5 -u "$GITEA_USER:$GITEA_PASS" \
                "http://127.0.0.1:$GITEA_PORT/api/v1/repos/$GITEA_USER/extensions" 2>&1)
            if echo "$EXT_CHECK" | grep -q '"full_name"'; then
                ok "Extensions repo already exists"
            else
                curl -s --noproxy "*" -X POST "http://127.0.0.1:$GITEA_PORT/api/v1/user/repos" \
                    -H "Content-Type: application/json" \
                    -u "$GITEA_USER:$GITEA_PASS" \
                    -d '{"name":"extensions","description":"OpenHands extensions (mirrored)","default_branch":"main","auto_init":false}' >/dev/null 2>&1
                ok "Extensions repo created"
            fi
        else
            warn "Skipping repo creation — admin user not working"
        fi

        # Step 5: Push skills
        if [ -d "$HICLAW_DIR/skills-repo.git" ]; then
            log "Pushing skills to Gitea..."
            TMPDIR="$(mktemp -d)"
            if git clone "$HICLAW_DIR/skills-repo.git" "$TMPDIR/skills" 2>/dev/null; then
                cd "$TMPDIR/skills"
                git remote add gitea "http://$GITEA_USER:$GITEA_PASS@127.0.0.1:$GITEA_PORT/$GITEA_USER/skills.git" 2>/dev/null || true
                PUSH_OUTPUT=$(http_proxy="" https_proxy="" HTTP_PROXY="" HTTPS_PROXY="" git -c http.proxy="" push gitea master --force 2>&1)
                if [ $? -eq 0 ]; then
                    ok "Skills pushed to Gitea"
                else
                    warn "Push failed: $PUSH_OUTPUT"
                fi
                cd "$PROJECT_DIR"
            else
                warn "Could not clone skills repo"
            fi
            rm -rf "$TMPDIR"
        fi
    else
        warn "Gitea failed to start after 30s"
        warn "Check: cat $HICLAW_DIR/gitea/log/setup-startup.log"
    fi

    # Stop temp Gitea
    log "Stopping temporary Gitea..."
    kill "$GITEA_PID" 2>/dev/null
    wait "$GITEA_PID" 2>/dev/null || true
    ok "Gitea setup done"
fi

# ═══════════════════════════════════════════════════════════════════════════
# [5/5] Build Frontend
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "[5/5] Frontend..."
if [ -f "$PROJECT_DIR/frontend/build/index.html" ]; then
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
