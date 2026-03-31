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

        # Step 2: Check Python on remote (need >= 3.12 for our wheels)
        yield _evt(ProvisionStep.CHECK_PYTHON, "started")
        stdout, _, ec = await self.ssh.run("python3 --version", timeout=10)
        python_ok = False
        if ec == 0:
            # Check version is >= 3.12
            version_str = stdout.strip()  # "Python 3.x.y"
            _, _, ver_ec = await self.ssh.run(
                "python3 -c 'import sys; exit(0 if sys.version_info >= (3,12) else 1)'",
                timeout=5,
            )
            if ver_ec == 0:
                python_ok = True
                yield _evt(ProvisionStep.CHECK_PYTHON, "completed", detail=version_str)
            else:
                yield _evt(ProvisionStep.CHECK_PYTHON, "started",
                           detail=f"{version_str} too old, need >= 3.12")

        if not python_ok:
            yield _evt(ProvisionStep.INSTALL_PYTHON, "started", detail="Deploying Python 3.12 standalone")
            python_tar = os.path.join(DEPS_DIR, "python3-standalone.tar.gz")
            if os.path.exists(python_tar):
                await self.ssh.upload_file(python_tar, "/tmp/python3-standalone.tar.gz")
                await self.ssh.run(f"tar xzf /tmp/python3-standalone.tar.gz -C {REMOTE_PYTHON_INSTALL_PATH}/ && rm /tmp/python3-standalone.tar.gz", timeout=60)
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
                _, _, ec = await self.ssh.run(f"{REMOTE_PYTHON_INSTALL_PATH}/python/bin/python3.12 --version", timeout=5)
                if ec == 0:
                    yield _evt(ProvisionStep.INSTALL_PYTHON, "completed")
                else:
                    yield _evt(ProvisionStep.INSTALL_PYTHON, "failed", detail="Python install failed")
                    return
            else:
                yield _evt(ProvisionStep.INSTALL_PYTHON, "failed", detail="python3-standalone.tar.gz not found")
                return

        # Step 3+4: Install SDK — uses pip install --target (no venv needed)
        if not already_has_sdk:
            has_internet = await self._check_internet()
            venv = self.tmpl["venv_path"]  # e.g. ~/.hiclaw/agent-venv

            if has_internet:
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "skipped", detail="Remote has internet")
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Installing via pip")

                # Ensure pip is available via the standalone Python
                await self.ssh.run(
                    f"$HOME/.local/bin/python3 -m ensurepip --upgrade 2>/dev/null || true",
                    timeout=30,
                )

                # Use mirror if accessible
                _, _, mirror_ec = await self.ssh.run(
                    "curl -s --max-time 3 -o /dev/null https://mirrors.aliyun.com/pypi/simple/",
                    timeout=5,
                )
                mirror_flag = "-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com" if mirror_ec == 0 else ""

                # Install to target dir — only-binary prevents source builds on machines without gcc
                _, stderr, ec = await self.ssh.run(
                    f"$HOME/.local/bin/python3 -m pip install --break-system-packages --upgrade "
                    f"--ignore-installed --only-binary :all: --target {venv}/lib "
                    f"{mirror_flag} {self.tmpl['pip_package']}",
                    timeout=600,
                )
                if ec != 0:
                    yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "failed", detail=stderr[:200])
                    return

                # Create wrapper script so agent-server binary works
                await self.ssh.run(
                    f"mkdir -p {venv}/bin && "
                    f"echo '#!/bin/bash' > {venv}/bin/agent-server && "
                    f"echo 'PYTHONPATH={venv}/lib:$PYTHONPATH exec $HOME/.local/bin/python3 -m openhands.agent_server \"$@\"' >> {venv}/bin/agent-server && "
                    f"chmod +x {venv}/bin/agent-server",
                    timeout=10,
                )
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed")
            else:
                # No internet — upload wheels
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
                           detail=f"Uploading {archive_size_mb}MB (no internet)")

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
                await self.ssh.run(f"mkdir -p {REMOTE_DEPS_PATH} && tar xzf /tmp/agent-wheels.tar.gz -C {REMOTE_DEPS_PATH}/", timeout=60)
                await self.ssh.run("rm -f /tmp/agent-wheels.tar.gz", timeout=5)
                os.remove(wheels_archive)
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "completed", detail=f"{archive_size_mb}MB uploaded")

                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Installing from wheels")
                # Ensure pip is available
                await self.ssh.run(
                    f"$HOME/.local/bin/python3 -m ensurepip --upgrade 2>/dev/null || true",
                    timeout=30,
                )
                # Install to target dir — only-binary prevents source builds
                _, stderr, ec = await self.ssh.run(
                    f"$HOME/.local/bin/python3 -m pip install --break-system-packages --upgrade "
                    f"--ignore-installed --only-binary :all: --target {venv}/lib "
                    f"--no-index --find-links {REMOTE_DEPS_PATH}/wheels/ "
                    f"{self.tmpl['pip_package']}",
                    timeout=300,
                )

                # Create wrapper script
                await self.ssh.run(
                    f"mkdir -p {venv}/bin && "
                    f"echo '#!/bin/bash' > {venv}/bin/agent-server && "
                    f"echo 'PYTHONPATH={venv}/lib:$PYTHONPATH exec $HOME/.local/bin/python3 -m openhands.agent_server \"$@\"' >> {venv}/bin/agent-server && "
                    f"chmod +x {venv}/bin/agent-server",
                    timeout=10,
                )
                if ec != 0:
                    yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "failed", detail=stderr[:200])
                    return
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed")
        else:
            yield _evt(ProvisionStep.CHECK_AGENT_SDK, "completed", detail="Already installed")

        # Step 5: Install code-server (try mirrors first, fallback to direct)
        if not already_has_cs:
            yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "started")
            installed = False

            # Download URLs — try mirrors first, then direct
            CS_FILE = "code-server.tar.gz"
            RELEASE_URL = "https://github.com/yizeng1100-dot/hiclaw/releases/download/deps-v1/code-server.tar.gz"
            mirror_urls = [
                f"https://ghfast.top/{RELEASE_URL}",
                RELEASE_URL,
            ]

            for url in mirror_urls:
                mirror_name = url.split("//")[1].split("/")[0]
                self._broadcast(_evt(ProvisionStep.INSTALL_CODE_SERVER, "started",
                                     detail=f"Trying {mirror_name}..."))
                try:
                    _, _, ec = await self.ssh.run(
                        f"curl -fSL --max-time 600 -o /tmp/{CS_FILE} '{url}'",
                        timeout=620,
                    )
                    if ec == 0:
                        # Extract and install
                        await self.ssh.run(
                            f"mkdir -p {REMOTE_CODE_SERVER_PATH} && "
                            f"tar xzf /tmp/{CS_FILE} -C {REMOTE_CODE_SERVER_PATH} --strip-components=1 && "
                            f"mkdir -p $HOME/.local/bin && ln -sf {REMOTE_CODE_SERVER_PATH}/bin/code-server $HOME/.local/bin/code-server && "
                            f"rm -f /tmp/{CS_FILE}",
                            timeout=60,
                        )
                        _, _, verify_ec = await self.ssh.run("command -v code-server 2>/dev/null || test -f $HOME/.local/bin/code-server || test -f $HOME/.hiclaw/code-server/bin/code-server", timeout=5)
                        if verify_ec == 0:
                            installed = True
                            yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "completed",
                                       detail=f"Installed via {mirror_name}")
                            break
                except Exception:
                    continue

            if not installed:
                # Final fallback: upload from app-server via SFTP
                cs_tar = os.path.join(DEPS_DIR, "code-server.tar.gz")
                if os.path.exists(cs_tar):
                    cs_size_mb = os.path.getsize(cs_tar) // 1024 // 1024
                    self._broadcast(_evt(ProvisionStep.INSTALL_CODE_SERVER, "started",
                                         detail=f"Mirrors failed, uploading from server ({cs_size_mb}MB)"))

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
                    await self.ssh.run(
                        f"mkdir -p {REMOTE_CODE_SERVER_PATH} && "
                        f"tar xzf /tmp/{CS_FILE} -C {REMOTE_CODE_SERVER_PATH} --strip-components=1 && "
                        f"mkdir -p $HOME/.local/bin && ln -sf {REMOTE_CODE_SERVER_PATH}/bin/code-server $HOME/.local/bin/code-server && "
                        f"rm -f /tmp/{CS_FILE}",
                        timeout=60,
                    )
                    _, _, verify_ec = await self.ssh.run("command -v code-server 2>/dev/null || test -f $HOME/.local/bin/code-server || test -f $HOME/.hiclaw/code-server/bin/code-server", timeout=5)
                    if verify_ec == 0:
                        installed = True
                        yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "completed",
                                   detail="Installed via SFTP upload")

                if not installed:
                    yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "skipped",
                               detail="All methods failed, VS Code unavailable")
        else:
            yield _evt(ProvisionStep.CHECK_CODE_SERVER, "completed", detail="Already installed")

    async def _check_internet(self) -> bool:
        """Check if remote machine can reach a pip mirror."""
        # Try aliyun mirror first (fast in China), then pypi
        for url in [
            "https://mirrors.aliyun.com/pypi/simple/",
            "https://pypi.org/simple/",
        ]:
            try:
                stdout, _, ec = await self.ssh.run(
                    f"curl -s --connect-timeout 5 --max-time 8 -o /dev/null -w '%{{http_code}}' {url}",
                    timeout=15,
                )
                if ec == 0 and stdout.strip() in ("200", "301", "302"):
                    return True
            except Exception:
                continue
        return False
