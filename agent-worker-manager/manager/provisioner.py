"""Provisioner factory — picks Linux or Windows implementation.

Historically this file held a single `Provisioner` class with all the
bash-centric logic inline. That class has been split into two subclasses
of `ProvisionerBase`:

- `LinuxProvisioner` in `provisioner_linux.py` (the existing code, moved
  verbatim — zero behavior change)
- `WindowsProvisioner` in `provisioner_windows.py` (new; PowerShell-based)

This module is now just:
  1. A thin `make_provisioner(ssh, os_type, ...)` factory that instantiates
     the right subclass based on `OsType`.
  2. Backward-compatible re-exports: anywhere in the codebase that still
     imports `Provisioner`, `REMOTE_VENV_PATH`, `DEPS_DIR`, `TEMPLATES`,
     etc. from `manager.provisioner` keeps working.
"""

from __future__ import annotations

from typing import Callable

from .models import OsType, ProvisionEvent
from .provisioner_base import (
    BUNDLE_PATH,
    BUNDLE_PATH_WINDOWS,
    DEPS_DIR,
    PYTHON_EMBED_WINDOWS,
    REMOTE_CODE_SERVER_PATH,
    REMOTE_DEPS_PATH,
    REMOTE_PYTHON_INSTALL_PATH,
    REMOTE_VENV_PATH,
    TEMPLATES,
    ProvisionerBase,
    _evt,
)
from .provisioner_linux import LinuxProvisioner
from .provisioner_windows import WindowsProvisioner
from .ssh_client import SSHClient

# Backward-compat alias: old code imports `Provisioner` directly.
Provisioner = LinuxProvisioner

__all__ = [
    # Factory
    'make_provisioner',
    # Classes
    'ProvisionerBase',
    'LinuxProvisioner',
    'WindowsProvisioner',
    'Provisioner',  # legacy alias
    # Constants still imported by other modules
    'TEMPLATES',
    'DEPS_DIR',
    'BUNDLE_PATH',
    'BUNDLE_PATH_WINDOWS',
    'PYTHON_EMBED_WINDOWS',
    'REMOTE_VENV_PATH',
    'REMOTE_DEPS_PATH',
    'REMOTE_CODE_SERVER_PATH',
    'REMOTE_PYTHON_INSTALL_PATH',
    # Helpers
    '_evt',
]


def make_provisioner(
    ssh: SSHClient,
    os_type: OsType | str = OsType.LINUX,
    *,
    template: str = 'openhands',
    broadcast_fn: Callable[[ProvisionEvent], None] | None = None,
) -> ProvisionerBase:
    """Build the correct Provisioner subclass for the target machine's OS.

    Args:
        ssh: Already-connected SSHClient.
        os_type: Target machine OS. `OsType.LINUX` (default) or `OsType.WINDOWS`.
                 Accepts plain strings ("linux" / "windows") for convenience.
        template: Template name from `TEMPLATES` (only "openhands" today).
        broadcast_fn: Optional callback that receives every ProvisionEvent as
                      it's emitted (used to stream live progress to the UI).

    Returns:
        A concrete `ProvisionerBase` subclass ready to `.provision()`.
    """
    # Normalize string input
    if isinstance(os_type, str):
        try:
            os_type = OsType(os_type)
        except ValueError:
            os_type = OsType.LINUX

    if os_type == OsType.WINDOWS:
        return WindowsProvisioner(ssh, template=template, broadcast_fn=broadcast_fn)
    return LinuxProvisioner(ssh, template=template, broadcast_fn=broadcast_fn)
