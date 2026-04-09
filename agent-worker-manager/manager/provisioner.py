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
        "pip_package": "openhands-agent-server==1.16.1 openhands-sdk==1.16.1 openhands-tools==1.16.1",
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
        self._host = ssh.host  # for log messages
        self.template = template
        self.tmpl = TEMPLATES.get(template, TEMPLATES["openhands"])
        self._broadcast = broadcast_fn or (lambda evt: None)

    async def _check_remote(self, cmd: str) -> bool:
        """Run a check command on remote, return True if exit code is 0."""
        _, _, ec = await self.ssh.run(cmd, timeout=5)
        return ec == 0

    async def _write_wrapper_scripts(self, venv: str, remote_python: str) -> None:
        """Write _launcher.py and agent-server wrapper script on remote machine.

        _launcher.py monkey-patches PUBLIC_SKILLS_REPO before starting agent-server,
        redirecting the SDK's github.com clone to the internal Gitea instance.
        """
        await self.ssh.run(
            f"mkdir -p {venv}/bin && "
            f"cat > {venv}/bin/_launcher.py << 'PYEOF'\n"
            "import os, sys, logging\n"
            "venv_lib = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib')\n"
            "if venv_lib not in sys.path:\n"
            "    sys.path.insert(0, venv_lib)\n"
            "#\n"
            "# === HiClaw patches (run before agent-server imports) ===\n"
            "#\n"
            "# 1. Force httpx connect timeout\n"
            "try:\n"
            "    import httpx\n"
            "    httpx._config.DEFAULT_TIMEOUT_CONFIG = httpx.Timeout(connect=10, read=60, write=30, pool=10)\n"
            "except Exception: pass\n"
            "#\n"
            "# 2. Enable ALL litellm/httpx logging at DEBUG level\n"
            "#    This prints full request URL, headers, and error details to stdout\n"
            "logging.basicConfig(level=logging.DEBUG, format='%(name)s %(levelname)s %(message)s', stream=sys.stdout)\n"
            "for name in ['LiteLLM', 'litellm', 'httpx', 'httpcore']:\n"
            "    logging.getLogger(name).setLevel(logging.DEBUG)\n"
            "#\n"
            "# 3. litellm verbose mode — prints to stdout directly\n"
            "try:\n"
            "    import litellm\n"
            "    litellm.set_verbose = True\n"
            "except Exception: pass\n"
            "#\n"
            "# 4. Monkey-patch SDK retry log to show cause chain\n"
            "try:\n"
            "    from openhands.sdk.llm.utils import retry_mixin as _rm\n"
            "    _orig = _rm.RetryMixin.log_retry_attempt\n"
            "    def _patched(self, rs):\n"
            "        _orig(self, rs)\n"
            "        exc = rs.outcome.exception() if rs.outcome else None\n"
            "        if not exc: return\n"
            "        c = exc.__cause__\n"
            "        d = 0\n"
            "        while c and d < 5:\n"
            "            print(f'[LLM_ERROR] cause[{d}] {type(c).__name__}: {c}', flush=True)\n"
            "            c = getattr(c, '__cause__', None)\n"
            "            d += 1\n"
            "        if hasattr(exc, 'response') and exc.response is not None:\n"
            "            print(f'[LLM_ERROR] HTTP {getattr(exc.response, \"status_code\", \"?\")}: {getattr(exc.response, \"text\", \"\")[:2000]}', flush=True)\n"
            "    _rm.RetryMixin.log_retry_attempt = _patched\n"
            "except Exception: pass\n"
            "#\n"
            "print('[HiClaw] All patches applied', flush=True)\n"
            "from openhands.agent_server.__main__ import main\n"
            "sys.exit(main())\n"
            "PYEOF\n", timeout=10)
        await self.ssh.run(
            f"cat > {venv}/bin/agent-server << 'WRAPPER_EOF'\n"
            f"#!/bin/bash\n"
            f"export PYTHONPATH={venv}/lib:$PYTHONPATH\n"
            f"# Append to no_proxy (don't overwrite — keep system proxy for LLM)\n"
            f"export no_proxy=\"${{no_proxy:+$no_proxy,}}localhost,127.0.0.1\"\n"
            f"export NO_PROXY=\"${{NO_PROXY:+$NO_PROXY,}}localhost,127.0.0.1\"\n"
            f"exec {remote_python} {venv}/bin/_launcher.py \"$@\"\n"
            f"WRAPPER_EOF\n"
            f"chmod +x {venv}/bin/agent-server", timeout=10)
        logger.info(f"[{self._host}] Wrapper scripts written: {venv}/bin/agent-server + _launcher.py")

    async def provision(self) -> AsyncGenerator[ProvisionEvent, None]:
        """Run all provisioning steps. Each step checks remote state first, skips if already done."""

        # >>> CUSTOM: HiClaw — resolve remote $HOME and create temp/logs dirs <<<
        home_out, _, _ = await self.ssh.run("echo $HOME", timeout=5)
        remote_home = home_out.strip() or "/root"
        remote_tmp = f"{remote_home}/.hiclaw/tmp"
        remote_logs = f"{remote_home}/.hiclaw/logs"
        await self.ssh.run(f"mkdir -p {remote_tmp} {remote_logs}", timeout=5)
        # >>> END CUSTOM <<<

        # ── Step 1: Python ──
        # Check: standalone 3.12 exists? OR system python >= 3.12?
        standalone_python = f"{REMOTE_PYTHON_INSTALL_PATH}/python/bin/python3.12".replace("$HOME", "~")
        has_standalone = await self._check_remote(f"test -f {standalone_python}")
        remote_python = "python3"
        python_ok = False

        if has_standalone:
            # >>> CUSTOM: HiClaw — verify it actually works <<<
            py_ver, _, py_ec = await self.ssh.run(f"{standalone_python} --version 2>&1", timeout=5)
            if py_ec == 0 and "3.12" in py_ver:
                remote_python = standalone_python
                python_ok = True
                yield _evt(ProvisionStep.CHECK_PYTHON, "completed", detail=f"Python 3.12 verified: {py_ver.strip()}")
                logger.info(f"[{self._host}] Python 3.12 verified at {standalone_python}")
            else:
                # Exists but broken — clean up all Python locations
                logger.warning(f"[{self._host}] Standalone Python broken (ec={py_ec}): {py_ver.strip()}")
                yield _evt(ProvisionStep.CHECK_PYTHON, "started", detail="Existing Python broken, will reinstall...")
                await self.ssh.run(
                    f"rm -rf {REMOTE_PYTHON_INSTALL_PATH}/python "
                    f"~/.hiclaw/agent-deps/python3-standalone",  # old path
                    timeout=15)
            # >>> END CUSTOM <<<
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
                await self.ssh.upload_file(python_tar, f"{remote_tmp}/python3-standalone.tar.gz",
                                           progress_callback=_py_progress)
                self._broadcast(_evt(ProvisionStep.INSTALL_PYTHON, "started",
                                     detail="Extracting..."))
                await self.ssh.run(f"mkdir -p {REMOTE_PYTHON_INSTALL_PATH} && tar xzf {remote_tmp}/python3-standalone.tar.gz -C {REMOTE_PYTHON_INSTALL_PATH}/ && rm {remote_tmp}/python3-standalone.tar.gz", timeout=120)
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
                py_ver_out, _, ec = await self.ssh.run(f"{remote_python} --version 2>&1", timeout=5)
                if ec == 0 and "3.12" in py_ver_out:
                    yield _evt(ProvisionStep.INSTALL_PYTHON, "completed",
                               detail=py_ver_out.strip())
                else:
                    yield _evt(ProvisionStep.INSTALL_PYTHON, "failed",
                               detail=f"Python verify failed (ec={ec}): {py_ver_out.strip()}")
                    return
            else:
                yield _evt(ProvisionStep.INSTALL_PYTHON, "failed", detail="python3-standalone.tar.gz not found")
                return

        # ── Step 2: Agent SDK ──
        # Check: binary exists AND actually works (import test) AND version matches expected
        binary = self.tmpl["binary"].replace("$HOME", "~")
        venv = self.tmpl["venv_path"]
        has_sdk = await self._check_remote(
            f"test -f {binary} || test -f /opt/agent-venv/bin/agent-server"
        )
        sdk_healthy = False
        # >>> CUSTOM: HiClaw — track whether to force re-upload wheels <<<
        force_reupload_wheels = False
        # >>> END CUSTOM <<<
        # >>> CUSTOM: HiClaw — extract expected version from pip_package for comparison <<<
        # pip_package example: "openhands-agent-server==1.16.1 openhands-sdk==1.16.1 ..."
        import re as _re
        _m = _re.search(r"openhands-sdk==(\S+)", self.tmpl.get("pip_package", ""))
        expected_sdk_version = _m.group(1) if _m else None
        # >>> END CUSTOM <<<
        if has_sdk:
            # >>> CUSTOM: HiClaw — verify ALL critical imports work AND version matches <<<
            # Must check openhands.tools AND a sample dependency (binaryornot) too,
            # otherwise broken installs (missing tools or deps) will be reused.
            verify_out, _, verify_ec = await self.ssh.run(
                f"PYTHONPATH={venv}/lib {remote_python} -c '"
                "import openhands.agent_server; "
                "import openhands.sdk; "
                "import openhands.tools; "
                "import binaryornot; "
                "import importlib.metadata; "
                "print(\"VERIFY_OK\", importlib.metadata.version(\"openhands-sdk\"))"
                "' 2>&1", timeout=15)
            installed_version = None
            if "VERIFY_OK" in verify_out:
                try:
                    installed_version = verify_out.split("VERIFY_OK", 1)[1].strip().split()[0]
                except Exception:
                    installed_version = None
            version_matches = (
                expected_sdk_version is not None
                and installed_version == expected_sdk_version
            )
            if "VERIFY_OK" in verify_out and version_matches:
                sdk_healthy = True
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "skipped",
                           detail=f"Already installed v{installed_version}")
                # Always regenerate wrapper scripts (ensure monkey-patch is up to date)
                await self._write_wrapper_scripts(venv, remote_python)
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed",
                           detail=f"Already installed v{installed_version} & verified")
                logger.info(f"[{self._host}] SDK: v{installed_version} already installed, wrapper regenerated")
            else:
                # Binary exists but broken OR outdated — clean up everything and reinstall
                if "VERIFY_OK" in verify_out and not version_matches:
                    reason = f"version mismatch: installed={installed_version}, expected={expected_sdk_version}"
                    logger.warning(f"[{self._host}] SDK {reason}, upgrading")
                    yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started",
                               detail=f"Upgrading: {reason}")
                else:
                    logger.warning(f"[{self._host}] SDK binary broken: {verify_out.strip()[-200:]}")
                    yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started",
                               detail="Existing install is broken, cleaning up and reinstalling...")
                # >>> CUSTOM: HiClaw — force-clean wheels too, then verify removal <<<
                await self.ssh.run(
                    f"rm -rf {venv} {REMOTE_DEPS_PATH}/wheels "
                    f"/opt/agent-venv "  # legacy path
                    f"~/.hiclaw/agent-deps/python3-standalone",  # old python path
                    timeout=30)
                # Verify cleanup actually removed the wheels dir
                check_cleanup, _, _ = await self.ssh.run(
                    f"test -d {REMOTE_DEPS_PATH}/wheels && echo STILL_THERE || echo CLEAN",
                    timeout=5,
                )
                if "STILL_THERE" in check_cleanup:
                    # Force re-create as empty so the upload path runs
                    await self.ssh.run(
                        f"rm -rf {REMOTE_DEPS_PATH}/wheels && mkdir -p {REMOTE_DEPS_PATH}",
                        timeout=10,
                    )
                # >>> END CUSTOM <<<
                logger.info(f"[{self._host}] Cleaned up old SDK install")
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started",
                           detail="Cleanup done. Re-uploading and reinstalling...")
                # >>> CUSTOM: HiClaw — mark that we MUST re-upload after broken install <<<
                force_reupload_wheels = True
            # >>> END CUSTOM <<<

        if not sdk_healthy:
            # >>> CUSTOM: HiClaw — re-upload wheels if forced OR not present <<<
            has_wheels = (
                False if force_reupload_wheels
                else await self._check_remote(f"test -d {REMOTE_DEPS_PATH}/wheels")
            )
            if has_wheels:
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "skipped", detail="Wheels already on remote")
                logger.info(f"[{self._host}] SDK wheels already on remote, skipping upload")
            # >>> END CUSTOM <<<
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
                await self.ssh.upload_file(wheels_archive, f"{remote_tmp}/agent-wheels.tar.gz",
                                           progress_callback=_on_progress)
                await self.ssh.run(
                    f"mkdir -p {REMOTE_DEPS_PATH} && "
                    f"tar xzf {remote_tmp}/agent-wheels.tar.gz -C {REMOTE_DEPS_PATH}/ && "
                    f"rm -f {remote_tmp}/agent-wheels.tar.gz", timeout=60)
                os.remove(wheels_archive)
                yield _evt(ProvisionStep.SCP_DEPENDENCIES, "completed", detail=f"{archive_size_mb}MB uploaded")

            # Install SDK from wheels
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Installing from wheels")

            # Pip commands need no_proxy to avoid corporate proxy interference
            pip_env = "no_proxy=localhost,127.0.0.1 NO_PROXY=localhost,127.0.0.1"

            # Step 2a: Ensure pip is available
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Setting up pip...")
            await self.ssh.run(f"{pip_env} {remote_python} -m ensurepip --upgrade 2>/dev/null || true", timeout=30)
            await self.ssh.run(
                f"{pip_env} {remote_python} -m pip install --break-system-packages --upgrade "
                f"--no-index --find-links {REMOTE_DEPS_PATH}/wheels/ "
                f"pip setuptools wheel 2>&1 || true", timeout=60)

            # Step 2b: Install all wheels with --no-deps first (avoid resolution failures)
            # Use -q (quiet) to reduce output volume — large output can block SSH channel
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Installing packages (pass 1/2)...")
            stdout_all, stderr, ec = await self.ssh.run(
                f"{pip_env} {remote_python} -m pip install -q --break-system-packages --upgrade "
                f"--ignore-installed --prefer-binary --target {venv}/lib "
                f"--no-index --no-deps --find-links {REMOTE_DEPS_PATH}/wheels/ "
                f"{REMOTE_DEPS_PATH}/wheels/*.whl 2>&1; echo EXIT_CODE=$?", timeout=600)
            logger.info(f"[{self._host}] Pip pass 1 tail: {stdout_all[-300:]}")

            # >>> CUSTOM: HiClaw — aggressive clean before pass 2 <<<
            # pip --target with shared namespace packages is unreliable across
            # pip versions. Clean ALL openhands stuff completely first, then
            # use --upgrade to force pip to write fresh files.
            await self.ssh.run(
                f"rm -rf {venv}/lib/openhands "
                f"{venv}/lib/openhands_aci* "
                f"{venv}/lib/openhands_sdk* "
                f"{venv}/lib/openhands_tools* "
                f"{venv}/lib/openhands_agent_server* "
                f"{venv}/lib/binaryornot*",
                timeout=15,
            )
            # >>> END CUSTOM <<<

            # Step 2c: Install openhands wheels EXPLICITLY by file path WITH deps.
            # Use file paths (not package names) to avoid shared-namespace
            # confusion. Use --upgrade to force pip to replace any leftover files.
            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "started", detail="Installing packages (pass 2/2)...")
            stdout2, stderr2, ec2 = await self.ssh.run(
                f"{pip_env} {remote_python} -m pip install -q --break-system-packages --upgrade "
                f"--prefer-binary --target {venv}/lib "
                f"--no-index --find-links {REMOTE_DEPS_PATH}/wheels/ "
                f"{REMOTE_DEPS_PATH}/wheels/openhands_aci-*.whl "
                f"{REMOTE_DEPS_PATH}/wheels/openhands_sdk-*.whl "
                f"{REMOTE_DEPS_PATH}/wheels/openhands_tools-*.whl "
                f"{REMOTE_DEPS_PATH}/wheels/openhands_agent_server-*.whl "
                f"2>&1; echo EXIT_CODE=$?", timeout=600)
            # Parse real exit code from output (since we used ; instead of &&)
            ec2 = 1
            if "EXIT_CODE=0" in stdout2:
                ec2 = 0
            logger.info(f"[{self._host}] Pip pass 2 tail: {stdout2[-300:]}")

            # Step 2d: Verify core import works
            check_out, _, _ = await self.ssh.run(
                f"PYTHONPATH={venv}/lib {remote_python} -c 'import openhands.agent_server; print(\"OK\")' 2>&1",
                timeout=10)
            if "OK" not in check_out:
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "failed",
                           detail=f"Core import failed: {check_out.strip()[-1000:]}\n\npip output: {(stdout2 + stderr2).strip()[-1000:]}")
                return
            if ec2 != 0:
                logger.warning(f"[{self._host}] Some optional packages failed, but core SDK OK")
            # >>> CUSTOM: HiClaw — wrapper script that patches PUBLIC_SKILLS_REPO <<<
            # Uses a Python launcher script instead of `python -m openhands.agent_server`
            # so we can monkey-patch the SDK constant before the server starts.
            # Write wrapper scripts (launcher + shell wrapper)
            await self._write_wrapper_scripts(venv, remote_python)
            # >>> END CUSTOM <<<

            # >>> CUSTOM: HiClaw — final verification: can agent-server actually run? <<<
            verify_out, _, verify_ec = await self.ssh.run(
                f"PYTHONPATH={venv}/lib {remote_python} -c '"
                "import openhands.agent_server; "
                "import openhands.sdk; "
                "import openhands.tools; "
                "import binaryornot; "
                "print(\"VERIFY_OK\")"
                "' 2>&1", timeout=15)
            if "VERIFY_OK" not in verify_out:
                # Diagnostic: list what's actually in the venv to understand what pip did
                ls_out, _, _ = await self.ssh.run(
                    f"echo '=== openhands/ contents ==='; "
                    f"ls {venv}/lib/openhands/ 2>&1; "
                    f"echo '=== openhands_*.dist-info ==='; "
                    f"ls -d {venv}/lib/openhands_* 2>&1; "
                    f"echo '=== binaryornot ==='; "
                    f"ls -d {venv}/lib/binaryornot* 2>&1; "
                    f"echo '=== pip output tail ==='; "
                    f"echo {stdout2[-800:]!r}",
                    timeout=10,
                )
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "failed",
                           detail=f"Post-install verify failed: {verify_out.strip()[-300:]}\n\nDiagnostic:\n{ls_out.strip()[-1500:]}")
                return
            # Also verify the binary wrapper works
            binary_check, _, binary_ec = await self.ssh.run(
                f"{venv}/bin/agent-server --help 2>&1 | head -3", timeout=10)
            if binary_ec != 0 and "usage" not in binary_check.lower() and "error" not in binary_check.lower():
                yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "failed",
                           detail=f"agent-server binary check failed (ec={binary_ec}): {binary_check.strip()[-500:]}")
                return
            logger.info(f"[{self._host}] SDK install verified: imports OK, binary OK")
            # >>> END CUSTOM <<<

            yield _evt(ProvisionStep.INSTALL_AGENT_SDK, "completed")

        # ── Step 2.5: Deploy public skills to user skills dir ──
        # >>> CUSTOM: HiClaw — transfer extensions via SSH to ~/.openhands/skills/ <<<
        # Deploy skills as "user skills" so SDK loads them directly from filesystem.
        # App-server passes load_public=false for remote workers, preventing any
        # git clone/fetch from GitHub. Zero network dependency for skills.
        extensions_bundle = os.path.join(DEPS_DIR, "openhands-extensions.bundle")
        if os.path.exists(extensions_bundle):
            user_skills = f"{remote_home}/.openhands/skills"
            has_skills = await self._check_remote(
                f"find {user_skills} -name '*.md' -type f 2>/dev/null | head -1 | grep -q ."
            )
            if not has_skills:
                bundle_size_kb = os.path.getsize(extensions_bundle) // 1024
                logger.info(f"[{self._host}] Uploading public skills bundle ({bundle_size_kb}KB) to user skills dir")
                await self.ssh.upload_file(
                    extensions_bundle,
                    f"{remote_tmp}/openhands-extensions.bundle",
                )
                await self.ssh.run(
                    f"git clone {remote_tmp}/openhands-extensions.bundle {remote_tmp}/_extensions 2>&1 && "
                    f"mkdir -p {user_skills} && "
                    f"cp -r {remote_tmp}/_extensions/skills/* {user_skills}/ 2>/dev/null; "
                    f"rm -rf {remote_tmp}/_extensions {remote_tmp}/openhands-extensions.bundle",
                    timeout=30,
                )
                _ok = await self._check_remote(
                    f"find {user_skills} -name '*.md' -type f 2>/dev/null | head -1 | grep -q ."
                )
                logger.info(f"[{self._host}] Public skills deploy: {'OK' if _ok else 'FAILED'}")
            else:
                logger.info(f"[{self._host}] User skills already exist, skipping upload")
        else:
            logger.info(f"[{self._host}] No extensions bundle at {extensions_bundle}, skipping")
        # >>> END CUSTOM <<<

        # ── Step 3: code-server ──
        # Check: code-server binary exists?
        cs_path = REMOTE_CODE_SERVER_PATH.replace("$HOME", "~")
        has_cs = await self._check_remote(f"test -f {cs_path}/bin/code-server")
        if has_cs:
            yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "completed", detail="Already installed")
            logger.info(f"[{self._host}] code-server already installed, skipping")
        else:
            CS_FILE = "code-server.tar.gz"
            cs_tar = os.path.join(DEPS_DIR, CS_FILE)
            if os.path.exists(cs_tar):
                cs_size_mb = os.path.getsize(cs_tar) // 1024 // 1024
                yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "started",
                           detail=f"Uploading ({cs_size_mb}MB)")
                last_mb = [0]
                def _cs_progress(sent, total):
                    sent_mb = sent // 1024 // 1024
                    if sent_mb > last_mb[0]:
                        last_mb[0] = sent_mb
                        pct = int(sent * 100 / total) if total else 0
                        self._broadcast(_evt(ProvisionStep.INSTALL_CODE_SERVER, "started",
                                             detail=f"Uploading {sent_mb}/{cs_size_mb}MB ({pct}%)"))
                await self.ssh.upload_file(cs_tar, f"{remote_tmp}/{CS_FILE}", progress_callback=_cs_progress)
                self._broadcast(_evt(ProvisionStep.INSTALL_CODE_SERVER, "started", detail="Extracting..."))
                await self.ssh.run(
                    f"mkdir -p {REMOTE_CODE_SERVER_PATH} && "
                    f"tar xzf {remote_tmp}/{CS_FILE} -C {REMOTE_CODE_SERVER_PATH} --strip-components=1 && "
                    f"mkdir -p $HOME/.local/bin && ln -sf {REMOTE_CODE_SERVER_PATH}/bin/code-server $HOME/.local/bin/code-server && "
                    f"rm -f {remote_tmp}/{CS_FILE}", timeout=60)
                if await self._check_remote(f"test -f {REMOTE_CODE_SERVER_PATH}/bin/code-server"):
                    yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "completed")
                else:
                    yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "failed", detail="Extraction failed")
            else:
                yield _evt(ProvisionStep.INSTALL_CODE_SERVER, "skipped",
                           detail="code-server.tar.gz not in deps/")

