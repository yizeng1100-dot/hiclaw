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

    async def provision(self) -> AsyncGenerator[ProvisionEvent, None]:
        """Run all provisioning steps, yielding progress events."""

        # Step 1: Check if already fully provisioned (skip everything)
        # Check both new path ($HOME/.hiclaw/) and legacy path (/opt/agent-venv/)
        binary = self.tmpl["binary"]
        stdout, _, ec = await self.ssh.run(
            f"test -f {binary} && echo YES || test -f /opt/agent-venv/bin/agent-server && echo YES || echo NO",
            timeout=5,
        )
        already_has_sdk = stdout.strip() == "YES"
        _, _, ec2 = await self.ssh.run("command -v code-server 2>/dev/null || test -f $HOME/.local/bin/code-server || test -f $HOME/.hiclaw/code-server/bin/code-server", timeout=5)
        already_has_cs = ec2 == 0

        if already_has_sdk and already_has_cs:
            yield _evt(ProvisionStep.CHECK_PYTHON, "completed", detail="Already deployed")
            yield _evt(ProvisionStep.SCP_DEPENDENCIES, "skipped", detail="Already deployed")
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed", detail="Already deployed")
            yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "completed", detail="Already deployed")
            return

        # Step 2: Check Python — only needed if SDK not yet installed
        # First check if standalone Python 3.12 was already installed (fastest check)
        standalone_python = f"{REMOTE_PYTHON_INSTALL_PATH}/python/bin/python3.12"
        _, _, py312_ec = await self.ssh.run(f"test -f {standalone_python}", timeout=5)
        has_standalone = py312_ec == 0

        remote_python = "python3"
        python_ok = False

        if has_standalone:
            # Standalone Python 3.12 already installed — use it directly
            remote_python = standalone_python
            python_ok = True
            yield _evt(ProvisionStep.CHECK_PYTHON, "completed",
                       detail="Python 3.12 (standalone, already installed)")
        elif not already_has_sdk:
            yield _evt(ProvisionStep.CHECK_PYTHON, "started")
            # Check with $HOME/.local/bin in PATH (where we symlink python3.12)
            stdout, _, ec = await self.ssh.run(
                "export PATH=$HOME/.local/bin:$PATH && python3 --version", timeout=10)
            if ec == 0:
                version_str = stdout.strip()
                _, _, ver_ec = await self.ssh.run(
                    "export PATH=$HOME/.local/bin:$PATH && "
                    "python3 -c 'import sys; exit(0 if sys.version_info >= (3,12) else 1)'",
                    timeout=5,
                )
                if ver_ec == 0:
                    python_ok = True
                    py_path_out, _, _ = await self.ssh.run(
                        "export PATH=$HOME/.local/bin:$PATH && which python3", timeout=5)
                    remote_python = py_path_out.strip() or "python3"
                    yield _evt(ProvisionStep.CHECK_PYTHON, "completed", detail=version_str)
                else:
                    yield _evt(ProvisionStep.CHECK_PYTHON, "started",
                               detail=f"{version_str} too old, need >= 3.12")
        else:
            # SDK already installed — find which python to use
            yield _evt(ProvisionStep.CHECK_PYTHON, "completed", detail="SDK already installed")
            python_ok = True
            py_out, _, _ = await self.ssh.run(
                "export PATH=$HOME/.local/bin:$PATH && which python3", timeout=5)
            remote_python = py_out.strip() or "python3"

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

        # Step 3+4: Install SDK — always push wheels from app-server (treat remote as offline)
        if not already_has_sdk:
            venv = self.tmpl["venv_path"]  # e.g. ~/.hiclaw/agent-venv

            # Upload wheels from app-server
            wheels_dir = os.path.join(DEPS_DIR, "wheels")
            if not os.path.isdir(wheels_dir):
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "failed", detail="wheels/ not found in deps/")
                return

            import subprocess
            wheels_archive = "/tmp/_wheels_upload.tar.gz"
            subprocess.run(f"tar czf {wheels_archive} -C {DEPS_DIR} wheels/",
                           shell=True, check=True, timeout=30)
            archive_size = os.path.getsize(wheels_archive)
            archive_size_mb = archive_size // 1024 // 1024
            yield _evt(ProvisionStep.SCP_DEPENDENCIES, "started",
                       detail=f"Uploading {archive_size_mb}MB")

            last_mb = [0]
            def _on_progress(sent, total):
                sent_mb = sent // 1024 // 1024
                if sent_mb > last_mb[0]:
                    last_mb[0] = sent_mb
                    total_mb = total // 1024 // 1024
                    pct = int(sent * 100 / total) if total else 0
                    self._broadcast(_evt(
                        ProvisionStep.SCP_DEPENDENCIES, "started",
                        detail=f"{sent_mb}/{total_mb}MB ({pct}%)"
                    ))

            await self.ssh.upload_file(wheels_archive, "/tmp/agent-wheels.tar.gz",
                                       progress_callback=_on_progress)
            await self.ssh.run(
                f"mkdir -p {REMOTE_DEPS_PATH} && "
                f"tar xzf /tmp/agent-wheels.tar.gz -C {REMOTE_DEPS_PATH}/ && "
                f"rm -f /tmp/agent-wheels.tar.gz",
                timeout=60,
            )
            os.remove(wheels_archive)
            yield _evt(ProvisionStep.SCP_DEPENDENCIES, "completed", detail=f"{archive_size_mb}MB uploaded")

            # Install from local wheels only — no internet needed
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Installing from wheels")
            await self.ssh.run(
                f"{remote_python} -m ensurepip --upgrade 2>/dev/null || true",
                timeout=30,
            )
            # Install setuptools+wheel first (pip install wheel doesn't need setuptools)
            await self.ssh.run(
                f"{remote_python} -m pip install --break-system-packages --upgrade "
                f"--no-index --find-links {REMOTE_DEPS_PATH}/wheels/ "
                f"pip setuptools wheel 2>&1 || true",
                timeout=60,
            )
            # Install SDK packages
            stdout_all, stderr, ec = await self.ssh.run(
                f"{remote_python} -m pip install --break-system-packages --upgrade "
                f"--ignore-installed --prefer-binary "
                f"--target {venv}/lib "
                f"--no-index --find-links {REMOTE_DEPS_PATH}/wheels/ "
                f"{self.tmpl['pip_package']} 2>&1",
                timeout=300,
            )

            # Create wrapper script
            await self.ssh.run(
                f"mkdir -p {venv}/bin && "
                f"echo '#!/bin/bash' > {venv}/bin/agent-server && "
                f"echo 'PYTHONPATH={venv}/lib:$PYTHONPATH exec {remote_python} -m openhands.agent_server \"$@\"' >> {venv}/bin/agent-server && "
                f"chmod +x {venv}/bin/agent-server",
                timeout=10,
            )
            if ec != 0:
                all_output = (stdout_all + "\n" + stderr).strip()
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "failed", detail=all_output[-2000:])
                return
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed")
        else:
            yield _evt(ProvisionStep.CHECK_AGENT_SDK, "completed", detail="Already installed")

        # Step 5: Install code-server — always upload from app-server (same as SDK)
        if not already_has_cs:
            CS_FILE = "code-server.tar.gz"
            cs_tar = os.path.join(DEPS_DIR, CS_FILE)
            if os.path.exists(cs_tar):
                cs_size_mb = os.path.getsize(cs_tar) // 1024 // 1024
                yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "started",
                           detail=f"Uploading code-server ({cs_size_mb}MB)")

                last_mb = [0]
                def _cs_progress(sent, total):
                    sent_mb = sent // 1024 // 1024
                    if sent_mb > last_mb[0]:
                        last_mb[0] = sent_mb
                        total_mb = total // 1024 // 1024
                        pct = int(sent * 100 / total) if total else 0
                        self._broadcast(_evt(
                            ProvisionStep.INSTALL_CODE_SERVER, "started",
                            detail=f"Uploading {sent_mb}/{total_mb}MB ({pct}%)"
                        ))

                await self.ssh.upload_file(cs_tar, f"/tmp/{CS_FILE}",
                                           progress_callback=_cs_progress)
                self._broadcast(_evt(ProvisionStep.INSTALL_CODE_SERVER, "started",
                                     detail="Extracting..."))
                await self.ssh.run(
                    f"mkdir -p {REMOTE_CODE_SERVER_PATH} && "
                    f"tar xzf /tmp/{CS_FILE} -C {REMOTE_CODE_SERVER_PATH} --strip-components=1 && "
                    f"mkdir -p $HOME/.local/bin && ln -sf {REMOTE_CODE_SERVER_PATH}/bin/code-server $HOME/.local/bin/code-server && "
                    f"rm -f /tmp/{CS_FILE}",
                    timeout=60,
                )
                _, _, verify_ec = await self.ssh.run(
                    f"test -f {REMOTE_CODE_SERVER_PATH}/bin/code-server", timeout=5)
                if verify_ec == 0:
                    yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "completed")
                else:
                    yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "failed",
                               detail="Extraction failed")
            else:
                yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "skipped",
                           detail="code-server.tar.gz not found in deps/")
        else:
            yield _evt(ProvisionStep.CHECK_CODE_SERVER, "completed", detail="Already installed")

