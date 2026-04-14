"""Dependency builder — creates offline bundles for remote deployment.

Run this script on a machine with internet to pre-build the dependency bundle.
The bundle is then uploaded to internal machines via SFTP during provisioning.

Usage:
    python -m manager.dep_builder build       # Build the bundle
    python -m manager.dep_builder check       # Check if bundle exists
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

DEPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deps")
BUNDLE_PATH = os.path.join(DEPS_DIR, "agent-deps-bundle.tar.gz")
WHEELS_DIR = os.path.join(DEPS_DIR, "wheels")

# What to download
SDK_PACKAGES = "openhands-agent-server==1.16.1.post7 openhands-sdk==1.16.1 openhands-tools==1.16.1"
CODE_SERVER_VERSION = "4.96.4"


def build_bundle():
    """Download all dependencies and create the offline bundle."""
    os.makedirs(WHEELS_DIR, exist_ok=True)

    print(f"Downloading Python wheels to {WHEELS_DIR}...")
    subprocess.run(
        f"pip download {SDK_PACKAGES} --dest {WHEELS_DIR}",
        shell=True, check=True,
    )

    print(f"Downloading code-server v{CODE_SERVER_VERSION}...")
    cs_path = os.path.join(DEPS_DIR, "code-server.tar.gz")
    subprocess.run(
        f"curl -fL 'https://github.com/coder/code-server/releases/download/"
        f"v{CODE_SERVER_VERSION}/code-server-{CODE_SERVER_VERSION}-linux-amd64.tar.gz' "
        f"-o {cs_path}",
        shell=True, check=True,
    )

    print(f"Creating bundle at {BUNDLE_PATH}...")
    subprocess.run(
        f"tar czf {BUNDLE_PATH} -C {DEPS_DIR} wheels/ code-server.tar.gz",
        shell=True, check=True,
    )

    size_mb = os.path.getsize(BUNDLE_PATH) / 1024 / 1024
    print(f"Bundle created: {BUNDLE_PATH} ({size_mb:.1f} MB)")


def check_bundle() -> bool:
    """Check if the offline bundle exists."""
    exists = os.path.exists(BUNDLE_PATH)
    if exists:
        size_mb = os.path.getsize(BUNDLE_PATH) / 1024 / 1024
        print(f"Bundle exists: {BUNDLE_PATH} ({size_mb:.1f} MB)")
    else:
        print(f"Bundle not found at {BUNDLE_PATH}")
        print(f"Run: python -m manager.dep_builder build")
    return exists


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "build":
        build_bundle()
    elif cmd == "check":
        check_bundle()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m manager.dep_builder [build|check]")
