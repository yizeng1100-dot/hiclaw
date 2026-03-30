"""Machine Manager — manages remote machines, not individual sessions."""

from __future__ import annotations

import asyncio
import os
import logging
import random

import httpx

from .models import (
    ConnectMachineRequest,
    MachineInfo,
    MachineStatus,
    ProvisionEvent,
    ProvisionStep,
    WorkerMode,
    compute_machine_id,
)
from .provisioner import Provisioner, TEMPLATES
from .ssh_client import SSHClient

logger = logging.getLogger(__name__)


def _pick_port() -> int:
    return random.randint(20000, 50000)


class MachineManager:
    """Manages remote machines. One machine = one agent-server, many conversations."""

    def __init__(self):
        self._machines: dict[str, MachineInfo] = {}
        self._ssh_clients: dict[str, SSHClient] = {}
        self._local_ports: dict[str, int] = {}
        self._listeners: dict[str, object] = {}
        self._event_queues: dict[str, list[asyncio.Queue]] = {}
        self._provision_locks: dict[str, asyncio.Lock] = {}

    async def connect_machine(self, req: ConnectMachineRequest) -> MachineInfo:
        """Idempotent connect. Returns existing machine if already ready."""
        machine_id = compute_machine_id(req.host, req.port, req.username)

        if machine_id in self._machines:
            machine = self._machines[machine_id]
            if machine.status == MachineStatus.READY:
                machine.active_conversations += 1
                # Update workspace if changed
                if req.workspace != machine.workspace:
                    machine.workspace = req.workspace
                    logger.info(f"Machine {machine_id} workspace updated to {req.workspace}")
                # Always sync skills on reconnect
                ssh = self._ssh_clients.get(machine_id)
                if ssh and ssh.connected:
                    asyncio.create_task(self._clone_skills_repo(ssh, machine))
                return machine
            if machine.status in (MachineStatus.CONNECTING, MachineStatus.PROVISIONING, MachineStatus.STARTING):
                # Already in progress — caller should subscribe to SSE
                return machine
            if machine.status == MachineStatus.ERROR:
                await self._cleanup_machine(machine_id)

        # New machine
        machine = MachineInfo(
            id=machine_id,
            host=req.host,
            port=req.port,
            username=req.username,
            mode=req.mode,
            template=req.template,
            workspace=req.workspace,
            agent_server_port=req.agent_server_port,
        )
        self._machines[machine_id] = machine
        self._event_queues[machine_id] = []
        self._provision_locks[machine_id] = asyncio.Lock()

        # Start provisioning in background
        asyncio.create_task(self._run_provisioning(machine_id, req))
        return machine

    def subscribe_events(self, machine_id: str) -> asyncio.Queue:
        """Subscribe to provisioning events for a machine."""
        q: asyncio.Queue = asyncio.Queue()
        if machine_id not in self._event_queues:
            self._event_queues[machine_id] = []
        self._event_queues[machine_id].append(q)

        # Send all past events immediately
        machine = self._machines.get(machine_id)
        if machine:
            for evt in machine.provision_steps:
                q.put_nowait(evt)

        return q

    def unsubscribe_events(self, machine_id: str, q: asyncio.Queue) -> None:
        queues = self._event_queues.get(machine_id, [])
        if q in queues:
            queues.remove(q)

    def _broadcast_event(self, machine_id: str, event: ProvisionEvent) -> None:
        """Broadcast event to all subscribers and store in history."""
        machine = self._machines.get(machine_id)
        if machine:
            machine.provision_steps.append(event)
        for q in self._event_queues.get(machine_id, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def _run_provisioning(self, machine_id: str, req: ConnectMachineRequest) -> None:
        """Full provisioning flow: SSH → provision → start → tunnel."""
        machine = self._machines[machine_id]

        async with self._provision_locks[machine_id]:
            try:
                # Step 1: SSH connect
                evt = ProvisionEvent(step=ProvisionStep.SSH_CONNECT, status="started")
                self._broadcast_event(machine_id, evt)
                machine.status = MachineStatus.CONNECTING

                ssh = SSHClient(
                    host=req.host,
                    port=req.port,
                    username=req.username,
                    password=req.password,
                    private_key=req.private_key,
                )
                await ssh.connect()
                self._ssh_clients[machine_id] = ssh

                evt = ProvisionEvent(step=ProvisionStep.SSH_CONNECT, status="completed")
                self._broadcast_event(machine_id, evt)

                # Step 2: Provision (check/install deps)
                machine.status = MachineStatus.PROVISIONING
                provisioner = Provisioner(
                    ssh, template=req.template,
                    broadcast_fn=lambda evt, mid=machine_id: self._broadcast_event(mid, evt),
                )
                async for evt in provisioner.provision():
                    self._broadcast_event(machine_id, evt)
                    if evt.status == "failed":
                        raise RuntimeError(f"Provisioning failed at {evt.step}: {evt.detail}")

                # Step 3: Clone skills repo
                evt = ProvisionEvent(step=ProvisionStep.CLONE_SKILLS, status="started")
                self._broadcast_event(machine_id, evt)

                await self._clone_skills_repo(ssh, machine)

                evt = ProvisionEvent(step=ProvisionStep.CLONE_SKILLS, status="completed")
                self._broadcast_event(machine_id, evt)

                # Step 4: Start agent-server
                machine.status = MachineStatus.STARTING
                evt = ProvisionEvent(step=ProvisionStep.START_AGENT_SERVER, status="started")
                self._broadcast_event(machine_id, evt)

                await self._start_agent_server(ssh, machine)

                evt = ProvisionEvent(step=ProvisionStep.START_AGENT_SERVER, status="completed")
                self._broadcast_event(machine_id, evt)

                # Step 4: Health check
                evt = ProvisionEvent(step=ProvisionStep.HEALTH_CHECK, status="started")
                self._broadcast_event(machine_id, evt)

                await self._wait_healthy(ssh, machine)

                evt = ProvisionEvent(step=ProvisionStep.HEALTH_CHECK, status="completed")
                self._broadcast_event(machine_id, evt)

                # Step 5: Start code-server (if installed)
                await self._start_code_server(ssh, machine)

                # Step 6: SSH tunnels
                evt = ProvisionEvent(step=ProvisionStep.SETUP_TUNNEL, status="started")
                self._broadcast_event(machine_id, evt)

                # Tunnel for agent-server
                local_port = _pick_port()
                listener = await ssh.forward_local_port(machine.agent_server_port, local_port)
                self._listeners[machine_id] = listener
                self._local_ports[machine_id] = local_port
                machine.tunnel_port = local_port
                machine.proxy_url = f"http://localhost:{local_port}"

                # Tunnel for code-server (if running) — fixed port for easy SSH forwarding
                if machine.code_server_port:
                    cs_local_port = 18443  # Fixed port so user can SSH -L 18443:localhost:18443
                    cs_listener = await ssh.forward_local_port(machine.code_server_port, cs_local_port)
                    self._listeners[f"{machine_id}_cs"] = cs_listener
                    machine.code_server_tunnel_port = cs_local_port
                    machine.vscode_url = f"http://localhost:{cs_local_port}"
                    logger.info(f"Code-server tunnel: localhost:{cs_local_port} → remote:{machine.code_server_port}")

                evt = ProvisionEvent(step=ProvisionStep.SETUP_TUNNEL, status="completed",
                                     detail=f"agent:localhost:{local_port}" + (f" vscode:localhost:{machine.code_server_tunnel_port}" if machine.vscode_url else ""))
                self._broadcast_event(machine_id, evt)

                # Done!
                machine.status = MachineStatus.READY
                machine.active_conversations = 1
                logger.info(f"Machine {machine_id} ready: {req.host}:{machine.agent_server_port} → localhost:{local_port}")

            except Exception as e:
                machine.status = MachineStatus.ERROR
                machine.error = str(e) or repr(e)
                logger.error(f"Machine {machine_id} provisioning failed: {e}", exc_info=True)

    async def _clone_skills_repo(self, ssh: SSHClient, machine: MachineInfo) -> None:
        """Clone or update HiClaw skills repo via SSH reverse tunnel + git daemon."""
        skills_dir = f"{machine.workspace}/.hiclaw/skills"
        GIT_PORT = 19418

        # Start git daemon on app-server (needed for both clone and pull)
        import subprocess
        git_daemon = subprocess.Popen(
            ["git", "daemon", "--reuseaddr", f"--port={GIT_PORT}",
             "--export-all", "--enable=receive-pack",
             f"--base-path={os.environ.get('HICLAW_DIR', '/opt/hiclaw')}", os.environ.get('HICLAW_DIR', '/opt/hiclaw')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        try:
            # Create reverse tunnel: remote:19418 → app-server:19418
            listener = await ssh._conn.forward_remote_port("", GIT_PORT, "localhost", GIT_PORT)

            # Check if already cloned
            stdout, _, ec = await ssh.run(f"test -d {skills_dir}/.git && echo YES || echo NO", timeout=5)

            if stdout.strip() == "YES":
                # Pull latest — merge, don't reset (preserve local edits)
                await ssh.run(
                    f"cd {skills_dir} && git pull --rebase origin master 2>/dev/null || git pull origin master || true",
                    timeout=30,
                )
                logger.info(f"Skills repo updated on {machine.host}")
            else:
                # Fresh clone
                await ssh.run(f"mkdir -p {machine.workspace}/.hiclaw", timeout=5)
                await ssh.run(
                    f"cd {machine.workspace}/.hiclaw && "
                    f"git clone git://localhost:{GIT_PORT}/skills-repo.git skills",
                    timeout=60,
                )
                await ssh.run(
                    f"cd {skills_dir} && "
                    f"git config user.email 'user@hiclaw' && "
                    f"git config user.name 'HiClaw User'",
                    timeout=5,
                )
                logger.info(f"Skills repo cloned to {skills_dir} on {machine.host}")

            listener.close()
        finally:
            git_daemon.terminate()
            git_daemon.wait()

    async def _start_agent_server(self, ssh: SSHClient, machine: MachineInfo) -> None:
        """Start agent-server on the remote machine."""
        tmpl = TEMPLATES.get(machine.template, TEMPLATES["openhands"])
        binary = tmpl["binary"]
        port = machine.agent_server_port

        # Check if agent-server is already running on this port
        stdout, _, ec = await ssh.run(f"curl -s --max-time 2 http://localhost:{port}/health", timeout=5)
        if ec == 0 and "OK" in stdout:
            logger.info(f"Agent-server already running on {machine.host}:{port}")
            return

        # Ensure workspace exists
        await ssh.run(f"mkdir -p {machine.workspace}")

        # Start in background, pass through debug env vars from app-server
        log_file = f"/tmp/agent-server-{machine.id}.log"
        env_vars = ""
        if os.environ.get('HICLAW_LLM_DEBUG'):
            env_vars += "HICLAW_LLM_DEBUG=1 "
        cmd = f"cd {machine.workspace} && {env_vars}{binary} --port {port}"
        await ssh.run_background(cmd, log_file=log_file)
        logger.info(f"Started agent-server on {machine.host}:{port}")

    async def _start_code_server(self, ssh: SSHClient, machine: MachineInfo) -> None:
        """Start code-server on the remote machine if installed."""
        _, _, ec = await ssh.run("which code-server", timeout=5)
        if ec != 0:
            logger.info(f"code-server not installed on {machine.host}, skipping")
            machine.code_server_port = 0
            return

        # Set dark theme to match container VS Code
        await ssh.run(
            "mkdir -p ~/.local/share/code-server/User && "
            "cat > ~/.local/share/code-server/User/settings.json << 'VSEOF'\n"
            '{"workbench.colorTheme":"Default Dark Modern","workbench.startupEditor":"none","telemetry.telemetryLevel":"off"}\n'
            "VSEOF",
            timeout=5,
        )

        cs_port = machine.code_server_port or 8443

        # Check if already running
        stdout, _, ec = await ssh.run(f"curl -s --max-time 2 -o /dev/null -w '%{{http_code}}' http://localhost:{cs_port}", timeout=5)
        if stdout.strip() == "200":
            logger.info(f"code-server already running on {machine.host}:{cs_port}")
            machine.code_server_port = cs_port
            return

        # Start code-server with no auth, bound to workspace
        log_file = f"/tmp/code-server-{machine.id}.log"
        cmd = (
            f"code-server --port {cs_port} --host 0.0.0.0 "
            f"--auth none --disable-telemetry "
            f"{machine.workspace}"
        )
        await ssh.run_background(cmd, log_file=log_file)
        machine.code_server_port = cs_port

        # Wait for it to start
        for _ in range(15):
            await asyncio.sleep(2)
            stdout, _, ec = await ssh.run(
                f"curl -s --max-time 2 -o /dev/null -w '%{{http_code}}' http://localhost:{cs_port}",
                timeout=5,
            )
            if stdout.strip() == "200":
                logger.info(f"code-server started on {machine.host}:{cs_port}")
                return
        logger.warning(f"code-server may not have started on {machine.host}:{cs_port}")

    async def _wait_healthy(self, ssh: SSHClient, machine: MachineInfo, timeout: int = 90) -> None:
        """Wait for agent-server to become healthy."""
        port = machine.agent_server_port
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                stdout, _, ec = await ssh.run(
                    f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{port}/health",
                    timeout=5,
                )
                if stdout.strip() == "200":
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
        raise TimeoutError(f"Agent-server health check timed out after {timeout}s")

    # ─── Query / Lifecycle ──────────────────────────────

    def get_machine(self, machine_id: str) -> MachineInfo | None:
        return self._machines.get(machine_id)

    def list_machines(self) -> list[MachineInfo]:
        return list(self._machines.values())

    def get_ssh_client(self, machine_id: str) -> SSHClient | None:
        return self._ssh_clients.get(machine_id)

    def get_tunnel_port(self, machine_id: str) -> int | None:
        return self._local_ports.get(machine_id)

    async def disconnect_machine(self, machine_id: str) -> bool:
        """Disconnect and clean up a machine."""
        machine = self._machines.get(machine_id)
        if not machine:
            return False
        await self._cleanup_machine(machine_id)
        return True

    async def _cleanup_machine(self, machine_id: str) -> None:
        """Clean up all resources for a machine."""
        machine = self._machines.get(machine_id)
        ssh = self._ssh_clients.get(machine_id)

        try:
            if ssh and ssh.connected and machine:
                if machine.mode == WorkerMode.DOCKER:
                    await ssh.run(f"docker rm -f agent-server-{machine_id}", timeout=30)
                else:
                    await ssh.run(f"pkill -f 'agent-server --port {machine.agent_server_port}' || true", timeout=10)
        except Exception as e:
            logger.warning(f"Cleanup error for machine {machine_id}: {e}")

        self._local_ports.pop(machine_id, None)
        listener = self._listeners.pop(machine_id, None)
        if listener and hasattr(listener, 'close'):
            listener.close()

        if ssh:
            await ssh.close()
            self._ssh_clients.pop(machine_id, None)

        self._machines.pop(machine_id, None)
        self._event_queues.pop(machine_id, None)
        self._provision_locks.pop(machine_id, None)
        logger.info(f"Machine {machine_id} cleaned up")
