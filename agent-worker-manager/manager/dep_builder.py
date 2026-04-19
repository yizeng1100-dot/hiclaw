"""Dependency builder — creates offline bundles for remote deployment.

Run this script on a machine with internet to pre-build the dependency bundle.
The bundle is then uploaded to internal machines via SFTP during provisioning.

Usage (Linux):
    python -m manager.dep_builder build             # Linux wheels + code-server bundle
    python -m manager.dep_builder check             # check Linux bundle exists

Usage (Windows):
    python -m manager.dep_builder build-windows           # wheels zip
    python -m manager.dep_builder check-windows           # check wheels zip exists
    python -m manager.dep_builder build-python-windows    # Python 3.12 embed zip
    python -m manager.dep_builder check-python-windows    # check embed zip exists
    python -m manager.dep_builder build-claude-windows    # Node.js + Claude CLI zip
    python -m manager.dep_builder check-claude-windows    # check Claude CLI zip exists

    python -m manager.dep_builder build-all-windows       # run all three Windows builds
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

DEPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'deps')
BUNDLE_PATH = os.path.join(DEPS_DIR, 'agent-deps-bundle.tar.gz')
WHEELS_DIR = os.path.join(DEPS_DIR, 'wheels')

# >>> CUSTOM: HiClaw — Windows-specific output paths <<<
WHEELS_DIR_WINDOWS = os.path.join(DEPS_DIR, 'wheels-windows')
BUNDLE_PATH_WINDOWS = os.path.join(DEPS_DIR, 'agent-deps-bundle-windows.zip')
PYTHON_EMBED_WINDOWS = os.path.join(DEPS_DIR, 'python-windows-embed.zip')
CLAUDE_CLI_BUNDLE_WINDOWS = os.path.join(DEPS_DIR, 'claude-cli-bundle-windows.zip')

# Python embed — python.org official embeddable distribution for Windows
PYTHON_EMBED_VERSION = '3.12.7'
PYTHON_EMBED_URL = (
    f'https://www.python.org/ftp/python/{PYTHON_EMBED_VERSION}/'
    f'python-{PYTHON_EMBED_VERSION}-embed-amd64.zip'
)
GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py'

# Node.js — portable zip distribution for Windows x64
NODE_WINDOWS_VERSION = '20.18.1'  # LTS as of 2025-01
NODE_WINDOWS_URL = (
    f'https://nodejs.org/dist/v{NODE_WINDOWS_VERSION}/'
    f'node-v{NODE_WINDOWS_VERSION}-win-x64.zip'
)
CLAUDE_NPM_PACKAGE = '@anthropic-ai/claude-code'
# >>> END CUSTOM <<<

# What to download
SDK_PACKAGES = (
    'openhands-agent-server==1.16.1.post9 openhands-sdk==1.16.1 openhands-tools==1.16.1'
)
CODE_SERVER_VERSION = '4.96.4'


def build_bundle():
    """Download all dependencies and create the offline bundle."""
    os.makedirs(WHEELS_DIR, exist_ok=True)

    print(f'Downloading Python wheels to {WHEELS_DIR}...')
    subprocess.run(
        f'pip download {SDK_PACKAGES} --dest {WHEELS_DIR}',
        shell=True,
        check=True,
    )

    print(f'Downloading code-server v{CODE_SERVER_VERSION}...')
    cs_path = os.path.join(DEPS_DIR, 'code-server.tar.gz')
    subprocess.run(
        f"curl -fL 'https://github.com/coder/code-server/releases/download/"
        f"v{CODE_SERVER_VERSION}/code-server-{CODE_SERVER_VERSION}-linux-amd64.tar.gz' "
        f'-o {cs_path}',
        shell=True,
        check=True,
    )

    print(f'Creating bundle at {BUNDLE_PATH}...')
    subprocess.run(
        f'tar czf {BUNDLE_PATH} -C {DEPS_DIR} wheels/ code-server.tar.gz',
        shell=True,
        check=True,
    )

    size_mb = os.path.getsize(BUNDLE_PATH) / 1024 / 1024
    print(f'Bundle created: {BUNDLE_PATH} ({size_mb:.1f} MB)')


def check_bundle() -> bool:
    """Check if the offline bundle exists."""
    exists = os.path.exists(BUNDLE_PATH)
    if exists:
        size_mb = os.path.getsize(BUNDLE_PATH) / 1024 / 1024
        print(f'Bundle exists: {BUNDLE_PATH} ({size_mb:.1f} MB)')
    else:
        print(f'Bundle not found at {BUNDLE_PATH}')
        print('Run: python -m manager.dep_builder build')
    return exists


# >>> CUSTOM: HiClaw — Windows wheels bundle builder <<<
def build_windows_bundle():
    """Download Windows-compatible wheels + zip them into
    `deps/agent-deps-bundle-windows.zip`.

    Uses `pip download --platform win_amd64 --python-version 312
    --only-binary=:all:` to grab wheels that match the Windows agent-server
    target (CPython 3.12, amd64). Pure-python wheels come down as-is;
    platform-specific wheels get their Windows build selected.

    Also prompts the caller to drop a pre-downloaded Python embed zip at
    `deps/python-windows-embed.zip` — we don't fetch that automatically
    because python.org sometimes rate-limits raw curl.
    """
    os.makedirs(WHEELS_DIR_WINDOWS, exist_ok=True)

    print(f'Downloading Windows wheels to {WHEELS_DIR_WINDOWS}...')
    # --only-binary=:all: forces pip to use wheels and skip any sdist fallback
    # --implementation cp --abi cp312 --platform win_amd64 targets CPython 3.12 on Windows.
    # Use `sys.executable -m pip` rather than shell `pip` so we pick up the
    # invoking interpreter's pip (system PATH may not have a bare `pip`).
    # --find-links {WHEELS_DIR} makes pip prefer wheels from the Linux bundle
    # directory — critical because openhands-agent-server is a private
    # ".postN" build not published on PyPI, shipped as a pure-python wheel
    # that works on Windows too. pip still falls back to PyPI for any
    # platform-specific transitives it can't find locally.
    if not os.path.isdir(WHEELS_DIR):
        raise RuntimeError(
            f'Linux wheels dir {WHEELS_DIR} missing — run `build` first or '
            f'populate it with the openhands .postN wheel manually.'
        )
    subprocess.run(
        f'{sys.executable} -m pip download {SDK_PACKAGES} --dest {WHEELS_DIR_WINDOWS} '
        f'--find-links {WHEELS_DIR} '
        f'--platform win_amd64 --platform any '
        f'--python-version 312 --implementation cp --abi cp312 '
        f'--only-binary=:all:',
        shell=True,
        check=True,
    )

    # Force-download Windows-only transitive deps that `pip download` on a
    # Linux build machine silently skips. Reason: pip's `--platform` flag
    # changes wheel tag matching but NOT environment-marker evaluation, so
    # a dep like `pywin32 ; sys_platform == "win32"` (required by `docker`
    # on Windows) gets filtered out because the build machine is Linux.
    # See: https://github.com/pypa/pip/issues/9580
    # We maintain a small, explicit list of known Windows-only dependencies
    # in the Openhands dep tree.
    # Full list discovered by scanning all wheel METADATA for Windows-only
    # markers (sys_platform=="win32", platform_system=="Windows", os_name=="nt").
    # pip on Linux skips these due to marker mismatch — must force-download.
    win_only_deps = 'pywin32 pywin32-ctypes colorama tzdata'
    print(f'Force-downloading Windows-only transitives: {win_only_deps}')
    subprocess.run(
        f'{sys.executable} -m pip download {win_only_deps} --dest {WHEELS_DIR_WINDOWS} '
        f'--platform win_amd64 '
        f'--python-version 312 --implementation cp --abi cp312 '
        f'--only-binary=:all: --no-deps',
        shell=True,
        check=True,
    )

    print(f'Creating Windows bundle zip at {BUNDLE_PATH_WINDOWS}...')
    # zip for Windows — PowerShell Expand-Archive on the remote only
    # handles .zip natively. We put the wheels into a `wheels/` subdir so
    # the extraction layout on the remote mirrors what the provisioner
    # expects under `.hiclaw/agent-deps/wheels/`.
    #
    # `cd` into DEPS_DIR then zip `wheels-windows/*` as `wheels/*` inside
    # the archive — easiest way is to temporarily symlink or use Python's
    # zipfile. Use zipfile for predictability.
    import zipfile

    if os.path.exists(BUNDLE_PATH_WINDOWS):
        os.remove(BUNDLE_PATH_WINDOWS)
    with zipfile.ZipFile(BUNDLE_PATH_WINDOWS, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(WHEELS_DIR_WINDOWS)):
            src = os.path.join(WHEELS_DIR_WINDOWS, name)
            if os.path.isfile(src):
                zf.write(src, arcname=f'wheels/{name}')

    size_mb = os.path.getsize(BUNDLE_PATH_WINDOWS) / 1024 / 1024
    print(f'Windows bundle created: {BUNDLE_PATH_WINDOWS} ({size_mb:.1f} MB)')

    # Remind about the Python embed package — we don't fetch it
    # automatically because some CI/build boxes block python.org.
    if not os.path.exists(PYTHON_EMBED_WINDOWS):
        print()
        print('NOTE: python-windows-embed.zip is NOT present. To enable')
        print('automatic Python deployment on Windows remotes without')
        print('pre-installed Python, download it manually:')
        print()
        print(f"  curl -fL '{PYTHON_EMBED_URL}' -o {PYTHON_EMBED_WINDOWS}")
        print()
        print('(The provisioner gracefully skips this step if the file is')
        print('missing and expects Python 3.12 to be on the remote PATH')
        print('or available via `py -3.12`.)')
    else:
        embed_mb = os.path.getsize(PYTHON_EMBED_WINDOWS) / 1024 / 1024
        print(f'Python embed present: {PYTHON_EMBED_WINDOWS} ({embed_mb:.1f} MB)')


def check_bundle_windows() -> bool:
    """Check if the Windows wheels bundle exists (for CI / pre-flight checks)."""
    exists = os.path.exists(BUNDLE_PATH_WINDOWS)
    if exists:
        size_mb = os.path.getsize(BUNDLE_PATH_WINDOWS) / 1024 / 1024
        print(f'Windows wheels bundle exists: {BUNDLE_PATH_WINDOWS} ({size_mb:.1f} MB)')
    else:
        print(f'Windows wheels bundle not found at {BUNDLE_PATH_WINDOWS}')
        print('Run: python -m manager.dep_builder build-windows')
    return exists


# ------------------------------------------------------------------
# Python embed builder — downloads python.org zip, enables site/pip,
# and repackages into deps/python-windows-embed.zip
# ------------------------------------------------------------------
def build_python_windows_embed():
    """Download the Python 3.12 Windows embeddable package, patch `_pth`
    to enable site-packages, inject pip, and save as
    `deps/python-windows-embed.zip`.

    The embed distribution from python.org ships without pip and with a
    `python312._pth` file that has `#import site` commented out. Without
    enabling site, pip can't install packages even if present. We:

      1. Fetch the embed zip from python.org
      2. Extract it into a staging directory
      3. Uncomment the `import site` line in `python*._pth`
      4. Fetch `get-pip.py` from bootstrap.pypa.io
      5. Run it with the staged python.exe to drop pip into the embed
         (requires Wine on Linux build boxes — if unavailable, we just
         bundle `get-pip.py` alongside and let the remote Windows run it
         on first boot)
      6. Repackage everything as a zip at `deps/python-windows-embed.zip`

    Note: step 5 needs a Windows-capable python.exe. On a Linux build
    machine, we skip the actual pip install and drop `get-pip.py` into
    the bundle root instead — the provisioner will run it on the target
    Windows machine during step 4 (INSTALL_PYTHON).
    """
    import tempfile
    import urllib.request
    import zipfile

    os.makedirs(DEPS_DIR, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='hiclaw-pyembed-', dir=DEPS_DIR) as tmp:
        raw_zip = os.path.join(tmp, 'python-embed-raw.zip')
        print(f'Downloading Python {PYTHON_EMBED_VERSION} embed from python.org...')
        print(f'  {PYTHON_EMBED_URL}')
        urllib.request.urlretrieve(PYTHON_EMBED_URL, raw_zip)
        raw_mb = os.path.getsize(raw_zip) / 1024 / 1024
        print(f'  downloaded {raw_mb:.1f} MB')

        stage = os.path.join(tmp, 'stage')
        os.makedirs(stage, exist_ok=True)
        print('Extracting embed zip to staging...')
        with zipfile.ZipFile(raw_zip, 'r') as zf:
            zf.extractall(stage)

        # Find python*._pth (e.g. python312._pth) and uncomment `import site`.
        pth_files = [
            name
            for name in os.listdir(stage)
            if name.endswith('._pth') and name.startswith('python')
        ]
        if not pth_files:
            raise RuntimeError(
                f'No python*._pth file found in embed zip — layout unexpected: '
                f'{os.listdir(stage)}'
            )
        for pth in pth_files:
            pth_path = os.path.join(stage, pth)
            content = open(pth_path, encoding='utf-8').read()
            # Replace commented `#import site` with enabled `import site`.
            # The embed distribution ships with this line commented out.
            patched = content.replace('#import site', 'import site')
            if patched == content and 'import site' not in content:
                # Line wasn't present at all; append it.
                patched = content.rstrip() + '\nimport site\n'
            open(pth_path, 'w', encoding='utf-8').write(patched)
            print(f'  patched {pth}: enabled `import site`')

        # Fetch get-pip.py so the embed can bootstrap pip on first use.
        # We bundle it rather than running it here because the embed's
        # python.exe is a Windows PE binary and won't execute on Linux.
        get_pip_path = os.path.join(stage, 'get-pip.py')
        print('Downloading get-pip.py...')
        urllib.request.urlretrieve(GET_PIP_URL, get_pip_path)
        print(f'  saved to {get_pip_path}')

        # Repackage as deps/python-windows-embed.zip. Contents are flat at
        # the zip root so that PowerShell `Expand-Archive -DestinationPath
        # <python_dir>` on the remote produces a working layout.
        if os.path.exists(PYTHON_EMBED_WINDOWS):
            os.remove(PYTHON_EMBED_WINDOWS)
        print(f'Repackaging to {PYTHON_EMBED_WINDOWS}...')
        with zipfile.ZipFile(PYTHON_EMBED_WINDOWS, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(stage):
                for f in files:
                    src = os.path.join(root, f)
                    # Preserve path relative to stage/
                    arcname = os.path.relpath(src, stage)
                    zf.write(src, arcname=arcname)

    size_mb = os.path.getsize(PYTHON_EMBED_WINDOWS) / 1024 / 1024
    print(f'Python embed bundle created: {PYTHON_EMBED_WINDOWS} ({size_mb:.1f} MB)')


def check_python_windows() -> bool:
    """Check if the Python embed bundle exists."""
    exists = os.path.exists(PYTHON_EMBED_WINDOWS)
    if exists:
        mb = os.path.getsize(PYTHON_EMBED_WINDOWS) / 1024 / 1024
        print(f'Python embed bundle exists: {PYTHON_EMBED_WINDOWS} ({mb:.1f} MB)')
    else:
        print(f'Python embed bundle not found at {PYTHON_EMBED_WINDOWS}')
        print('Run: python -m manager.dep_builder build-python-windows')
    return exists


# ------------------------------------------------------------------
# Claude CLI bundle builder — downloads Node.js Windows portable,
# uses system Node/npm to install @anthropic-ai/claude-code, writes
# our own .cmd wrapper, and repackages into
# deps/claude-cli-bundle-windows.zip
# ------------------------------------------------------------------
def build_claude_cli_windows():
    """Build `deps/claude-cli-bundle-windows.zip` from scratch.

    Layout of the final zip (flat at root, so `Expand-Archive
    -DestinationPath %USERPROFILE%\\.local` on the remote produces the
    matching directory tree):

        node/                        <- Node.js Windows x64 portable
            node.exe
            npm.cmd
            ...
        node_modules/
            @anthropic-ai/
                claude-code/         <- the npm package
        bin/
            claude.cmd               <- wrapper we generate

    Build steps:

      1. Download Node.js Windows x64 portable zip from nodejs.org
      2. Extract it — the archive contains one top-level directory
         `node-v<ver>-win-x64/` which we rename to `node/`
      3. Use the **build machine's** system `npm` to install
         `@anthropic-ai/claude-code` into a staging prefix. This puts
         `node_modules/@anthropic-ai/claude-code/` under the staging
         directory. The package is pure JS so its node_modules/ tree
         is portable to Windows.
      4. Write a `bin/claude.cmd` wrapper that sets up PATH and invokes
         `node_modules/@anthropic-ai/claude-code/cli.js` via the bundled
         node.exe. Paths are relative (%~dp0..) so the bundle works at
         any extraction location.
      5. Zip everything with flat root layout.

    Requirements on the build machine: system `npm` + `node` available
    on PATH, and internet access to nodejs.org + npm registry.
    """
    import shutil
    import tempfile
    import urllib.request
    import zipfile

    # Pre-flight: verify system npm/node are available
    try:
        subprocess.run(
            'npm --version',
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            'System `npm` not found. Install Node.js on the build machine '
            'first (e.g. `apt install nodejs npm` or `nvm install 20`), '
            'then retry.'
        ) from e

    os.makedirs(DEPS_DIR, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='hiclaw-claude-', dir=DEPS_DIR) as tmp:
        # Step 1: download Node.js Windows zip
        node_zip = os.path.join(tmp, 'node-win.zip')
        print(f'Downloading Node.js {NODE_WINDOWS_VERSION} (Windows x64)...')
        print(f'  {NODE_WINDOWS_URL}')
        urllib.request.urlretrieve(NODE_WINDOWS_URL, node_zip)
        node_mb = os.path.getsize(node_zip) / 1024 / 1024
        print(f'  downloaded {node_mb:.1f} MB')

        # Step 2: extract to staging, rename single top-level dir to `node/`
        stage = os.path.join(tmp, 'stage')
        os.makedirs(stage, exist_ok=True)
        node_extract = os.path.join(tmp, 'node-extract')
        os.makedirs(node_extract, exist_ok=True)
        with zipfile.ZipFile(node_zip, 'r') as zf:
            zf.extractall(node_extract)
        # The zip contains a single top-level dir like node-v20.18.1-win-x64/
        entries = os.listdir(node_extract)
        if len(entries) != 1:
            raise RuntimeError(
                f'Unexpected Node.js zip layout — expected 1 top-level dir, '
                f'got {entries}'
            )
        node_src = os.path.join(node_extract, entries[0])
        node_dst = os.path.join(stage, 'node')
        shutil.move(node_src, node_dst)
        print(f'  staged node/ ({len(os.listdir(node_dst))} files)')

        # Step 3: npm install @anthropic-ai/claude-code into the staging
        # prefix. Uses the build machine's system npm (any platform) to
        # populate node_modules/ with pure-JS content. The result is
        # portable to Windows.
        print(f'Installing {CLAUDE_NPM_PACKAGE}@latest via system npm...')
        subprocess.run(
            f'npm install --prefix {stage} --no-save --no-audit --no-fund '
            f'{CLAUDE_NPM_PACKAGE}@latest',
            shell=True,
            check=True,
            cwd=stage,
        )
        # npm puts packages in <prefix>/node_modules/
        node_modules = os.path.join(stage, 'node_modules')
        if not os.path.isdir(node_modules):
            raise RuntimeError(f'npm install finished but {node_modules} not found')
        claude_pkg = os.path.join(node_modules, '@anthropic-ai', 'claude-code')
        if not os.path.isdir(claude_pkg):
            raise RuntimeError(
                f'@anthropic-ai/claude-code not found at {claude_pkg} after npm install'
            )
        print(f'  installed into {node_modules}')

        # Remove the package.json / package-lock.json that npm creates at
        # the prefix — we don't need them at runtime and they pollute the
        # bundle root.
        for junk in ('package.json', 'package-lock.json', '.package-lock.json'):
            p = os.path.join(stage, junk)
            if os.path.exists(p):
                os.remove(p)

        # Step 4: write our own wrapper. We DON'T use any `.cmd` shim
        # npm may have generated under `node_modules/.bin/` because its
        # path resolution is fragile. Instead, invoke cli.js directly
        # via node.exe.
        bin_dir = os.path.join(stage, 'bin')
        os.makedirs(bin_dir, exist_ok=True)
        wrapper = (
            '@echo off\r\n'
            'setlocal\r\n'
            'set "BUNDLE=%~dp0.."\r\n'
            'set "PATH=%BUNDLE%\\node;%PATH%"\r\n'
            '"%BUNDLE%\\node\\node.exe" '
            '"%BUNDLE%\\node_modules\\@anthropic-ai\\claude-code\\cli.js" %*\r\n'
        )
        wrapper_path = os.path.join(bin_dir, 'claude.cmd')
        with open(wrapper_path, 'w', newline='') as fh:
            fh.write(wrapper)
        print(f'  wrote wrapper {wrapper_path}')

        # Step 5: zip with flat root layout
        if os.path.exists(CLAUDE_CLI_BUNDLE_WINDOWS):
            os.remove(CLAUDE_CLI_BUNDLE_WINDOWS)
        print(f'Packaging to {CLAUDE_CLI_BUNDLE_WINDOWS}...')
        with zipfile.ZipFile(
            CLAUDE_CLI_BUNDLE_WINDOWS, 'w', zipfile.ZIP_DEFLATED
        ) as zf:
            for root, _dirs, files in os.walk(stage):
                for f in files:
                    src = os.path.join(root, f)
                    arcname = os.path.relpath(src, stage)
                    # Use forward slashes for arcnames (zip convention)
                    zf.write(src, arcname=arcname.replace(os.sep, '/'))

    size_mb = os.path.getsize(CLAUDE_CLI_BUNDLE_WINDOWS) / 1024 / 1024
    print(f'Claude CLI bundle created: {CLAUDE_CLI_BUNDLE_WINDOWS} ({size_mb:.1f} MB)')


def check_claude_windows() -> bool:
    """Check if the Claude CLI Windows bundle exists."""
    exists = os.path.exists(CLAUDE_CLI_BUNDLE_WINDOWS)
    if exists:
        mb = os.path.getsize(CLAUDE_CLI_BUNDLE_WINDOWS) / 1024 / 1024
        print(f'Claude CLI bundle exists: {CLAUDE_CLI_BUNDLE_WINDOWS} ({mb:.1f} MB)')
    else:
        print(f'Claude CLI bundle not found at {CLAUDE_CLI_BUNDLE_WINDOWS}')
        print('Run: python -m manager.dep_builder build-claude-windows')
    return exists


def build_all_windows():
    """Run all three Windows builds in sequence. Handy for smoke-testing."""
    print('=== 1/3: Python embed ===')
    build_python_windows_embed()
    print()
    print('=== 2/3: wheels bundle ===')
    build_windows_bundle()
    print()
    print('=== 3/3: Claude CLI bundle ===')
    build_claude_cli_windows()
    print()
    print('All Windows bundles built successfully.')


# >>> END CUSTOM <<<


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if cmd == 'build':
        build_bundle()
    elif cmd == 'check':
        check_bundle()
    elif cmd == 'build-windows':
        build_windows_bundle()
    elif cmd == 'check-windows':
        check_bundle_windows()
    # >>> CUSTOM: HiClaw — Windows auto-deploy helpers <<<
    elif cmd == 'build-python-windows':
        build_python_windows_embed()
    elif cmd == 'check-python-windows':
        check_python_windows()
    elif cmd == 'build-claude-windows':
        build_claude_cli_windows()
    elif cmd == 'check-claude-windows':
        check_claude_windows()
    elif cmd == 'build-all-windows':
        build_all_windows()
    # >>> END CUSTOM <<<
    else:
        print(f'Unknown command: {cmd}')
        print(
            'Usage: python -m manager.dep_builder '
            '[build|check|build-windows|check-windows|'
            'build-python-windows|check-python-windows|'
            'build-claude-windows|check-claude-windows|'
            'build-all-windows]'
        )
