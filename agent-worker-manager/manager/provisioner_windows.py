"""Windows provisioner — deploys agent-server to Windows remotes via PowerShell.

Scope (v2 — full auto-deploy):
- Claude mode ONLY. The OpenHands default engine is NOT exercised on Windows.
- PowerShell-only command strategy. Bash-on-Windows (Git Bash / WSL) is not
  auto-detected — if the remote has no Python we push our own embed zip from
  `deps/python-windows-embed.zip` into `%USERPROFILE%\\.hiclaw\\python`.
- code-server is NOT installed on Windows (users can run local VS Code).
- Claude CLI IS auto-deployed. We ship `deps/claude-cli-bundle-windows.zip`
  (portable Node.js + `@anthropic-ai/claude-code` + a generated `claude.cmd`
  wrapper), extract it into `%USERPROFILE%\\.local\\`, and verify with
  `claude --version`. The agent-server.cmd wrapper puts
  `%USERPROFILE%\\.local\\bin` on PATH so the SDK can subprocess `claude`
  directly. Login (`claude login`) is still a manual one-off step for the
  user, mirroring the Linux flow — the provisioner does NOT handle OAuth.
- Skills are NOT pre-loaded on Windows (v1 behavior preserved): only an
  empty `%USERPROFILE%\\.openhands\\skills` directory is created.

Conventions:
- All remote paths are written with `/` forward slashes (PowerShell accepts
  them) to keep the f-string templates simple.
- Expanded user-profile path is stored in `self._userprofile` after the
  first `echo $env:USERPROFILE` call — reused everywhere as an absolute
  Windows path (e.g. `C:/Users/admin`).
- Per-port PID file lives at `<userprofile>/.hiclaw/agent-server-<port>.pid`.
"""

from __future__ import annotations

import logging
import os
import re
from typing import AsyncGenerator

from .models import ProvisionEvent, ProvisionStep
from .provisioner_base import (
    BUNDLE_PATH_WINDOWS,
    CLAUDE_CLI_BUNDLE_WINDOWS,
    PYTHON_EMBED_WINDOWS,
    ProvisionerBase,
    _evt,
)

logger = logging.getLogger(__name__)


# Relative-to-userprofile paths. Linux layout mirrors $HOME/.hiclaw/... —
# we keep the same directory name on Windows for consistency, just under
# the Windows userprofile.
_REL_HICLAW = '.hiclaw'
_REL_VENV_LIB = '.hiclaw/agent-venv/lib'
_REL_VENV_BIN = '.hiclaw/agent-venv/bin'
_REL_DEPS = '.hiclaw/agent-deps'
_REL_WHEELS = '.hiclaw/agent-deps/wheels'
_REL_PYTHON = '.hiclaw/python'
_REL_LOGS = '.hiclaw/logs'
_REL_TMP = '.hiclaw/tmp'


def _ps(command: str) -> str:
    """Wrap a PowerShell command so we can ssh.run() it directly.

    OpenSSH on Windows Server typically routes SSH commands through cmd.exe
    by default. We explicitly invoke powershell.exe with -NoProfile so:
      - ~/.powershell profile scripts don't interfere
      - encoding is predictable (utf-8 output)

    The command string is passed via `-Command` which requires double-escaping
    any literal double quotes — callers should use single quotes inside
    PowerShell strings where possible.
    """
    # Note: we leave newlines intact; PowerShell handles multi-line -Command
    # fine when the whole blob is quoted.
    return f'powershell.exe -NoProfile -NonInteractive -Command "{command}"'


