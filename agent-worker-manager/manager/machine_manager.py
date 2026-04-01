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
                ssh = self._ssh_clients.get(machine_id)
                # Update workspace if changed — restart agent-server + code-server
                if req.workspace != machine.workspace:
                    old_workspace = machine.workspace
                    machine.workspace = req.workspace
                    logger.info(f"Machine {machine_id} workspace changed: {old_workspace} → {req.workspace}")
                    if ssh and ssh.connected:
                        # Restart agent-server with new workspace
                        await self._start_agent_server(ssh, machine)
                        # Restart code-server with new workspace
                        port = machine.agent_server_port
                        await ssh.run(f"pkill -f 'code-server.*--port {machine.code_server_port}' 2>/dev/null || true", timeout=5)
                        await asyncio.sleep(1)
                        await self._start_code_server(ssh, machine)
                # Always sync skills on reconnect
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

                # Read CoMagic token from remote (always, regardless of agent-server state)
                token_out, _, _ = await ssh.run(
                    "cat ~/.comagic/userToken.json 2>/dev/null || echo '{}'",
                    timeout=5,
                )
                try:
                    import json as _json
                    _comagic = _json.loads(token_out.strip())
                    if _comagic.get('token'):
                        machine.comagic_token = _comagic['token']
                    if _comagic.get('xUserId'):
                        machine.comagic_user_id = _comagic['xUserId']
                    if _comagic.get('token'):
                        logger.info(f"CoMagic token loaded for {machine.host}")
                except Exception:
                    pass

                # Step 4: Health check first — if agent-server already running and healthy, skip start
                machine.status = MachineStatus.STARTING
                port = machine.agent_server_port
                evt = ProvisionEvent(step=ProvisionStep.HEALTH_CHECK, status="started",
                                     detail="Checking existing agent-server...")
                self._broadcast_event(machine_id, evt)

                already_healthy = False
                try:
                    h_out, _, h_ec = await ssh.run(
                        f"no_proxy=localhost,127.0.0.1 curl -s -o /dev/null -w '%{{http_code}}' --max-time 3 http://localhost:{port}/health",
                        timeout=5,
                    )
                    if h_out.strip() == "200":
                        # Verify workspace matches
                        ps_out, _, _ = await ssh.run(
                            f"ps aux | grep 'agent-server.*--port {port}' | grep -v grep | head -1",
                            timeout=5,
                        )
                        if machine.workspace in ps_out:
                            already_healthy = True
                            logger.info(f"Agent-server already healthy on port {port}, reusing")
                        else:
                            logger.info(f"Agent-server on port {port} has wrong workspace, will restart")
                except Exception:
                    pass

                if already_healthy:
                    evt = ProvisionEvent(step=ProvisionStep.HEALTH_CHECK, status="completed",
                                         detail="Already running")
                    self._broadcast_event(machine_id, evt)
                    evt = ProvisionEvent(step=ProvisionStep.START_AGENT_SERVER, status="completed",
                                         detail="Already running")
                    self._broadcast_event(machine_id, evt)
                else:
                    # Not healthy — kill old process, start fresh
                    evt = ProvisionEvent(step=ProvisionStep.START_AGENT_SERVER, status="started")
                    self._broadcast_event(machine_id, evt)

                    await self._start_agent_server(ssh, machine)

                    evt = ProvisionEvent(step=ProvisionStep.START_AGENT_SERVER, status="completed")
                    self._broadcast_event(machine_id, evt)

                    # Now wait for health
                    import time as _time
                    _hc_start = _time.monotonic()
                    evt = ProvisionEvent(step=ProvisionStep.HEALTH_CHECK, status="started",
                                         detail="Waiting for agent-server to start...")
                    self._broadcast_event(machine_id, evt)

                    await self._wait_healthy(ssh, machine)

                    _hc_elapsed = int(_time.monotonic() - _hc_start)
                    evt = ProvisionEvent(step=ProvisionStep.HEALTH_CHECK, status="completed",
                                         detail=f"Healthy ({_hc_elapsed}s)")
                    self._broadcast_event(machine_id, evt)
                    logger.info(f"Health check took {_hc_elapsed}s")

                # Step 5: Start code-server (if installed)
                import time as _time
                _cs_start = _time.monotonic()
                evt = ProvisionEvent(step=ProvisionStep.INSTALL_CODE_SERVER, status="started",
                                     detail="Starting code-server...")
                self._broadcast_event(machine_id, evt)
                await self._start_code_server(ssh, machine)
                _cs_elapsed = int(_time.monotonic() - _cs_start)
                if machine.code_server_port:
                    evt = ProvisionEvent(step=ProvisionStep.INSTALL_CODE_SERVER, status="completed",
                                         detail=f"Running on port {machine.code_server_port} ({_cs_elapsed}s)")
                else:
                    evt = ProvisionEvent(step=ProvisionStep.INSTALL_CODE_SERVER, status="skipped",
                                         detail=f"Not installed ({_cs_elapsed}s)")
                self._broadcast_event(machine_id, evt)
                logger.info(f"code-server step took {_cs_elapsed}s")

                # Step 6: SSH tunnels
                evt = ProvisionEvent(step=ProvisionStep.SETUP_TUNNEL, status="started",
                                     detail="Creating SSH tunnels...")
                self._broadcast_event(machine_id, evt)

                try:
                    # Tunnel for agent-server
                    local_port = _pick_port()
                    logger.info(f"Creating agent-server tunnel: localhost:{local_port} → remote:{machine.agent_server_port}")
                    listener = await ssh.forward_local_port(machine.agent_server_port, local_port)
                    self._listeners[machine_id] = listener
                    self._local_ports[machine_id] = local_port
                    machine.tunnel_port = local_port
                    machine.proxy_url = f"http://localhost:{local_port}"

                    # Tunnel for code-server (if running) — fixed port for easy SSH forwarding
                    if machine.code_server_port:
                        cs_local_port = 18443
                        logger.info(f"Creating code-server tunnel: localhost:{cs_local_port} → remote:{machine.code_server_port}")
                        try:
                            cs_listener = await ssh.forward_local_port(machine.code_server_port, cs_local_port)
                            self._listeners[f"{machine_id}_cs"] = cs_listener
                            machine.code_server_tunnel_port = cs_local_port
                            machine.vscode_url = f"http://localhost:{cs_local_port}"
                        except Exception as cs_e:
                            logger.warning(f"Code-server tunnel failed (non-fatal): {cs_e}")

                    evt = ProvisionEvent(step=ProvisionStep.SETUP_TUNNEL, status="completed",
                                         detail=f"agent:localhost:{local_port}" + (f" vscode:localhost:{machine.code_server_tunnel_port}" if machine.vscode_url else ""))
                    self._broadcast_event(machine_id, evt)
                except Exception as tunnel_e:
                    logger.error(f"Tunnel creation failed: {tunnel_e}")
                    evt = ProvisionEvent(step=ProvisionStep.SETUP_TUNNEL, status="failed",
                                         detail=str(tunnel_e)[:500])
                    self._broadcast_event(machine_id, evt)
                    raise

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
             f"--base-path={os.environ.get('HICLAW_DIR', os.path.join(os.path.expanduser('~'), '.hiclaw'))}", os.environ.get('HICLAW_DIR', os.path.join(os.path.expanduser('~'), '.hiclaw'))],
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
        """Start agent-server on the remote machine.

        Logic:
        1. Check if port already has a healthy agent-server → reuse or kill+restart
        2. Kill any leftover process on the port
        3. Start fresh
        """
        tmpl = TEMPLATES.get(machine.template, TEMPLATES["openhands"])
        binary = tmpl["binary"]
        port = machine.agent_server_port

        # Find actual binary — check new path first, fall back to legacy
        stdout, _, _ = await ssh.run(f"test -f {binary} && echo FOUND || echo MISSING", timeout=5)
        if stdout.strip() != "FOUND":
            stdout2, _, _ = await ssh.run("test -f /opt/agent-venv/bin/agent-server && echo FOUND || echo MISSING", timeout=5)
            if stdout2.strip() == "FOUND":
                binary = "/opt/agent-venv/bin/agent-server"
                logger.info(f"Using legacy binary path: {binary}")

        # Step 1: Check if something is already listening on the port
        health_out, _, health_ec = await ssh.run(
            f"no_proxy=localhost,127.0.0.1 curl -s -o /dev/null -w '%{{http_code}}' --max-time 3 http://localhost:{port}/health",
            timeout=5,
        )
        port_healthy = health_out.strip() == "200"

        if port_healthy:
            # Something healthy on the port — check if it's our agent-server with right workspace
            check_stdout, _, _ = await ssh.run(
                f"ps aux | grep 'agent-server.*--port {port}' | grep -v grep | head -1", timeout=5)
            if machine.workspace in check_stdout:
                logger.info(f"Agent-server already running in {machine.workspace}, reusing")
                return
            else:
                logger.info(f"Port {port} occupied (wrong workspace or other process), killing")
                await ssh.run(f"fuser -k {port}/tcp 2>/dev/null || pkill -f 'agent-server.*--port {port}' || true", timeout=5)
                await asyncio.sleep(2)
        else:
            # Port not healthy — kill any leftover agent-server process on this port
            await ssh.run(f"pkill -f 'agent-server.*--port {port}' 2>/dev/null || true", timeout=5)
            # Also kill anything else holding the port
            await ssh.run(f"fuser -k {port}/tcp 2>/dev/null || true", timeout=5)
            await asyncio.sleep(1)

        # Step 2: Ensure workspace exists
        await ssh.run(f"mkdir -p {machine.workspace}/.hiclaw")

        # Step 3: Start in background
        log_file = f"/tmp/agent-server-{machine.id}.log"
        # no_proxy: corporate proxies intercept localhost + app-server IP connections
        app_ip = os.environ.get('HICLAW_APP_IP', '')
        no_proxy_list = f"localhost,127.0.0.1{f',{app_ip}' if app_ip else ''}"
        env_vars = f"no_proxy={no_proxy_list} NO_PROXY={no_proxy_list} "
        # Store conversation data in workspace/.hiclaw/ (separate from project files)
        env_vars += f"FILE_STORE_PATH={machine.workspace}/.hiclaw "
        if os.environ.get('HICLAW_LLM_DEBUG'):
            env_vars += "HICLAW_LLM_DEBUG=1 "
        # Read CoMagic token from remote machine's ~/.comagic/userToken.json
        token_out, _, _ = await ssh.run(
            "cat ~/.comagic/userToken.json 2>/dev/null || echo '{}'",
            timeout=5,
        )
        try:
            import json
            comagic = json.loads(token_out.strip())
            if comagic.get('token'):
                env_vars += f"COMAGIC_TOKEN='{comagic['token']}' "
                machine.comagic_token = comagic['token']
            if comagic.get('xUserId'):
                env_vars += f"COMAGIC_USER_ID='{comagic['xUserId']}' "
                machine.comagic_user_id = comagic['xUserId']
            if comagic.get('token'):
                logger.info(f"CoMagic token loaded for {machine.host}")
        except Exception:
            pass
        cmd = f"cd {machine.workspace} && {env_vars}{binary} --port {port}"
        await ssh.run_background(cmd, log_file=log_file)
        logger.info(f"Started agent-server on {machine.host}:{port}")

    async def _start_code_server(self, ssh: SSHClient, machine: MachineInfo) -> None:
        """Start code-server on the remote machine if installed."""
        # Find code-server binary — single SSH command checks all paths
        out, _, _ = await ssh.run(
            "for p in ~/.hiclaw/code-server/bin/code-server ~/.local/bin/code-server; do "
            "[ -f \"$p\" ] && echo \"$p\" && exit 0; done; "
            "command -v code-server 2>/dev/null || echo ''",
            timeout=5,
        )
        cs_bin = out.strip()
        if not cs_bin:
            logger.info(f"code-server not installed on {machine.host}, skipping")
            machine.code_server_port = 0
            return

        logger.info(f"Found code-server at: {cs_bin}")

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
        stdout, _, ec = await ssh.run(f"no_proxy=localhost,127.0.0.1 curl -s --max-time 2 -o /dev/null -w '%{{http_code}}' http://localhost:{cs_port}", timeout=5)
        if stdout.strip() == "200":
            logger.info(f"code-server already running on {machine.host}:{cs_port}")
            machine.code_server_port = cs_port
            return

        # Start code-server with full path, no auth, bound to workspace
        log_file = f"/tmp/code-server-{machine.id}.log"
        cmd = (
            f"no_proxy=localhost,127.0.0.1 NO_PROXY=localhost,127.0.0.1 "
            f"{cs_bin} --port {cs_port} --host 0.0.0.0 "
            f"--auth none --disable-telemetry "
            f"{machine.workspace}"
        )
        await ssh.run_background(cmd, log_file=log_file)
        machine.code_server_port = cs_port

        # Wait for it to start (5 attempts × 2s = 10s max)
        for _ in range(5):
            await asyncio.sleep(2)
            stdout, _, ec = await ssh.run(
                f"no_proxy=localhost,127.0.0.1 curl -s --max-time 2 -o /dev/null -w '%{{http_code}}' http://localhost:{cs_port}",
                timeout=5,
            )
            if stdout.strip() == "200":
                logger.info(f"code-server started on {machine.host}:{cs_port}")
                return
        logger.warning(f"code-server may not have started on {machine.host}:{cs_port}")

    async def _wait_healthy(self, ssh: SSHClient, machine: MachineInfo, timeout: int = 180) -> None:
        """Wait for agent-server to become healthy."""
        port = machine.agent_server_port
        log_file = f"/tmp/agent-server-{machine.id}.log"
        start = asyncio.get_event_loop().time()
        attempt = 0
        # Wait a few seconds before first check — agent-server needs time to import modules
        await asyncio.sleep(5)
        while asyncio.get_event_loop().time() - start < timeout:
            attempt += 1
            elapsed = int(asyncio.get_event_loop().time() - start)

            # Check if process is still alive — fail fast if it crashed
            proc_out, _, _ = await ssh.run(
                f"pgrep -f 'agent-server --port {port}' >/dev/null 2>&1 && echo ALIVE || echo DEAD",
                timeout=5,
            )
            if proc_out.strip() == "DEAD":
                # Process crashed — read log tail for error details
                log_out, _, _ = await ssh.run(f"tail -30 {log_file} 2>/dev/null", timeout=5)
                error_detail = log_out.strip()[-1000:] if log_out.strip() else "No log output"
                self._broadcast_event(machine.id, ProvisionEvent(
                    step=ProvisionStep.HEALTH_CHECK, status="started",
                    detail=f"agent-server crashed! Log: {error_detail[:500]}",
                ))
                raise RuntimeError(
                    f"agent-server process died. Last log:\n{error_detail}"
                )

            try:
                stdout, stderr, ec = await ssh.run(
                    f"no_proxy=localhost,127.0.0.1 curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{port}/health",
                    timeout=5,
                )
                code = stdout.strip()
                if code == "200":
                    return
                # Broadcast progress so frontend knows it's still trying
                if attempt % 3 == 0:
                    self._broadcast_event(machine.id, ProvisionEvent(
                        step=ProvisionStep.HEALTH_CHECK, status="started",
                        detail=f"Waiting... ({elapsed}s, HTTP {code})",
                    ))
                    logger.info(f"Health check attempt {attempt}: HTTP {code} ({elapsed}s)")
            except Exception as e:
                if attempt % 3 == 0:
                    self._broadcast_event(machine.id, ProvisionEvent(
                        step=ProvisionStep.HEALTH_CHECK, status="started",
                        detail=f"Waiting... ({elapsed}s, {type(e).__name__})",
                    ))
                    logger.info(f"Health check attempt {attempt}: {e} ({elapsed}s)")
            await asyncio.sleep(3)
        # Timed out — grab log for debugging
        log_out, _, _ = await ssh.run(f"tail -30 {log_file} 2>/dev/null", timeout=5)
        raise TimeoutError(
            f"Agent-server health check timed out after {timeout}s. "
            f"Last log:\n{log_out.strip()[-1000:]}"
        )

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
