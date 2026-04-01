"""Provisioner — deploys all dependencies from app-server to remote machines.

Always pushes everything from the app-server, regardless of what the remote
machine already has. This ensures internal/air-gapped machines work correctly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator, Callable

from .models import ProvisionEvent, ProvisionStep
from .ssh_client import SSHClient

logger = logging.getLogger(__name__)

# Remote machine paths — configurable via environment variables
# These use $HOME which bash expands on the remote machine — no /opt/ needed, no sudo
REMOTE_VENV_PATH = os.environ.get('HICLAW_REMOTE_VENV', '$HOME/.hiclaw/agent-venv')
REMOTE_DEPS_PATH = os.environ.get('HICLAW_REMOTE_DEPS', '$HOME/.hiclaw/agent-deps')
REMOTE_CODE_SERVER_PATH = os.environ.get('HICLAW_REMOTE_CODE_SERVER', '$HOME/.hiclaw/code-server')
REMOTE_PYTHON_INSTALL_PATH = os.environ.get('HICLAW_REMOTE_PYTHON_PATH', '$HOME/.hiclaw')

# Template-specific config
TEMPLATES = {
    "openhands": {
        "venv_path": REMOTE_VENV_PATH,
        "pip_package": "openhands-agent-server==1.14 openhands-sdk==1.14 openhands-tools==1.14",
        "binary": f"{REMOTE_VENV_PATH}/bin/agent-server",
        "health_check": "/health",
    },
}

# Offline bundle paths (on app-server)
DEPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deps")
BUNDLE_PATH = os.path.join(DEPS_DIR, "agent-deps-bundle.tar.gz")


def _evt(step: ProvisionStep, status: str, detail: str = "") -> ProvisionEvent:
    return ProvisionEvent(step=step, status=status, detail=detail)


class Provisioner:
    """Deploys all dependencies to a remote machine via SSH/SFTP.

    Always pushes from app-server — does not rely on remote having internet.
    """

    def __init__(self, ssh: SSHClient, template: str = "openhands",
                 broadcast_fn: Callable[[ProvisionEvent], None] | None = None):
        self.ssh = ssh
        self.template = template
        self.tmpl = TEMPLATES.get(template, TEMPLATES["openhands"])
        self._broadcast = broadcast_fn or (lambda evt: None)

    async def _check_remote(self, cmd: str) -> bool:
        """Run a check command on remote, return True if exit code is 0."""
        _, _, ec = await self.ssh.run(cmd, timeout=5)
        return ec == 0

    async def provision(self) -> AsyncGenerator[ProvisionEvent, None]:
        """Run all provisioning steps. Each step checks remote state first, skips if already done."""

        # ── Step 1: Python ──
        # Check: standalone 3.12 exists? OR system python >= 3.12?
        standalone_python = f"{REMOTE_PYTHON_INSTALL_PATH}/python/bin/python3.12".replace("$HOME", "~")
        has_standalone = await self._check_remote(f"test -f {standalone_python}")
        remote_python = "python3"
        python_ok = False

        if has_standalone:
            remote_python = standalone_python
            python_ok = True
            yield _evt(ProvisionStep.CHECK_PYTHON, "completed", detail="Python 3.12 already installed")
            logger.info(f"Python: standalone exists at {standalone_python}")
        else:
            yield _evt(ProvisionStep.CHECK_PYTHON, "started")
            sys_ok = await self._check_remote(
                "export PATH=$HOME/.local/bin:$PATH && "
                "python3 -c 'import sys; exit(0 if sys.version_info >= (3,12) else 1)'"
            )
            if sys_ok:
                py_out, _, _ = await self.ssh.run(
                    "export PATH=$HOME/.local/bin:$PATH && which python3", timeout=5)
                remote_python = py_out.strip() or "python3"
                python_ok = True
                ver_out, _, _ = await self.ssh.run(
                    "export PATH=$HOME/.local/bin:$PATH && python3 --version", timeout=5)
                yield _evt(ProvisionStep.CHECK_PYTHON, "completed", detail=ver_out.strip())
            else:
                ver_out, _, _ = await self.ssh.run("python3 --version 2>&1 || echo 'not found'", timeout=5)
                yield _evt(ProvisionStep.CHECK_PYTHON, "started",
                           detail=f"{ver_out.strip()}, need >= 3.12")

        if not python_ok:
            yield _evt(ProvisionStep.INSTALL_PYTHON, "started", detail="Deploying Python 3.12 standalone")
            python_tar = os.path.join(DEPS_DIR, "python3-standalone.tar.gz")
            if os.path.exists(python_tar):
                tar_size_mb = os.path.getsize(python_tar) // 1024 // 1024
                last_mb = [0]
                def _py_progress(sent, total):
                    sent_mb = sent // 1024 // 1024
                    if sent_mb > last_mb[0]:
                        last_mb[0] = sent_mb
                        total_mb = total // 1024 // 1024
                        pct = int(sent * 100 / total) if total else 0
                        self._broadcast(_evt(
                            ProvisionStep.INSTALL_PYTHON, "started",
                            detail=f"Uploading Python {sent_mb}/{total_mb}MB ({pct}%)"
                        ))
                self._broadcast(_evt(ProvisionStep.INSTALL_PYTHON, "started",
                                     detail=f"Uploading Python 3.12 ({tar_size_mb}MB)"))
                await self.ssh.upload_file(python_tar, "/tmp/python3-standalone.tar.gz",
                                           progress_callback=_py_progress)
                self._broadcast(_evt(ProvisionStep.INSTALL_PYTHON, "started",
                                     detail="Extracting..."))
                await self.ssh.run(f"mkdir -p {REMOTE_PYTHON_INSTALL_PATH} && tar xzf /tmp/python3-standalone.tar.gz -C {REMOTE_PYTHON_INSTALL_PATH}/ && rm /tmp/python3-standalone.tar.gz", timeout=120)
                # Override system python3/pip3 with 3.12 — put in front of PATH
                await self.ssh.run(
                    f"mkdir -p $HOME/.local/bin && "
                    f"ln -sf {REMOTE_PYTHON_INSTALL_PATH}/python/bin/python3.12 $HOME/.local/bin/python3 && "
                    f"ln -sf {REMOTE_PYTHON_INSTALL_PATH}/python/bin/python3.12 $HOME/.local/bin/python3.12 && "
                    f"ln -sf {REMOTE_PYTHON_INSTALL_PATH}/python/bin/pip3.12 $HOME/.local/bin/pip3 && "
                    f"ln -sf {REMOTE_PYTHON_INSTALL_PATH}/python/bin/pip3.12 $HOME/.local/bin/pip3.12",
                    timeout=5,
                )
                # Ensure PATH has ~/.local/bin first
                await self.ssh.run("grep -q '.local/bin' $HOME/.bashrc || echo 'export PATH=$HOME/.local/bin:$PATH' >> $HOME/.bashrc", timeout=5)
                # Verify with full path
                remote_python = f"{REMOTE_PYTHON_INSTALL_PATH}/python/bin/python3.12"
                _, _, ec = await self.ssh.run(f"{remote_python} --version", timeout=5)
                if ec == 0:
                    yield _evt(ProvisionStep.INSTALL_PYTHON, "completed")
                else:
                    yield _evt(ProvisionStep.INSTALL_PYTHON, "failed", detail="Python install failed")
                    return
            else:
                yield _evt(ProvisionStep.INSTALL_PYTHON, "failed", detail="python3-standalone.tar.gz not found")
                return

        # ── Step 2: Agent SDK ──
        # Check: wrapper script exists?
        binary = self.tmpl["binary"].replace("$HOME", "~")
        has_sdk = await self._check_remote(
            f"test -f {binary} || test -f /opt/agent-venv/bin/agent-server"
        )
        if has_sdk:
            yield _evt(ProvisionStep.SCP_DEPENDENCIES, "skipped", detail="Already installed")
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed", detail="Already installed")
            logger.info("SDK: already installed, skipping")
        else:
            venv = self.tmpl["venv_path"]
            # Check: wheels already on remote?
            has_wheels = await self._check_remote(f"test -d {REMOTE_DEPS_PATH}/wheels")
            if has_wheels:
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "skipped", detail="Wheels already on remote")
                logger.info("SDK wheels: already on remote, skipping upload")
            else:
                wheels_dir = os.path.join(DEPS_DIR, "wheels")
                if not os.path.isdir(wheels_dir):
                    yield _evt(ProvisionStep.SCP_DEPENDENCIES, "failed", detail="wheels/ not found in deps/")
                    return
                import subprocess
                wheels_archive = "/tmp/_wheels_upload.tar.gz"
                subprocess.run(f"tar czf {wheels_archive} -C {DEPS_DIR} wheels/",
                               shell=True, check=True, timeout=30)
                archive_size_mb = os.path.getsize(wheels_archive) // 1024 // 1024
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "started", detail=f"Uploading {archive_size_mb}MB")
                last_mb = [0]
                def _on_progress(sent, total):
                    sent_mb = sent // 1024 // 1024
                    if sent_mb > last_mb[0]:
                        last_mb[0] = sent_mb
                        pct = int(sent * 100 / total) if total else 0
                        self._broadcast(_evt(ProvisionStep.SCP_DEPENDENCIES, "started",
                                             detail=f"{sent_mb}/{archive_size_mb}MB ({pct}%)"))
                await self.ssh.upload_file(wheels_archive, "/tmp/agent-wheels.tar.gz",
                                           progress_callback=_on_progress)
                await self.ssh.run(
                    f"mkdir -p {REMOTE_DEPS_PATH} && "
                    f"tar xzf /tmp/agent-wheels.tar.gz -C {REMOTE_DEPS_PATH}/ && "
                    f"rm -f /tmp/agent-wheels.tar.gz", timeout=60)
                os.remove(wheels_archive)
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "completed", detail=f"{archive_size_mb}MB uploaded")

            # Install SDK from wheels
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Installing from wheels")
            await self.ssh.run(f"{remote_python} -m ensurepip --upgrade 2>/dev/null || true", timeout=30)
            await self.ssh.run(
                f"{remote_python} -m pip install --break-system-packages --upgrade "
                f"--no-index --find-links {REMOTE_DEPS_PATH}/wheels/ "
                f"pip setuptools wheel 2>&1 || true", timeout=60)
            stdout_all, stderr, ec = await self.ssh.run(
                f"{remote_python} -m pip install --break-system-packages --upgrade "
                f"--ignore-installed --prefer-binary --target {venv}/lib "
                f"--no-index --find-links {REMOTE_DEPS_PATH}/wheels/ "
                f"{self.tmpl['pip_package']} 2>&1", timeout=300)
            if ec != 0:
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "failed",
                           detail=(stdout_all + "\n" + stderr).strip()[-2000:])
                return
            await self.ssh.run(
                f"mkdir -p {venv}/bin && "
                f"echo '#!/bin/bash' > {venv}/bin/agent-server && "
                f"echo 'PYTHONPATH={venv}/lib:$PYTHONPATH exec {remote_python} -m openhands.agent_server \"$@\"' >> {venv}/bin/agent-server && "
                f"chmod +x {venv}/bin/agent-server", timeout=10)
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed")

        # ── Step 3: code-server — skipped (users use VS Code Remote SSH) ──
        yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "skipped", detail="Use VS Code Remote SSH")