class WindowsProvisioner(ProvisionerBase):
    """Deploys agent-server to a Windows remote via SSH + PowerShell."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cached after first probe — absolute Windows userprofile path like
        # "C:/Users/admin". Stored with forward slashes because PS accepts them
        # and it keeps f-string templating simple.
        self._userprofile: str | None = None

    # ------------------------------------------------------------
    # Path helpers (depend on self._userprofile, so populate it first
    # via _probe_userprofile)
    # ------------------------------------------------------------

    def _up(self) -> str:
        """Return the cached %USERPROFILE% path. Must be called AFTER probe."""
        if not self._userprofile:
            raise RuntimeError(
                'WindowsProvisioner._up() called before probing userprofile'
            )
        return self._userprofile

    def _venv(self) -> str:
        return f'{self._up()}/{_REL_VENV_LIB.rsplit("/", 1)[0]}'  # .../agent-venv

    def _venv_lib(self) -> str:
        return f'{self._up()}/{_REL_VENV_LIB}'

    def _venv_bin(self) -> str:
        return f'{self._up()}/{_REL_VENV_BIN}'

    def _deps_dir(self) -> str:
        return f'{self._up()}/{_REL_DEPS}'

    def _wheels_dir(self) -> str:
        return f'{self._up()}/{_REL_WHEELS}'

    def _python_dir(self) -> str:
        return f'{self._up()}/{_REL_PYTHON}'

    def _python_exe(self) -> str:
        return f'{self._python_dir()}/python.exe'

    def _tmp_dir(self) -> str:
        return f'{self._up()}/{_REL_TMP}'

    def _logs_dir(self) -> str:
        return f'{self._up()}/{_REL_LOGS}'

    def _pid_file(self, port: int) -> str:
        return f'{self._up()}/{_REL_HICLAW}/agent-server-{port}.pid'

    # ------------------------------------------------------------
    # Probes
    # ------------------------------------------------------------

    async def _probe_userprofile(self) -> str:
        """Resolve the remote's %USERPROFILE% path and cache it.

        We convert backslashes to forward slashes immediately so all downstream
        path manipulation can use a single separator.
        """
        out, _, _ = await self.ssh.run(_ps('Write-Host $env:USERPROFILE'), timeout=10)
        userprofile = (out or '').strip().replace('\\', '/')
        if not userprofile:
            raise RuntimeError('Could not resolve remote %USERPROFILE% via PowerShell')
        self._userprofile = userprofile
        logger.info(f'[{self._host}] Remote %USERPROFILE% = {userprofile}')
        return userprofile

    async def _detect_python(self) -> str | None:
        """Return absolute path of a usable Python 3.12 on the remote, or None.

        Probe order:
          1. Our own standalone embed at `<userprofile>/.hiclaw/python/python.exe`
          2. `python.exe` on PATH (`where.exe python`)
          3. `py -3.12` (Python launcher)
        """
        # 1. Standalone embed
        embed_py = self._python_exe()
        out, _, _ = await self.ssh.run(
            _ps(
                f"if (Test-Path '{embed_py}') {{ & '{embed_py}' --version }} else {{ 'missing' }}"
            ),
            timeout=10,
        )
        if '3.12' in out:
            return embed_py

        # 2. python on PATH
        out, _, ec = await self.ssh.run(_ps('python --version 2>&1'), timeout=10)
        if ec == 0 and '3.12' in out:
            # Get the absolute path
            path_out, _, _ = await self.ssh.run(
                _ps('(Get-Command python).Source'), timeout=5
            )
            return (path_out or 'python').strip().replace('\\', '/')

        # 3. py launcher
        out, _, ec = await self.ssh.run(_ps('py -3.12 --version 2>&1'), timeout=10)
        if ec == 0 and '3.12' in out:
            return 'py -3.12'

        return None

    # ------------------------------------------------------------
    # Main provision flow
    # ------------------------------------------------------------

    async def provision(self) -> AsyncGenerator[ProvisionEvent, None]:
        # Step 0: resolve userprofile + create scratch dirs
        try:
            await self._probe_userprofile()
        except Exception as e:
            yield _evt(
                ProvisionStep.SSH_CONNECT,
                'failed',
                detail=f'Could not resolve remote %USERPROFILE%: {e}',
            )
            return

        await self.ssh.run(
            _ps(
                f'New-Item -ItemType Directory -Force -Path '
                f"'{self._tmp_dir()}','{self._logs_dir()}','{self._deps_dir()}' | Out-Null"
            ),
            timeout=15,
        )

        # ── Step 1: Check Python ──
        remote_python = await self._detect_python()
        if remote_python:
            yield _evt(
                ProvisionStep.CHECK_PYTHON,
                'completed',
                detail=f'Python 3.12 found at {remote_python}',
            )
        else:
            yield _evt(
                ProvisionStep.CHECK_PYTHON,
                'started',
                detail='No Python 3.12 found, will deploy embed zip',
            )
            # ── Step 1.5: Install Python embed if we shipped one ──
            if not os.path.exists(PYTHON_EMBED_WINDOWS):
                yield _evt(
                    ProvisionStep.INSTALL_PYTHON,
                    'failed',
                    detail=(
                        f'No Python 3.12 on remote AND no '
                        f'{os.path.basename(PYTHON_EMBED_WINDOWS)} in deps/. '
                        f'Run on the build machine:\n'
                        f'  python -m manager.dep_builder build-python-windows'
                    ),
                )
                return

            size_mb = os.path.getsize(PYTHON_EMBED_WINDOWS) // 1024 // 1024
            yield _evt(
                ProvisionStep.INSTALL_PYTHON,
                'started',
                detail=f'Uploading Python embed ({size_mb}MB)',
            )
            remote_zip = f'{self._tmp_dir()}/python-embed.zip'
            last_mb = [0]

            def _py_progress(sent, total):
                sent_mb = sent // 1024 // 1024
                if sent_mb > last_mb[0]:
                    last_mb[0] = sent_mb
                    pct = int(sent * 100 / total) if total else 0
                    self._broadcast(
                        _evt(
                            ProvisionStep.INSTALL_PYTHON,
                            'started',
                            detail=f'Uploading {sent_mb}/{size_mb}MB ({pct}%)',
                        )
                    )

            await self.ssh.upload_file(
                PYTHON_EMBED_WINDOWS, remote_zip, progress_callback=_py_progress
            )
            self._broadcast(
                _evt(ProvisionStep.INSTALL_PYTHON, 'started', detail='Extracting...')
            )
            await self.ssh.run(
                _ps(
                    f"Remove-Item -Recurse -Force '{self._python_dir()}' -ErrorAction SilentlyContinue; "
                    f"Expand-Archive -Path '{remote_zip}' -DestinationPath '{self._python_dir()}' -Force; "
                    f"Remove-Item '{remote_zip}' -Force"
                ),
                timeout=180,
            )
            # Enable site-packages in the embed distribution so pip can import:
            # we need to uncomment `import site` in python3NN._pth.
            await self.ssh.run(
                _ps(
                    f"Get-ChildItem '{self._python_dir()}' -Filter 'python*._pth' | "
                    f'ForEach-Object {{ '
                    f"(Get-Content $_.FullName) -replace '^#\\s*import site','import site' | "
                    f'Set-Content $_.FullName }}'
                ),
                timeout=10,
            )
            remote_python = self._python_exe()

            # Bootstrap pip. The Windows embed distribution does NOT ship
            # with pip; dep_builder bundles `get-pip.py` alongside
            # `python.exe`. Running it drops pip into
            # `<python_dir>/Lib/site-packages/` and creates console scripts
            # in `<python_dir>/Scripts/`. Without this step the next
            # INSTALL_AGENT_SDK command (`python -m pip install ...`) fails
            # with "No module named pip" and returns exit code 1.
            get_pip = f'{self._python_dir()}/get-pip.py'
            self._broadcast(
                _evt(
                    ProvisionStep.INSTALL_PYTHON,
                    'started',
                    detail='Bootstrapping pip...',
                )
            )
            pip_boot_out, _, pip_boot_ec = await self.ssh.run(
                _ps(
                    f"& '{remote_python}' '{get_pip}' "
                    f'--no-warn-script-location --disable-pip-version-check 2>&1'
                ),
                timeout=180,
            )
            if pip_boot_ec != 0:
                yield _evt(
                    ProvisionStep.INSTALL_PYTHON,
                    'failed',
                    detail=(
                        f'pip bootstrap failed (ec={pip_boot_ec}): '
                        f'{pip_boot_out.strip()[-500:]}'
                    ),
                )
                return

            # Verify
            ver_out, _, ec = await self.ssh.run(
                _ps(f"& '{remote_python}' --version 2>&1"), timeout=10
            )
            if ec != 0 or '3.12' not in ver_out:
                yield _evt(
                    ProvisionStep.INSTALL_PYTHON,
                    'failed',
                    detail=f'Python verify failed (ec={ec}): {ver_out.strip()[:300]}',
                )
                return
            yield _evt(
                ProvisionStep.INSTALL_PYTHON,
                'completed',
                detail=ver_out.strip(),
            )

        # ── Step 2: Upload + install wheels ──
        if not os.path.exists(BUNDLE_PATH_WINDOWS):
            yield _evt(
                ProvisionStep.SCP_DEPENDENCIES,
                'failed',
                detail=(
                    f'{os.path.basename(BUNDLE_PATH_WINDOWS)} not found in deps/. '
                    f'Run `python -m manager.dep_builder build-windows` on a '
                    f'machine with network access first.'
                ),
            )
            return

        archive_size_mb = os.path.getsize(BUNDLE_PATH_WINDOWS) // 1024 // 1024
        yield _evt(
            ProvisionStep.SCP_DEPENDENCIES,
            'started',
            detail=f'Uploading wheels bundle ({archive_size_mb}MB)',
        )
        remote_zip = f'{self._tmp_dir()}/agent-deps-windows.zip'
        last_mb = [0]

        def _wheels_progress(sent, total):
            sent_mb = sent // 1024 // 1024
            if sent_mb > last_mb[0]:
                last_mb[0] = sent_mb
                pct = int(sent * 100 / total) if total else 0
                self._broadcast(
                    _evt(
                        ProvisionStep.SCP_DEPENDENCIES,
                        'started',
                        detail=f'{sent_mb}/{archive_size_mb}MB ({pct}%)',
                    )
                )

        await self.ssh.upload_file(
            BUNDLE_PATH_WINDOWS, remote_zip, progress_callback=_wheels_progress
        )
        await self.ssh.run(
            _ps(
                f"Remove-Item -Recurse -Force '{self._wheels_dir()}' -ErrorAction SilentlyContinue; "
                f"Expand-Archive -Path '{remote_zip}' -DestinationPath '{self._deps_dir()}' -Force; "
                f"Remove-Item '{remote_zip}' -Force"
            ),
            timeout=180,
        )
        yield _evt(
            ProvisionStep.SCP_DEPENDENCIES,
            'completed',
            detail=f'{archive_size_mb}MB uploaded + extracted',
        )

        # ── Step 3: pip install (single pass, --target, --no-deps not usable
        #           because we DO want deps resolved from the local wheels dir)
        yield _evt(
            ProvisionStep.INSTALL_AGENT_SDK,
            'started',
            detail='Installing packages...',
        )
        # Kill any lingering python.exe from a previous attempt — their
        # loaded .pyd files would be locked, causing Remove-Item to skip
        # them and pip to not re-extract the adjacent .py files.
        await self.ssh.run(
            _ps(
                f'Get-Process python* -ErrorAction SilentlyContinue | '
                f"Where-Object {{ $_.Path -like '*{self._up()}*' }} | "
                f'Stop-Process -Force -ErrorAction SilentlyContinue'
            ),
            timeout=10,
        )
        # Clean out any prior install so mismatched package sets can't linger.
        await self.ssh.run(
            _ps(
                f"Remove-Item -Recurse -Force '{self._venv_lib()}' "
                f'-ErrorAction SilentlyContinue; '
                f"New-Item -ItemType Directory -Force -Path '{self._venv_lib()}' | Out-Null"
            ),
            timeout=30,
        )

        # Install packages by extracting wheels directly with Python's
        # zipfile module. We bypass `pip install --target` entirely because
        # pip on Windows embed skips .py files for compiled packages
        # (a known bug with embed distributions: pip only copies the .pyd
        # but not __init__.py and other .py files). Direct extraction is
        # simpler, faster, and fully reliable.
        _pkg_str = self.tmpl.get('pip_package', '')
        _m_sdk = re.search(r'openhands-sdk==(\S+)', _pkg_str)
        _m_srv = re.search(r'openhands-agent-server==(\S+)', _pkg_str)
        expected_sdk_version = _m_sdk.group(1) if _m_sdk else None
        expected_server_version = _m_srv.group(1) if _m_srv else None

        # Upload a small Python script that extracts ALL .whl files in the
        # wheels directory into the target lib directory.
        extract_script = (
            'import zipfile, os, sys\n'
            f"wheels_dir = r'{self._wheels_dir()}'\n"
            f"target = r'{self._venv_lib()}'\n"
            'count = 0\n'
            'for whl in sorted(os.listdir(wheels_dir)):\n'
            "    if not whl.endswith('.whl'):\n"
            '        continue\n'
            '    path = os.path.join(wheels_dir, whl)\n'
            '    with zipfile.ZipFile(path) as z:\n'
            '        for name in z.namelist():\n'
            "            if name.endswith('/'):\n"
            '                continue\n'
            '            dest = os.path.join(target, name)\n'
            '            os.makedirs(os.path.dirname(dest), exist_ok=True)\n'
            '            # Skip .pyd files that already exist — on Windows,\n'
            "            # open(locked_pyd, 'wb') HANGS (doesn't raise) if\n"
            '            # a previous python process still holds the lock.\n'
            "            if os.path.exists(dest) and dest.endswith('.pyd'):\n"
            '                continue\n'
            '            try:\n'
            "                with open(dest, 'wb') as f:\n"
            '                    f.write(z.read(name))\n'
            '            except PermissionError:\n'
            '                pass\n'
            '    count += 1\n'
            "print(f'Extracted {count} wheels to {target}')\n"
        )
        extract_path = f'{self._tmp_dir()}/_extract_wheels.py'
        await self.ssh.upload_text(extract_script, extract_path)

        self._broadcast(
            _evt(
                ProvisionStep.INSTALL_AGENT_SDK,
                'started',
                detail='Extracting wheels (direct unzip)...',
            )
        )
        ext_out, ext_err, ext_ec = await self.ssh.run(
            _ps(f"& '{remote_python}' '{extract_path}'"),
            timeout=600,
        )
        logger.info(f'[{self._host}] Wheel extraction: {ext_out.strip()}')
        if ext_ec != 0:
            yield _evt(
                ProvisionStep.INSTALL_AGENT_SDK,
                'failed',
                detail=(
                    f'Wheel extraction failed (ec={ext_ec}):\n\n'
                    f'stdout: {ext_out.strip()[-1000:]}\n'
                    f'stderr: {ext_err.strip()[-1000:] if ext_err else "(empty)"}'
                ),
            )
            return

        # Verify — upload a small .py script then run it, to avoid
        # PowerShell double-quote escaping hell. The inner `"` in
        # `python -c "import ..."` terminates the outer `-Command "..."`.
        verify_py = (
            'import sys, os\n'
            "venv_lib = os.environ.get('PYTHONPATH', '')\n"
            'sys.path.insert(0, venv_lib)\n'
            '# pywin32 bootstrap for --target installs:\n'
            '# 1. DLL loader needs pywin32_system32/ on PATH\n'
            '# 2. Python importer needs win32/ and win32/lib/ on sys.path\n'
            '# (normally pywin32.pth + pywin32_bootstrap.py handle this,\n'
            "#  but .pth files don't run outside site-packages)\n"
            "for sub in ['pywin32_system32', 'win32', 'win32/lib']:\n"
            '    p = os.path.join(venv_lib, sub)\n'
            '    if os.path.isdir(p) and p not in sys.path:\n'
            '        sys.path.insert(0, p)\n'
            "pw32_dll = os.path.join(venv_lib, 'pywin32_system32')\n"
            'if os.path.isdir(pw32_dll):\n'
            "    os.environ['PATH'] = pw32_dll + os.pathsep + os.environ.get('PATH', '')\n"
            "    if hasattr(os, 'add_dll_directory'):\n"
            '        os.add_dll_directory(pw32_dll)\n'
            'import openhands.agent_server\n'
            'import openhands.sdk\n'
            'import openhands.tools\n'
            'import importlib.metadata as m\n'
            "print('VERIFY_OK', m.version('openhands-sdk'), m.version('openhands-agent-server'))\n"
        )
        verify_script = f'{self._tmp_dir()}/_verify_sdk.py'
        await self.ssh.upload_text(verify_py, verify_script)
        verify_cmd = (
            f"$env:PYTHONPATH='{self._venv_lib()}'; "
            f"& '{remote_python}' '{verify_script}'"
        )
        # 120s timeout: first import on Windows embed is very slow because
        # Python scans ~25,000 files + Windows Defender might scan .pyd/.py
        verify_out, verify_err, verify_ec = await self.ssh.run(
            _ps(verify_cmd), timeout=120
        )
        if 'VERIFY_OK' not in verify_out:
            yield _evt(
                ProvisionStep.INSTALL_AGENT_SDK,
                'failed',
                detail=(
                    f'Import verify failed (ec={verify_ec}):\n\n'
                    f'stdout: {verify_out.strip()[-500:]}\n'
                    f'stderr: {verify_err.strip()[-500:] if verify_err else "(empty)"}'
                ),
            )
            return

        # Extract versions for the completed-event detail
        try:
            parts = verify_out.split('VERIFY_OK', 1)[1].strip().split()
            installed_sdk = parts[0] if len(parts) > 0 else '?'
            installed_srv = parts[1] if len(parts) > 1 else '?'
        except Exception:
            installed_sdk = '?'
            installed_srv = '?'

        if (
            expected_sdk_version
            and expected_server_version
            and (
                installed_sdk != expected_sdk_version
                or installed_srv != expected_server_version
            )
        ):
            logger.warning(
                f'[{self._host}] Windows SDK version mismatch: '
                f'installed sdk={installed_sdk}/server={installed_srv}, '
                f'expected sdk={expected_sdk_version}/server={expected_server_version}'
            )

        # Write the agent-server wrapper .cmd + _launcher.py
        await self._write_wrapper_scripts(remote_python)

        yield _evt(
            ProvisionStep.INSTALL_AGENT_SDK,
            'completed',
            detail=f'Installed sdk={installed_sdk}, server={installed_srv}',
        )

        # Save the detected Python path so start_agent_server can use it.
        self._remote_python = remote_python

        # ── Step 4: Auto-deploy Claude CLI ──
        # Bundle contains portable Node.js + @anthropic-ai/claude-code +
        # a generated claude.cmd wrapper. Layout (flat at zip root):
        #   node/                            <- Node.js Windows x64
        #   node_modules/@anthropic-ai/claude-code/
        #   bin/claude.cmd                   <- wrapper we control
        # Extracting with -DestinationPath "$up\.local" merges it under
        # %USERPROFILE%\.local\, which is already on the agent-server
        # wrapper's PATH (set PATH=%USERPROFILE%\.local\bin;%PATH% in
        # agent-server.cmd), so `claude` is resolvable without a shell
        # restart. Login state (`claude login`) is still a manual step
        # for the user after Connect, mirroring the Linux flow.
        if not os.path.exists(CLAUDE_CLI_BUNDLE_WINDOWS):
            yield _evt(
                ProvisionStep.INSTALL_CLAUDE_CLI,
                'failed',
                detail=(
                    f'{os.path.basename(CLAUDE_CLI_BUNDLE_WINDOWS)} not found '
                    f'in deps/. Run on the build machine:\n'
                    f'  python -m manager.dep_builder build-claude-windows'
                ),
            )
            return

        claude_size_mb = os.path.getsize(CLAUDE_CLI_BUNDLE_WINDOWS) // 1024 // 1024
        yield _evt(
            ProvisionStep.INSTALL_CLAUDE_CLI,
            'started',
            detail=f'Uploading Claude CLI bundle ({claude_size_mb}MB)',
        )
        remote_claude_zip = f'{self._tmp_dir()}/claude-cli-bundle-windows.zip'
        claude_last_mb = [0]

        def _claude_progress(sent, total):
            sent_mb = sent // 1024 // 1024
            if sent_mb > claude_last_mb[0]:
                claude_last_mb[0] = sent_mb
                pct = int(sent * 100 / total) if total else 0
                self._broadcast(
                    _evt(
                        ProvisionStep.INSTALL_CLAUDE_CLI,
                        'started',
                        detail=f'{sent_mb}/{claude_size_mb}MB ({pct}%)',
                    )
                )

        await self.ssh.upload_file(
            CLAUDE_CLI_BUNDLE_WINDOWS,
            remote_claude_zip,
            progress_callback=_claude_progress,
        )
        self._broadcast(
            _evt(ProvisionStep.INSTALL_CLAUDE_CLI, 'started', detail='Extracting...')
        )

        local_dir = f'{self._up()}/.local'
        # Expand-Archive into %USERPROFILE%\.local\; -Force overwrites
        # existing files so re-runs are idempotent. We do NOT delete the
        # target dir first (it may contain other .local/bin shims from
        # future tools), only the subdirs owned by this bundle.
        await self.ssh.run(
            _ps(
                f"New-Item -ItemType Directory -Force -Path '{local_dir}' | Out-Null; "
                f"foreach ($sub in 'node','node_modules','bin') {{ "
                f"    $p = Join-Path '{local_dir}' $sub; "
                f'    if (Test-Path $p) {{ Remove-Item -Recurse -Force $p }} '
                f'}}; '
                f"Expand-Archive -Path '{remote_claude_zip}' "
                f"-DestinationPath '{local_dir}' -Force; "
                f"Remove-Item '{remote_claude_zip}' -Force"
            ),
            timeout=180,
        )

        # Verify by invoking the wrapper we ship
        claude_cmd = f'{local_dir}/bin/claude.cmd'
        ver_out, _, ver_ec = await self.ssh.run(
            _ps(f"& '{claude_cmd}' --version 2>&1"),
            timeout=30,
        )
        if ver_ec != 0 or not ver_out.strip():
            yield _evt(
                ProvisionStep.INSTALL_CLAUDE_CLI,
                'failed',
                detail=(
                    f'Claude CLI verification failed (ec={ver_ec}): '
                    f'{ver_out.strip()[:500]}'
                ),
            )
            return
        yield _evt(
            ProvisionStep.INSTALL_CLAUDE_CLI,
            'completed',
            detail=ver_out.strip().splitlines()[0],
        )

        # ── Step 5: Skills sync ──
        # Create the user skills directory so Claude mode's workspace
        # discovery has somewhere to look. We don't pre-populate from a
        # bundle on Windows v1 — users can upload skills manually or
        # through a future feature.
        user_skills = f'{self._up()}/.openhands/skills'
        await self.ssh.run(
            _ps(
                f"New-Item -ItemType Directory -Force -Path '{user_skills}' | Out-Null"
            ),
            timeout=10,
        )
        yield _evt(
            ProvisionStep.CLONE_SKILLS,
            'completed',
            detail=f'Skills dir ready at {user_skills}',
        )

        # ── Step 6-9 are triggered by machine_manager._start_agent_server ──
        # The provision() generator's job is just prep work; the actual
        # agent-server process launch happens AFTER provision() returns,
        # in machine_manager._start_agent_server → provisioner.start_agent_server().
        # So we're done here — caller will proceed to start + health + tunnel.

    # ------------------------------------------------------------
    # Wrapper script writing (uses ssh.upload_text — no heredoc)
    # ------------------------------------------------------------

    async def _write_wrapper_scripts(self, remote_python: str) -> None:
        """Drop `_launcher.py` (identical to the Linux version) and a
        Windows-native `agent-server.cmd` into `<venv>/bin/`.
        """
        bin_dir = self._venv_bin()
        await self.ssh.run(
            _ps(f"New-Item -ItemType Directory -Force -Path '{bin_dir}' | Out-Null"),
            timeout=10,
        )

        # _launcher.py — Windows variant bootstraps pywin32 for --target installs.
        launcher_py = (
            'import os, sys, logging\n'
            "venv_lib = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib')\n"
            'if venv_lib not in sys.path:\n'
            '    sys.path.insert(0, venv_lib)\n'
            '#\n'
            '# pywin32 bootstrap for pip --target installs:\n'
            "# .pth files don't execute outside site-packages, so we manually\n"
            '# add pywin32_system32/ (DLLs), win32/ and win32/lib/ (modules)\n'
            "for _sub in ['pywin32_system32', 'win32', os.path.join('win32', 'lib')]:\n"
            '    _p = os.path.join(venv_lib, _sub)\n'
            '    if os.path.isdir(_p) and _p not in sys.path:\n'
            '        sys.path.insert(0, _p)\n'
            "pw32_dll = os.path.join(venv_lib, 'pywin32_system32')\n"
            'if os.path.isdir(pw32_dll):\n'
            "    os.environ['PATH'] = pw32_dll + os.pathsep + os.environ.get('PATH', '')\n"
            "    if hasattr(os, 'add_dll_directory'):\n"
            '        os.add_dll_directory(pw32_dll)\n'
            '#\n'
            '# === HiClaw patches (run before agent-server imports) ===\n'
            '#\n'
            'try:\n'
            '    import httpx\n'
            '    httpx._config.DEFAULT_TIMEOUT_CONFIG = httpx.Timeout(connect=10, read=60, write=30, pool=10)\n'
            'except Exception: pass\n'
            "logging.basicConfig(level=logging.DEBUG, format='%(name)s %(levelname)s %(message)s', stream=sys.stdout)\n"
            "for name in ['LiteLLM', 'litellm', 'httpx', 'httpcore']:\n"
            '    logging.getLogger(name).setLevel(logging.DEBUG)\n'
            'try:\n'
            '    import litellm\n'
            '    litellm.set_verbose = True\n'
            'except Exception: pass\n'
            "print('[HiClaw] Windows launcher ready', flush=True)\n"
            'from openhands.agent_server.__main__ import main\n'
            'sys.exit(main())\n'
        )
        await self.ssh.upload_text(launcher_py, f'{bin_dir}/_launcher.py')

        # agent-server.cmd wrapper
        wrapper_cmd = (
            '@echo off\r\n'
            f'set PYTHONPATH={self._venv_lib()};%PYTHONPATH%\r\n'
            'set no_proxy=localhost,127.0.0.1,%no_proxy%\r\n'
            'set NO_PROXY=localhost,127.0.0.1,%NO_PROXY%\r\n'
            # pywin32 DLLs (pywintypes312.dll, pythoncom312.dll) live
            # in pywin32_system32/ under --target installs. Must be on
            # PATH for the Windows DLL loader to find them at import
            # time (mcp → pywintypes → DLL search).
            f'set PATH={self._venv_lib()}\\pywin32_system32;'
            '%USERPROFILE%\\.local\\bin;%PATH%\r\n'
            f'"{remote_python}" "{bin_dir}/_launcher.py" %*\r\n'
        )
        await self.ssh.upload_text(wrapper_cmd, f'{bin_dir}/agent-server.cmd')
        logger.info(f'[{self._host}] Wrote Windows wrapper: {bin_dir}/agent-server.cmd')

    # ------------------------------------------------------------
    # Abstract method impls (start / alive / kill)
    # ------------------------------------------------------------

    def _env_vars_linux_to_ps(self, env_vars: str) -> list[str]:
        """Translate the Linux-style `KEY=VAL KEY2='val with space' ...` string
        that machine_manager._start_agent_server builds into a list of
        PowerShell `$env:KEY = 'VAL'` statements.

        Key subtlety: machine_manager's env_vars string contains literal
        `$HOME` references (e.g. `FILE_STORE_PATH=$HOME/.hiclaw`). On Linux
        the surrounding bash shell expands `$HOME` at exec time, but on
        Windows PowerShell (and our single-quoted `$env:KEY='val'`
        assignment) `$HOME` would stay literal. We substitute it with the
        resolved remote userprofile before wrapping.
        """
        if not env_vars:
            return []

        # Tokenize respecting single and double quotes.
        pattern = re.compile(r"(\w+)=('([^']*)'|\"([^\"]*)\"|(\S*))")
        stmts: list[str] = []
        # Resolved userprofile for $HOME substitution. Fall back to the
        # literal $HOME if we somehow lost the cache — worst case the agent
        # process fails with a readable error.
        home_replacement = self._userprofile or '$HOME'
        for match in pattern.finditer(env_vars):
            key = match.group(1)
            # Prefer the quoted capture groups, fallback to the bare one.
            val = match.group(3) or match.group(4) or match.group(5) or ''
            # Substitute Linux $HOME with the real remote userprofile. Keep
            # the forward slashes — PowerShell / Python both accept them.
            val = val.replace('$HOME', home_replacement)
            # PowerShell single-quote escape: ' becomes ''
            val_escaped = val.replace("'", "''")
            stmts.append(f"$env:{key} = '{val_escaped}'")
        return stmts

    async def start_agent_server(
        self,
        port: int,
        env_vars: str,
        log_file: str,
    ) -> None:
        """Start agent-server.cmd as a hidden background process on Windows.

        Strategy:
          1. Translate `env_vars` into PowerShell `$env:KEY=...` statements.
          2. Translate the Linux-style log_file path (`$HOME/.hiclaw/logs/..`)
             to the Windows equivalent (`<userprofile>/.hiclaw/logs/..`).
          3. `Start-Process` the wrapper .cmd with `-WindowStyle Hidden` and
             `-PassThru` so we can capture the PID.
          4. Write the PID to `<userprofile>/.hiclaw/agent-server-<port>.pid`.
        """
        # Ensure userprofile is populated — it already should be from provision()
        # but start_agent_server is also called from reconnect paths where
        # provision() may have been skipped.
        if not self._userprofile:
            await self._probe_userprofile()

        bin_dir = self._venv_bin()

        # Translate env vars into PowerShell
        env_stmts = self._env_vars_linux_to_ps(env_vars)
        '; '.join(env_stmts) + ('; ' if env_stmts else '')

        # Translate log_file: Linux path → Windows path under userprofile
        log_win = log_file.replace('$HOME', self._up()).replace('\\', '/')

        pid_file = self._pid_file(port)

        # Start python.exe in background via a helper .ps1 script that we
        # upload and invoke. Previous attempts with `Start-Process -FilePath
        # agent-server.cmd` and `Start-Process -FilePath python.exe` both
        # failed because:
        #   - .cmd wrapper: PowerShell treated LiteLLM ANSI stderr as error
        #   - Direct python: Start-Process over SSH creates processes that
        #     die when the SSH channel closes (no persistent session)
        #
        # Reliable Windows background trick: write a tiny .ps1 that sets
        # env vars, starts python as a detached process via WMI, captures
        # PID, and writes it to the PID file. WMI-created processes survive
        # SSH disconnect because they're owned by WMI, not the SSH session.
        remote_python = getattr(self, '_remote_python', None) or self._python_exe()
        launcher = f'{bin_dir}/_launcher.py'
        venv_lib = self._venv_lib()
        pw32_dll = f'{venv_lib}/pywin32_system32'
        local_bin = f'{self._up()}/.local/bin'

        # Strategy: upload a .cmd batch file that sets all env vars and
        # launches python.exe. Then use WMI via PowerShell to start the
        # .cmd as a detached process. WMI-created processes survive SSH
        # disconnect (unlike Start-Process which inherits the SSH session).
        # The .cmd handles its own stdout/stderr redirection via `>` and `2>`.
        log_dir = self._logs_dir()
        starter_cmd = '@echo off\r\n'
        # Force UTF-8 so emoji in agent-server print() don't crash cp1252
        starter_cmd += 'set PYTHONIOENCODING=utf-8\r\n'
        starter_cmd += f'set PYTHONPATH={venv_lib}\r\n'
        starter_cmd += f'set PATH={pw32_dll};{local_bin};%PATH%\r\n'
        starter_cmd += 'set no_proxy=localhost,127.0.0.1,%no_proxy%\r\n'
        starter_cmd += 'set NO_PROXY=localhost,127.0.0.1,%NO_PROXY%\r\n'
        # Add the translated env vars from machine_manager
        for stmt in env_stmts:
            # Convert PS `$env:KEY = 'VALUE'` to cmd `set KEY=VALUE`
            import re as _re

            m = _re.match(r"\$env:(\w+)\s*=\s*'(.*)'", stmt)
            if m:
                starter_cmd += f'set {m.group(1)}={m.group(2)}\r\n'
        starter_cmd += (
            f'"{remote_python}" "{launcher}" --port {port} '
            f'> "{log_win}" 2> "{log_win}.err"\r\n'
        )
        starter_bat = f'{self._tmp_dir()}/_start_agent.cmd'
        await self.ssh.upload_text(starter_cmd, starter_bat)

        # Ensure log directory exists
        await self.ssh.run(
            _ps(f"New-Item -ItemType Directory -Force -Path '{log_dir}' | Out-Null"),
            timeout=10,
        )

        # Launch via `schtasks` — registers a one-time scheduled task and
        # runs it immediately. This is the only reliable Windows mechanism
        # to start a process that truly survives SSH disconnect:
        #   - `cmd /c start /b`  → child dies when SSH channel closes
        #   - `Start-Process`    → inherits SSH session
        #   - WMI Create()       → sometimes tears down the child
        # schtasks-launched processes are owned by Task Scheduler service,
        # fully detached from our session.
        task_name = f'HiClawAgent_{port}'
        # Escape backslashes for the /tr argument
        tr_value = f'cmd /c "{starter_bat}"'
        # Create task (runs as current user, HighestAvailable to get SYSTEM-level detachment)
        # /sc once + /st 00:00 + /sd 01/01/2030 → task exists but won't auto-run
        # We manually trigger with /run, then /delete it.
        create_ps = (
            f"schtasks /create /tn '{task_name}' /tr '{tr_value}' "
            f'/sc once /st 00:00 /sd 01/01/2030 /f 2>&1 | Out-String'
        )
        out, err_out, ec = await self.ssh.run(_ps(create_ps), timeout=15)
        if ec != 0 and 'SUCCESS' not in (out or '').upper():
            raise RuntimeError(
                f'Failed to create scheduled task (ec={ec}):\n'
                f'stdout: {out.strip()[-500:]}\nstderr: {err_out.strip()[-500:] if err_out else ""}'
            )
        logger.info(f'[{self._host}] Created scheduled task {task_name}')

        # Run the task now — this launches the detached process
        run_ps = f"schtasks /run /tn '{task_name}' 2>&1 | Out-String"
        out, err_out, ec = await self.ssh.run(_ps(run_ps), timeout=15)
        if ec != 0:
            raise RuntimeError(
                f'Failed to run scheduled task (ec={ec}):\n'
                f'stdout: {out.strip()[-500:]}\nstderr: {err_out.strip()[-500:] if err_out else ""}'
            )

        # Clean up the task definition (the process keeps running)
        await self.ssh.run(
            _ps(f"schtasks /delete /tn '{task_name}' /f 2>&1 | Out-Null"),
            timeout=10,
        )

        # Give the process a moment to bind its port
        import asyncio

        await asyncio.sleep(3)

        # Find the PID by matching python.exe with our _launcher.py
        find_pid_ps = (
            f'$proc = Get-WmiObject Win32_Process | '
            f"Where-Object {{ $_.CommandLine -like '*_launcher.py*--port {port}*' }}; "
            f'if ($proc) {{ '
            f"  Set-Content -Path '{pid_file}' -Value $proc.ProcessId -NoNewline; "
            f'  Write-Host $proc.ProcessId '
            f"}} else {{ Write-Host 'NOT_FOUND' }}"
        )
        out, err_out, ec = await self.ssh.run(_ps(find_pid_ps), timeout=10)
        if ec != 0 or 'NOT_FOUND' in (out or ''):
            raise RuntimeError(
                f'Windows agent-server failed to start after schtasks trigger (ec={ec}):\n'
                f'stdout: {out.strip()[-500:]}\nstderr: {err_out.strip()[-500:] if err_out else ""}'
            )
        logger.info(
            f'[{self._host}] Windows agent-server started on :{port}, pid={out.strip()}'
        )

    async def is_agent_server_alive(self, port: int) -> bool:
        """Check whether the PID recorded for `port` is still running."""
        if not self._userprofile:
            try:
                await self._probe_userprofile()
            except Exception:
                return False

        pid_file = self._pid_file(port)
        check_cmd = (
            f"if (Test-Path '{pid_file}') {{ "
            f"  $pid = (Get-Content '{pid_file}').Trim(); "
            f'  if (Get-Process -Id $pid -ErrorAction SilentlyContinue) '
            f"    {{ Write-Host 'ALIVE' }} else {{ Write-Host 'DEAD' }} "
            f"}} else {{ Write-Host 'NOPIDFILE' }}"
        )
        out, _, _ = await self.ssh.run(_ps(check_cmd), timeout=10)
        return 'ALIVE' in (out or '')

    async def kill_agent_server(self, port: int) -> None:
        """Force-kill the recorded PID and remove the PID file (best-effort)."""
        if not self._userprofile:
            try:
                await self._probe_userprofile()
            except Exception:
                return

        pid_file = self._pid_file(port)
        kill_cmd = (
            f"if (Test-Path '{pid_file}') {{ "
            f"  $pid = (Get-Content '{pid_file}').Trim(); "
            f'  Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue; '
            f"  Remove-Item '{pid_file}' -Force -ErrorAction SilentlyContinue "
            f'}}'
        )
        await self.ssh.run(_ps(kill_cmd), timeout=10)

    async def tail_agent_log(self, log_file: str, lines: int = 30) -> str:
        """Read last N lines of log file on Windows.

        Also reads the .err file (stderr captured by starter .cmd) since
        Python crashes usually write traceback to stderr.
        """
        # Translate Linux-style path (may contain $HOME) to Windows
        if not self._userprofile:
            try:
                await self._probe_userprofile()
            except Exception:
                return ''
        log_win = log_file.replace('$HOME', self._up()).replace('\\', '/')

        # Read both stdout log and stderr log — stderr is where Python
        # tracebacks usually end up.
        read_cmd = (
            f"$out = ''; "
            f"if (Test-Path '{log_win}') {{ "
            f"  $c = Get-Content '{log_win}' -Tail {lines} -ErrorAction SilentlyContinue; "
            f'  if ($c) {{ $out += ($c -join [char]10) }} '
            f'}}; '
            f"if (Test-Path '{log_win}.err') {{ "
            f"  $c = Get-Content '{log_win}.err' -Tail {lines} -ErrorAction SilentlyContinue; "
            f"  if ($c) {{ $out += [char]10 + '--- STDERR ---' + [char]10 + ($c -join [char]10) }} "
            f'}}; '
            f'Write-Output $out'
        )
        out, _, _ = await self.ssh.run(_ps(read_cmd), timeout=10)
        return (out or '').strip()
