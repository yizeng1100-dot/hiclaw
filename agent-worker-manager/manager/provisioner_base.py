"""Abstract Provisioner base — shared helpers + constants + ABC.

This module holds the OS-agnostic pieces of the provisioning system:
- Remote-path defaults (overridable via env vars)
- Template config (only `openhands` for now; same on both OSes)
- Local bundle paths in `deps/`
- `_evt()` helper that builds ProvisionEvent instances
- `ProvisionerBase` — the abstract base class both LinuxProvisioner and
  WindowsProvisioner inherit from.

All Linux-specific shell (bash heredocs, `pgrep`, `tar xzf`, `$HOME`, ...)
lives in `provisioner_linux.py`. All Windows-specific shell (PowerShell,
`%USERPROFILE%`, `Expand-Archive`, `Get-Process`, ...) lives in
`provisioner_windows.py`.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable

from .models import ProvisionEvent, ProvisionStep
from .ssh_client import SSHClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Remote-machine paths (Linux-style; Windows provisioner translates as needed)
# ---------------------------------------------------------------------------

REMOTE_VENV_PATH = os.environ.get('HICLAW_REMOTE_VENV', '$HOME/.hiclaw/agent-venv')
REMOTE_DEPS_PATH = os.environ.get('HICLAW_REMOTE_DEPS', '$HOME/.hiclaw/agent-deps')
REMOTE_CODE_SERVER_PATH = os.environ.get(
    'HICLAW_REMOTE_CODE_SERVER', '$HOME/.hiclaw/code-server'
)
REMOTE_PYTHON_INSTALL_PATH = os.environ.get(
    'HICLAW_REMOTE_PYTHON_PATH', '$HOME/.hiclaw'
)


# ---------------------------------------------------------------------------
# Template config — same package set on both OSes (wheels are cross-platform)
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict] = {
    'openhands': {
        'venv_path': REMOTE_VENV_PATH,
        'pip_package': (
            'openhands-agent-server==1.16.1.post9 '
            'openhands-sdk==1.16.1 '
            'openhands-tools==1.16.1'
        ),
        'binary': f'{REMOTE_VENV_PATH}/bin/agent-server',
        'health_check': '/health',
    },
}


# ---------------------------------------------------------------------------
# Local bundle paths (on app-server)
# ---------------------------------------------------------------------------

DEPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'deps')
BUNDLE_PATH = os.path.join(DEPS_DIR, 'agent-deps-bundle.tar.gz')
# Windows variants — built by `dep_builder.build_windows_bundle()` /
# `build_python_windows_embed()` / `build_claude_cli_windows()`. All three
# are required for full Windows auto-deploy; the provisioner will yield
# failed events with build-command hints if any are missing.
BUNDLE_PATH_WINDOWS = os.path.join(DEPS_DIR, 'agent-deps-bundle-windows.zip')
PYTHON_EMBED_WINDOWS = os.path.join(DEPS_DIR, 'python-windows-embed.zip')
CLAUDE_CLI_BUNDLE_WINDOWS = os.path.join(DEPS_DIR, 'claude-cli-bundle-windows.zip')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evt(step: ProvisionStep, status: str, detail: str = '') -> ProvisionEvent:
    """Short alias for building a ProvisionEvent."""
    return ProvisionEvent(step=step, status=status, detail=detail)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ProvisionerBase(ABC):
    """Abstract base for OS-specific provisioners.

    Holds the bits that are identical across Linux and Windows (SSH handle,
    template config, broadcast callback) and declares the abstract methods
    that subclasses must implement. Subclasses are expected to encapsulate
    ALL shell-specific behavior — this class never runs bash or PowerShell
    commands directly.
    """

    def __init__(
        self,
        ssh: SSHClient,
        template: str = 'openhands',
        broadcast_fn: Callable[[ProvisionEvent], None] | None = None,
    ):
        self.ssh = ssh
        self._host = ssh.host  # convenience for log messages
        self.template = template
        self.tmpl = TEMPLATES.get(template, TEMPLATES['openhands'])
        self._broadcast = broadcast_fn or (lambda evt: None)

    # ------------- shared (OS-agnostic) helpers -------------

    async def _check_remote(self, cmd: str) -> bool:
        """Run a check command on remote, return True if exit code is 0.

        Both subclasses use this for simple existence/version checks. The
        `cmd` string itself is OS-specific and must be constructed by the
        caller.
        """
        _, _, ec = await self.ssh.run(cmd, timeout=5)
        return ec == 0

    # ------------- abstract interface -------------

    @abstractmethod
    def provision(self) -> AsyncGenerator[ProvisionEvent, None]:
        """Run the full provisioning flow, yielding ProvisionEvents per step.

        Implementations should handle all 9 UI steps: SSH_CONNECT, CHECK_PYTHON,
        INSTALL_PYTHON (conditional), SCP_DEPENDENCIES, INSTALL_AGENT_SDK,
        INSTALL_CLAUDE_CLI, CLONE_SKILLS, START_AGENT_SERVER, HEALTH_CHECK,
        SETUP_TUNNEL.
        """
        ...

    @abstractmethod
    async def start_agent_server(
        self,
        port: int,
        env_vars: str,
        log_file: str,
    ) -> None:
        """Launch the agent-server as a detached background process on the remote.

        Subclasses decide how to daemonize (nohup/setsid for Linux, Start-Process
        for PowerShell). Must persist a PID or a similar handle so
        is_agent_server_alive / kill_agent_server can locate it later.
        """
        ...

    @abstractmethod
    async def is_agent_server_alive(self, port: int) -> bool:
        """Return True if the agent-server process for `port` is running."""
        ...

    @abstractmethod
    async def kill_agent_server(self, port: int) -> None:
        """Forcibly terminate the agent-server process for `port` (best-effort)."""
        ...

    async def tail_agent_log(self, log_file: str, lines: int = 30) -> str:
        """Return the last N lines of the agent-server log file.

        Subclasses may override to use platform-specific tail commands.
        Default implementation uses Linux `tail -N`.
        """
        out, _, _ = await self.ssh.run(
            f'tail -{lines} {log_file} 2>/dev/null', timeout=5
        )
        return out.strip()
