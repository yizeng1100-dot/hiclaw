"""SSH connection management using asyncssh."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncssh

logger = logging.getLogger(__name__)


class SSHClient:
    """Manages SSH connections to remote machines."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "root",
        password: str | None = None,
        private_key: str | None = None,
        connect_timeout: int = 10,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.connect_timeout = connect_timeout
        self._conn: asyncssh.SSHClientConnection | None = None
        self._bg_processes: list = []

    async def connect(self) -> None:
        """Establish SSH connection."""
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "known_hosts": None,  # Accept any host key (internal network)
            "login_timeout": self.connect_timeout,
        }
        if self.password:
            kwargs["password"] = self.password
        if self.private_key:
            kwargs["client_keys"] = [asyncssh.import_private_key(self.private_key)]

        logger.info(f"Connecting to {self.username}@{self.host}:{self.port}")
        self._conn = await asyncssh.connect(**kwargs)
        logger.info(f"Connected to {self.host}")

    async def run(self, command: str, timeout: int = 60) -> tuple[str, str, int]:
        """Execute a command and return (stdout, stderr, exit_code)."""
        if self._conn is None:
            raise RuntimeError("Not connected")

        logger.debug(f"[{self.host}] $ {command}")
        try:
            result = await asyncio.wait_for(
                self._conn.run(command),
                timeout=timeout,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = result.exit_status or 0
            if exit_code != 0:
                logger.warning(f"[{self.host}] exit={exit_code} stderr={stderr[:200]}")
            return stdout.strip(), stderr.strip(), exit_code
        except asyncio.TimeoutError:
            logger.error(f"[{self.host}] Command timed out: {command[:100]}")
            raise

    async def run_background(self, command: str, log_file: str = "/dev/null") -> str:
        """Execute a command in the background via create_process.

        The process stays alive as long as the SSH connection is alive.
        We keep the process channel open (stored in _bg_processes).
        """
        if self._conn is None:
            raise RuntimeError("Not connected")

        logger.debug(f"[{self.host}] (bg) $ {command}")

        # Start process — don't wait for it to finish
        full_cmd = f"{command} > {log_file} 2>&1"
        process = await self._conn.create_process(full_cmd)
        self._bg_processes.append(process)

        # Give it a moment to start, then find its PID
        await asyncio.sleep(2)
        stdout, _, _ = await self.run(
            f"pgrep -f '{command.split('/')[-1].split()[0]}' | tail -1",
            timeout=5,
        )
        pid = stdout.strip()
        logger.info(f"[{self.host}] Background PID: {pid}")
        return pid

    async def write_file(self, remote_path: str, content: bytes) -> None:
        """Write binary content to a file on the remote machine via SFTP."""
        if self._conn is None:
            raise RuntimeError("Not connected")
        async with self._conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, 'wb') as f:
                await f.write(content)
        logger.debug(f"[{self.host}] Wrote {len(content)} bytes to {remote_path}")

    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        progress_callback: object = None,
    ) -> None:
        """Upload a local file to remote via SFTP with progress tracking.

        Args:
            progress_callback: Optional callable(bytes_sent, total_bytes) called periodically.
        """
        if self._conn is None:
            raise RuntimeError("Not connected")
        import os
        total = os.path.getsize(local_path)

        def _progress(src_path, dst_path, bytes_sent, total_bytes):
            if progress_callback and callable(progress_callback):
                progress_callback(bytes_sent, total_bytes)

        async with self._conn.start_sftp_client() as sftp:
            await sftp.put(local_path, remote_path, progress_handler=_progress, block_size=65536)

        logger.info(f"[{self.host}] Uploaded {local_path} → {remote_path} ({total} bytes)")

    async def forward_local_port(self, remote_port: int, local_port: int) -> None:
        """Create a local port forward: localhost:local_port → remote:remote_port."""
        if self._conn is None:
            raise RuntimeError("Not connected")
        listener = await self._conn.forward_local_port("", local_port, "localhost", remote_port)
        logger.info(f"Port forward: localhost:{local_port} → remote:localhost:{remote_port}")
        return listener

    async def close(self) -> None:
        """Close SSH connection."""
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
            logger.info(f"Disconnected from {self.host}")

    @property
    def connected(self) -> bool:
        return self._conn is not None and not self._conn.is_closed()
