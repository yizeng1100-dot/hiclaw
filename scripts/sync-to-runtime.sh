#!/bin/bash
#
# Sync fork code from workspace to .hiclaw/runtime/packages/
# Run after making changes to ensure the running app-server uses latest code.
#
# Usage:
#   ./scripts/sync-to-runtime.sh
#

set -e

WORKSPACE="/home/gyz/cc/workspace/OpenHands"
RUNTIME="/home/gyz/.hiclaw/runtime/packages"

if [ ! -d "$RUNTIME" ]; then
    echo "ERROR: Runtime directory not found: $RUNTIME"
    exit 1
fi

echo "Syncing fork code to runtime..."

# 1. Agent-server fork (packages/agent-server → runtime)
echo "  → agent-server..."
cp -r "$WORKSPACE/packages/agent-server/openhands/agent_server/"* \
      "$RUNTIME/openhands/agent_server/"

# 2. App-server customizations
echo "  → app_conversation models..."
cp "$WORKSPACE/openhands/app_server/app_conversation/app_conversation_models.py" \
   "$RUNTIME/openhands/app_server/app_conversation/"

echo "  → live_status service..."
cp "$WORKSPACE/openhands/app_server/app_conversation/live_status_app_conversation_service.py" \
   "$RUNTIME/openhands/app_server/app_conversation/"

echo "  → sql_app_conversation_info_service..."
cp "$WORKSPACE/openhands/app_server/app_conversation/sql_app_conversation_info_service.py" \
   "$RUNTIME/openhands/app_server/app_conversation/"

echo "  → config..."
cp "$WORKSPACE/openhands/app_server/config.py" \
   "$RUNTIME/openhands/app_server/"

echo "  → server/app.py..."
cp "$WORKSPACE/openhands/server/app.py" \
   "$RUNTIME/openhands/server/"

# 3. Custom modules
echo "  → custom/skill_mgmt..."
mkdir -p "$RUNTIME/custom/skill_mgmt"
cp -r "$WORKSPACE/custom/skill_mgmt/"*.py "$RUNTIME/custom/skill_mgmt/" 2>/dev/null || true

echo "  → custom/skill_examples..."
mkdir -p "$RUNTIME/custom/skill_examples"
cp -r "$WORKSPACE/custom/skill_examples/"* "$RUNTIME/custom/skill_examples/" 2>/dev/null || true

# 4. Rebuild agent-server wheel for remote deployment
echo "  → Rebuilding agent-server wheel..."
cd "$WORKSPACE/packages/agent-server"
/home/gyz/.cache/pypoetry/virtualenvs/openhands-ai-xyHC1t0E-py3.12/bin/python -m build --wheel -q 2>/dev/null
WHL=$(ls -1 dist/openhands_agent_server-*.whl 2>/dev/null | tail -1)
if [ -n "$WHL" ]; then
    cp "$WHL" "$WORKSPACE/agent-worker-manager/deps/wheels/"
    echo "  → Wheel updated: $(basename $WHL)"
fi

echo ""
echo "✓ Sync complete. Restart app-server to apply changes."
