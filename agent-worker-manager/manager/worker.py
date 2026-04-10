"""Worker lifecycle management — create, start, health-check, destroy."""

from __future__ import annotations

import asyncio
import logging
import random

import httpx

from .models import CreateWorkerRequest, WorkerInfo, WorkerMode, WorkerStatus
from .ssh_client import SSHClient

logger = logging.getLogger(__name__)

# Template configs (loaded from config.yaml in production)
TEMPLATES = {
    "openhands": {
        "docker": {
            "image": "ghcr.io/openhands/agent-server:1.16.1-python",
            "port": 8000,
            "health_check": "/health",
        },
        "host": {
            "command": "{REMOTE_VENV_PATH}/bin/agent-server --port {port}",
            "port": 8000,
            "health_check": "/health",
        },
    },
}


def _pick_port() -> int:
    """Pick a random high port to avoid collisions."""
    return random.randint(20000, 50000)


class WorkerManager:
    """Manages workers on remote machines via SSH."""

    def __init__(self):
        self._workers: dict[str, WorkerInfo] = {}
        self._ssh_clients: dict[str, SSHClient] = {}
        self._remote_ports: dict[str, int] = {}
        self._local_ports: dict[str, int] = {}  # SSH tunnel local ports
        self._listeners: dict[str, object] = {}  # SSH tunnel listeners

    async def create_worker(self, req: CreateWorkerRequest, manager_base_url: str) -> WorkerInfo:
        """Create a new worker on the remote machine."""
        worker = WorkerInfo(
            host=req.host,
            port=req.port,
            username=req.username,
            mode=req.mode,
            template=req.template,
            workspace=req.workspace,
        )

        # Determine the remote port for agent-server
        remote_port = req.agent_server_port or _pick_port()
        worker.agent_server_port = remote_port

        self._workers[worker.id] = worker

        try:
            # 1. SSH connect
            worker.status = WorkerStatus.CREATING
            ssh = SSHClient(
                host=req.host,
                port=req.port,
                username=req.username,
                password=req.password,
                private_key=req.private_key,
            )
            await ssh.connect()
            self._ssh_clients[worker.id] = ssh

            # 2. Start agent-server
            worker.status = WorkerStatus.STARTING
            if req.mode == WorkerMode.DOCKER:
                await self._start_docker(ssh, worker)
            else:
                await self._start_host(ssh, worker)

            # 3. Health check via SSH (run curl on remote machine)
            await self._wait_healthy_via_ssh(ssh, remote_port, worker)

            # 4. Set up SSH tunnel: localhost:local_port → remote:remote_port
            local_port = _pick_port()
            listener = await ssh.forward_local_port(remote_port, local_port)
            self._listeners[worker.id] = listener
            self._local_ports[worker.id] = local_port
            self._remote_ports[worker.id] = remote_port

            # The proxy URL points to the SSH tunnel — supports HTTP + WebSocket
            worker.proxy_url = f"http://localhost:{local_port}"

            worker.status = WorkerStatus.RUNNING
            logger.info(f"Worker {worker.id} running on {req.host}:{remote_port}, tunnel localhost:{local_port}")

        except Exception as e:
            worker.status = WorkerStatus.ERROR
            worker.error = str(e) or repr(e)
            logger.error(f"Worker {worker.id} failed: {e}", exc_info=True)

        return worker

    async def _start_docker(self, ssh: SSHClient, worker: WorkerInfo) -> None:
        """Start agent-server as a Docker container on the remote machine."""
        tmpl = TEMPLATES.get(worker.template, {}).get("docker", {})
        image = tmpl.get("image", "ghcr.io/openhands/agent-server:1.16.1-python")
        container_port = tmpl.get("port", 8000)

        container_name = f"agent-worker-{worker.id}"

        # Ensure workspace directory exists
        await ssh.run(f"mkdir -p {worker.workspace}")

        # Run the container
        cmd = (
            f"docker run -d --name {container_name} "
            f"-p {worker.agent_server_port}:{container_port} "
            f"-v {worker.workspace}:/workspace/project "
            f"--add-host=host.docker.internal:host-gateway "
            f"{image} --port {container_port}"
        )
        stdout, stderr, exit_code = await ssh.run(cmd, timeout=120)
        if exit_code != 0:
            raise RuntimeError(f"Docker run failed: {stderr}")

        worker.container_id = stdout[:12]
        logger.info(f"Container {worker.container_id} started on {worker.host}")

    async def _start_host(self, ssh: SSHClient, worker: WorkerInfo) -> None:
        """Start agent-server as a process on the remote machine."""
        tmpl = TEMPLATES.get(worker.template, {}).get("host", {})
        cmd_template = tmpl.get("command", "openhands-agent-server --port {port}")
        cmd = cmd_template.format(port=worker.agent_server_port)

        # Ensure workspace directory exists
        await ssh.run(f"mkdir -p {worker.workspace}")

        # Start in background with log file
        # >>> CUSTOM: HiClaw — bypass proxy on remote machine for localhost <<<
        log_file = f"/tmp/agent-worker-{worker.id}.log"
        env_prefix = "export no_proxy=localhost,127.0.0.1; export NO_PROXY=localhost,127.0.0.1; "
        pid_str = await ssh.run_background(f"{env_prefix}cd {worker.workspace} && {cmd}", log_file=log_file)
        try:
            worker.pid = int(pid_str)
        except (ValueError, TypeError):
            worker.pid = 0
        logger.info(f"Process started on {worker.host}, PID={worker.pid}, log={log_file}")

    async def _wait_healthy_via_ssh(self, ssh: SSHClient, remote_port: int, worker: WorkerInfo, timeout: int = 90) -> None:
        """Wait for the remote agent-server to become healthy by running curl on the remote machine."""
        tmpl = TEMPLATES.get(worker.template, {}).get(worker.mode.value, {})
        health_path = tmpl.get("health_check", "/health")

        logger.info(f"Waiting for health check on {ssh.host}:{remote_port}{health_path}")
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            try:
                # >>> CUSTOM: HiClaw — bypass proxy for localhost health check <<<
                stdout, stderr, exit_code = await ssh.run(
                    f"curl --noproxy localhost -s -o /dev/null -w '%{{http_code}}' http://localhost:{remote_port}{health_path}",
                    timeout=5,
                )
                if stdout.strip() == "200":
                    logger.info(f"Health check passed for worker {worker.id}")
                    return
            except Exception:
                pass
            await asyncio.sleep(2)

        raise TimeoutError(f"Worker {worker.id} health check timed out after {timeout}s")

    def get_worker(self, worker_id: str) -> WorkerInfo | None:
        return self._workers.get(worker_id)

    def list_workers(self) -> list[WorkerInfo]:
        return list(self._workers.values())

    def get_ssh_client(self, worker_id: str) -> SSHClient | None:
        return self._ssh_clients.get(worker_id)

    def get_worker_remote_addr(self, worker_id: str) -> tuple[str, int] | None:
        """Get the remote host:port for a worker."""
        worker = self._workers.get(worker_id)
        remote_port = self._remote_ports.get(worker_id)
        if worker and remote_port:
            return (worker.host, remote_port)
        return None

    async def delete_worker(self, worker_id: str) -> bool:
        """Stop and clean up a worker."""
        worker = self._workers.get(worker_id)
        if not worker:
            return False

        ssh = self._ssh_clients.get(worker_id)

        try:
            if ssh and ssh.connected:
                if worker.mode == WorkerMode.DOCKER and worker.container_id:
                    await ssh.run(f"docker rm -f agent-worker-{worker_id}", timeout=30)
                elif worker.mode == WorkerMode.HOST and worker.pid:
                    await ssh.run(f"kill {worker.pid}", timeout=10)
        except Exception as e:
            logger.warning(f"Cleanup error for worker {worker_id}: {e}")

        self._remote_ports.pop(worker_id, None)
        self._local_ports.pop(worker_id, None)
        listener = self._listeners.pop(worker_id, None)
        if listener and hasattr(listener, 'close'):
            listener.close()

        # Close SSH
        if ssh:
            await ssh.close()
            self._ssh_clients.pop(worker_id, None)

        worker.status = WorkerStatus.STOPPED
        self._workers.pop(worker_id, None)

        logger.info(f"Worker {worker_id} deleted")
        return True
