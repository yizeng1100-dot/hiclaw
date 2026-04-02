"""
>>> CUSTOM: HiClaw — Centralized configuration.

All HiClaw paths, ports, and credentials are defined here.
NEVER hardcode these values in other files — always import from here.
<<<
"""

import os

# ─── Paths ───
HICLAW_DIR = os.environ.get('HICLAW_DIR', os.path.join(os.path.expanduser('~'), '.hiclaw'))
SKILLS_REPO_PATH = os.path.join(HICLAW_DIR, 'skills-repo.git')
GITEA_DIR = os.path.join(HICLAW_DIR, 'gitea')
VENV_DIR = os.path.join(HICLAW_DIR, 'venv')

# ─── Ports ───
GITEA_PORT = int(os.environ.get('HICLAW_GITEA_PORT', '3300'))
WORKER_MANAGER_PORT = int(os.environ.get('HICLAW_MANAGER_PORT', '9090'))
APP_SERVER_PORT = int(os.environ.get('HICLAW_APP_PORT', '3000'))
GIT_DAEMON_PORT = int(os.environ.get('HICLAW_GIT_DAEMON_PORT', '19418'))
CODE_SERVER_PORT = int(os.environ.get('HICLAW_CODE_SERVER_PORT', '8443'))
AGENT_SERVER_PORT = int(os.environ.get('HICLAW_AGENT_PORT', '8000'))

# ─── Gitea ───
GITEA_ADMIN_USER = os.environ.get('HICLAW_GITEA_USER', 'hiclaw-admin')
GITEA_ADMIN_PASSWORD = os.environ.get('HICLAW_GITEA_PASSWORD', 'HiClaw2026!')
GITEA_REPO_NAME = os.environ.get('HICLAW_GITEA_REPO', 'skills')

# ─── URLs (derived) ───
GITEA_URL = f'http://localhost:{GITEA_PORT}'
WORKER_MANAGER_URL = f'http://localhost:{WORKER_MANAGER_PORT}'
GITEA_REPO_URL = f'{GITEA_URL}/{GITEA_ADMIN_USER}/{GITEA_REPO_NAME}'
GITEA_REPO_AUTH_URL = f'http://{GITEA_ADMIN_USER}:{GITEA_ADMIN_PASSWORD}@localhost:{GITEA_PORT}/{GITEA_ADMIN_USER}/{GITEA_REPO_NAME}.git'

# ─── Defaults ───
DEFAULT_WORKSPACE = os.environ.get('HICLAW_DEFAULT_WORKSPACE', '/root/workspace')

# ─── Public Skills ───
# Mirror of github.com/OpenHands/extensions on internal Gitea
# Agent-server clones from here instead of GitHub (works in air-gapped networks)
PUBLIC_SKILLS_REPO = os.environ.get(
    'OH_PUBLIC_SKILLS_REPO',
    f'http://{GITEA_ADMIN_USER}:{GITEA_ADMIN_PASSWORD}@localhost:{GITEA_PORT}/{GITEA_ADMIN_USER}/extensions.git'
)

# App server IP reachable from remote machines (for MCP URL replacement)
# MUST be set in internal networks where icanhazip.com is not accessible
APP_IP = os.environ.get('HICLAW_APP_IP', '')
