"""Machine Manager — manages remote machines, not individual sessions."""

from __future__ import annotations

import asyncio
import json
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

# >>> CUSTOM: HiClaw — persist machine state to disk <<<
HICLAW_DIR = os.environ.get('HICLAW_DIR', os.path.join(os.path.expanduser('~'), '.hiclaw'))
STATE_FILE = os.path.join(HICLAW_DIR, 'machines-state.json')


def _save_machines_state(machines: dict[str, MachineInfo]) -> None:
    """Save machine info to disk so it survives restarts."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        data = {mid: m.model_dump() for mid, m in machines.items()}
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f, default=str)
    except Exception as e:
        logger.warning(f'Failed to save machine state: {e}')


def _load_machines_state() -> dict[str, MachineInfo]:
    """Load previously saved machine state from disk."""
    try:
        if not os.path.exists(STATE_FILE):
            return {}
        with open(STATE_FILE) as f:
            data = json.load(f)
        machines = {}
        for mid, mdata in data.items():
            try:
                # Reset transient state — tunnels/connections need to be re-established
                mdata['tunnel_port'] = 0
                mdata['code_server_tunnel_port'] = 0
                mdata['proxy_url'] = ''
                mdata['vscode_url'] = ''
                mdata['status'] = MachineStatus.PAUSED.value
                mdata['provision_steps'] = []
                machines[mid] = MachineInfo(**mdata)
            except Exception as e:
                logger.warning(f'Failed to restore machine {mid}: {e}')
        if machines:
            logger.info(f'Restored {len(machines)} machines from {STATE_FILE}')
        return machines
    except Exception as e:
        logger.warning(f'Failed to load machine state: {e}')
        return {}
# >>> END CUSTOM <<<


def _pick_port() -> int:
    return random.randint(20000, 50000)


class MachineManager:
    """Manages remote machines. One machine = one agent-server, many conversations."""

    def __init__(self):
        # >>> CUSTOM: HiClaw — restore machines from disk <<<
        self._machines: dict[str, MachineInfo] = _load_machines_state()
        # >>> END CUSTOM <<<
        self._ssh_clients: dict[str, SSHClient] = {}
        self._local_ports: dict[str, int] = {}
        self._listeners: dict[str, object] = {}
        self._event_queues: dict[str, list[asyncio.Queue]] = {}
        self._provision_locks: dict[str, asyncio.Lock] = {}

    # >>> CUSTOM: HiClaw — reconnect to previously saved machines <<<
    async def reconnect_saved_machines(self, passwords: dict[str, str] | None = None) -> int:
        """Reconnect to machines that were saved before restart.

        For each machine in PAUSED state (restored from disk), attempt to:
        1. SSH connect
        2. Check if agent-server is still running
        3. Re-establish SSH tunnel
        4. Mark as READY

        Args:
            passwords: mapping of machine_id → SSH password (needed because
                       passwords are NOT persisted to disk for security)

        Returns:
            Number of machines successfully reconnected.
        """
        paused = {mid: m for mid, m in self._machines.items()
                  if m.status == MachineStatus.PAUSED}
        if not paused:
            return 0

        logger.info(f'Attempting to reconnect {len(paused)} saved machines...')
        reconnected = 0

        for machine_id, machine in paused.items():
            try:
                # Need password — check env or passed dict
                password = None
                if passwords:
                    password = passwords.get(machine_id)
                if not password:
                    password = os.environ.get(f'HICLAW_SSH_PASS_{machine_id}')
                if not password:
                    password = os.environ.get('HICLAW_SSH_PASSWORD')
                if not password:
                    logger.warning(f'No password for machine {machine_id} ({machine.host}), skipping reconnect')
                    continue

                # SSH connect
                ssh = SSHClient(machine.host, machine.port, machine.username, password)
                await ssh.connect()

                # Check if agent-server is still running
                if machine.mode == WorkerMode.DOCKER:
                    check_cmd = f"docker ps --filter 'name=agent-server-{machine_id}' --format '{{{{.Status}}}}'"
                else:
                    check_cmd = f"pgrep -f 'agent.server.*--port {machine.agent_server_port}' > /dev/null && echo running || echo stopped"
                stdout, _, ec = await ssh.run(check_cmd, timeout=10)
                is_running = 'running' in stdout.lower() or ('Up' in stdout)

                if not is_running:
                    logger.info(f'Machine {machine_id} ({machine.host}): agent-server not running, skipping')
                    await ssh.close()
                    continue

                # Re-establish SSH tunnel
                local_port = _pick_port()
                tunnel = await ssh.forward_local_port(local_port, machine.agent_server_port)
                self._ssh_clients[machine_id] = ssh
                self._local_ports[machine_id] = local_port
                self._listeners[machine_id] = tunnel

                # Verify health
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(f'http://localhost:{local_port}/health', timeout=5)
                        if resp.status_code != 200:
                            raise Exception(f'Health check failed: {resp.status_code}')
                except Exception as e:
                    logger.warning(f'Machine {machine_id} health check failed: {e}')
                    await ssh.close()
                    continue

                # Success — update state
                machine.status = MachineStatus.READY
                machine.tunnel_port = local_port
                machine.proxy_url = f'http://localhost:{local_port}'

                # Also try to re-establish code-server tunnel
                try:
                    cs_local_port = _pick_port()
                    cs_tunnel = await ssh.forward_local_port(cs_local_port, machine.code_server_port)
                    machine.code_server_tunnel_port = cs_local_port
                    machine.vscode_url = f'http://localhost:{cs_local_port}'
                except Exception:
                    pass  # code-server tunnel is optional

                self._event_queues[machine_id] = []
                self._provision_locks[machine_id] = asyncio.Lock()
                reconnected += 1
                logger.info(f'Machine {machine_id} ({machine.host}) reconnected: tunnel localhost:{local_port} → {machine.agent_server_port}')

            except Exception as e:
                logger.warning(f'Failed to reconnect machine {machine_id} ({machine.host}): {e}')

        if reconnected > 0:
            _save_machines_state(self._machines)
            logger.info(f'Reconnected {reconnected}/{len(paused)} machines')
        return reconnected
    # >>> END CUSTOM <<<

    async def connect_machine(self, req: ConnectMachineRequest) -> MachineInfo:
        """Idempotent connect. Returns existing machine if already ready."""
        machine_id = compute_machine_id(req.host, req.port, req.username)

        if machine_id in self._machines:
            machine = self._machines[machine_id]
            if machine.status == MachineStatus.READY:
                # >>> CUSTOM: HiClaw — verify agent-server is still alive before reusing <<<
                still_healthy = False
                try:
                    if machine.tunnel_port:
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(
                                f"http://localhost:{machine.tunnel_port}/health",
                                timeout=5,
                            )
                            still_healthy = resp.status_code == 200
                except Exception as e:
                    logger.warning(f"Machine {machine_id} health check failed: {e}")

                if not still_healthy:
                    logger.warning(f"Machine {machine_id} was READY but agent-server is dead, re-provisioning...")
                    machine.status = MachineStatus.ERROR
                    machine.error = "Agent server not responding, reconnecting..."
                    await self._cleanup_machine(machine_id)
                    # Fall through to create new machine
                else:
                    # >>> END CUSTOM <<<
                    machine.active_conversations += 1
                    ssh = self._ssh_clients.get(machine_id)
                    # >>> CUSTOM: HiClaw — full reconnect health checks <<<
                    if ssh and ssh.connected:
                        async def _run_checks():
                            try:
                                await self._reconnect_health_checks(ssh, machine, req)
                            except Exception as exc:
                                logger.error(f"Reconnect health checks crashed: {exc}", exc_info=True)
                        asyncio.create_task(_run_checks())
                    else:
                        logger.warning(f"Machine {machine_id} reuse: SSH not connected, skipping health checks")
                    # >>> END CUSTOM <<<
                    return machine
            if machine.status in (MachineStatus.CONNECTING, MachineStatus.PROVISIONING, MachineStatus.STARTING):
                # Already in progress — caller should subscribe to SSE
                return machine
            if machine.status == MachineStatus.ERROR:
                await self._cleanup_machine(machine_id)
            # >>> CUSTOM: HiClaw — handle PAUSED machines (restored from disk) <<<
            if machine.status == MachineStatus.PAUSED:
                logger.info(f"Machine {machine_id} is PAUSED (restored from disk), re-provisioning...")
                await self._cleanup_machine(machine_id)
                # Fall through to create new machine entry and re-provision
            # >>> END CUSTOM <<<

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
        _save_machines_state(self._machines)  # >>> CUSTOM: HiClaw <<<

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
                            f"ps aux | grep 'agent.server.*--port {port}' | grep -v grep | head -1",
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
                _save_machines_state(self._machines)  # >>> CUSTOM: HiClaw <<<
                logger.info(f"Machine {machine_id} ready: {req.host}:{machine.agent_server_port} → localhost:{local_port}")

            except Exception as e:
                machine.status = MachineStatus.ERROR
                machine.error = str(e) or repr(e)
                _save_machines_state(self._machines)  # >>> CUSTOM: HiClaw <<<
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
            # >>> CUSTOM: HiClaw — reuse agent-server regardless of workspace <<<
            # One agent-server serves ALL workspaces. Each conversation specifies
            # its own working_dir via StartConversationRequest.
            # Check if running agent-server has correct FILE_STORE_PATH=$HOME/.hiclaw
            # If not (old version, or not set), kill and restart with correct config
            check_stdout, _, _ = await ssh.run(
                f"ps aux | grep 'agent.server.*--port {port}' | grep -v grep | head -1", timeout=5)
            home_out, _, _ = await ssh.run("echo $HOME", timeout=3)
            remote_home = home_out.strip() or "/root"
            correct_store = f"FILE_STORE_PATH={remote_home}/.hiclaw"
            if check_stdout and correct_store not in check_stdout:
                logger.info(f"Agent-server missing '{correct_store}' in cmd, restarting")
                await ssh.run(f"pkill -f 'agent.server.*--port {port}' 2>/dev/null || true", timeout=5)
                await ssh.run(f"fuser -k {port}/tcp 2>/dev/null || true", timeout=5)
                await asyncio.sleep(2)
            else:
                logger.info(f"Agent-server healthy with correct config on port {port}, reusing")
                await ssh.run(f"mkdir -p {machine.workspace}", timeout=5)
                return
            # >>> END CUSTOM <<<
        else:
            # Port not healthy — kill any leftover agent-server process on this port
            await ssh.run(f"pkill -f 'agent.server.*--port {port}' 2>/dev/null || true", timeout=5)
            # Also kill anything else holding the port
            await ssh.run(f"fuser -k {port}/tcp 2>/dev/null || true", timeout=5)
            await asyncio.sleep(1)

        # Step 2: Ensure workspace and log dirs exist
        await ssh.run(f"mkdir -p {machine.workspace} $HOME/.hiclaw/logs $HOME/.hiclaw/tmp")

        # Step 3: Start in background
        log_file = f"$HOME/.hiclaw/logs/agent-server-{machine.id}.log"
        # no_proxy: corporate proxies intercept localhost + app-server IP connections
        app_ip = os.environ.get('HICLAW_APP_IP', '')
        if not app_ip:
            # Try to detect app-server IP from SSH connection (remote sees us as this IP)
            try:
                ip_out, _, _ = await ssh.run("echo $SSH_CLIENT | awk '{print $1}'", timeout=3)
                app_ip = ip_out.strip()
            except Exception:
                pass
        no_proxy_list = f"localhost,127.0.0.1{f',{app_ip}' if app_ip else ''}"
        env_vars = f"no_proxy={no_proxy_list} NO_PROXY={no_proxy_list} "
        # >>> CUSTOM: HiClaw — use user home for FILE_STORE_PATH (not workspace-specific) <<<
        # This allows one agent-server to serve multiple workspaces
        env_vars += f"FILE_STORE_PATH=$HOME/.hiclaw "
        # >>> CUSTOM: HiClaw — pass secret key for encrypting API keys in persisted conversations <<<
        _secret_key = os.environ.get('OH_SECRET_KEY', '')
        if _secret_key:
            env_vars += f"OH_SECRET_KEY='{_secret_key}' "
        # >>> CUSTOM: HiClaw — public skills env var (still useful for SDK monkey-patch) <<<
        public_skills_repo = os.environ.get('OH_PUBLIC_SKILLS_REPO', '')
        if not public_skills_repo:
            _gitea_port = os.environ.get('HICLAW_GITEA_PORT', '3300')
            _gitea_user = os.environ.get('HICLAW_GITEA_USER', 'hiclaw-admin')
            _gitea_pass = os.environ.get('HICLAW_GITEA_PASSWORD', 'HiClaw2026!')
            _gitea_host = app_ip or 'localhost'
            public_skills_repo = f'http://{_gitea_user}:{_gitea_pass}@{_gitea_host}:{_gitea_port}/{_gitea_user}/extensions.git'
        if public_skills_repo:
            env_vars += f"OH_PUBLIC_SKILLS_REPO='{public_skills_repo}' "
        # >>> END CUSTOM <<<
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
        # >>> CUSTOM: HiClaw — cd to $HOME, not workspace (one agent-server for all workspaces) <<<
        cmd = f"cd $HOME && {env_vars}{binary} --port {port}"
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

        # >>> CUSTOM: HiClaw — start code-server at $HOME so all workspaces are accessible <<<
        log_file = f"$HOME/.hiclaw/logs/code-server-{machine.id}.log"
        cmd = (
            f"no_proxy=localhost,127.0.0.1 NO_PROXY=localhost,127.0.0.1 "
            f"{cs_bin} --port {cs_port} --host 0.0.0.0 "
            f"--auth none --disable-telemetry --disable-workspace-trust "
            f"$HOME"
        )
        # >>> END CUSTOM <<<
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
        log_file = f"$HOME/.hiclaw/logs/agent-server-{machine.id}.log"
        start = asyncio.get_event_loop().time()
        attempt = 0
        # Wait a few seconds before first check — agent-server needs time to import modules
        await asyncio.sleep(5)
        while asyncio.get_event_loop().time() - start < timeout:
            attempt += 1
            elapsed = int(asyncio.get_event_loop().time() - start)

            # Check if process is still alive — fail fast if it crashed
            proc_out, _, _ = await ssh.run(
                f"pgrep -f 'agent.server --port {port}' >/dev/null 2>&1 && echo ALIVE || echo DEAD",
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

    async def _reconnect_health_checks(self, ssh: SSHClient, machine: MachineInfo, req: ConnectMachineRequest) -> None:
        """Run all health checks when reusing an existing READY machine.

        Checks (in background, non-blocking):
        1. Workspace directory exists
        2. Code-server is healthy, restart if not
        3. Public skills cache exists, clone from Gitea if not
        4. Custom skills repo is synced
        """
        try:
            logger.info(f"[RECONNECT] Starting health checks for {machine.host}")

            # 1. Workspace change
            if req.workspace != machine.workspace:
                old_workspace = machine.workspace
                machine.workspace = req.workspace
                logger.info(f"Machine {machine.id} workspace changed: {old_workspace} → {req.workspace}")
                await ssh.run(f"mkdir -p {req.workspace}", timeout=5)
            else:
                # Ensure workspace dir exists even if unchanged
                await ssh.run(f"mkdir -p {machine.workspace}", timeout=5)

            # 2. Code-server health
            if machine.code_server_port:
                try:
                    cs_out, _, _ = await ssh.run(
                        f"no_proxy=localhost,127.0.0.1 curl -s -o /dev/null -w '%{{http_code}}' "
                        f"--max-time 3 http://localhost:{machine.code_server_port}/healthz",
                        timeout=5,
                    )
                    if cs_out.strip() != "200":
                        logger.warning(f"Code-server not healthy on reconnect, restarting")
                        await self._start_code_server(ssh, machine)
                except Exception as e:
                    logger.warning(f"Code-server health check failed on reconnect: {e}")

            # 3. Public skills cache — upload bundle via SSH if missing
            # Resolve $HOME first — SFTP doesn't expand shell variables
            _home_out, _, _ = await ssh.run("echo $HOME", timeout=3)
            _remote_home = _home_out.strip() or "/root"
            _skills_cache = f"{_remote_home}/.openhands/cache/skills"
            _remote_tmp = f"{_remote_home}/.hiclaw/tmp"

            _has_cache, _, _ = await ssh.run(
                f"test -d {_skills_cache}/public-skills/.git && echo YES || echo NO",
                timeout=5,
            )
            logger.info(f"[RECONNECT] Public skills cache check: {_has_cache.strip()}, path={_skills_cache}")
            if "YES" not in _has_cache:
                extensions_bundle = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "deps", "openhands-extensions.bundle"
                )
                logger.info(f"[RECONNECT] Bundle path: {extensions_bundle}, exists={os.path.exists(extensions_bundle)}")
                if os.path.exists(extensions_bundle):
                    await ssh.run(f"mkdir -p {_remote_tmp} {_skills_cache}", timeout=5)
                    await ssh.upload_file(
                        extensions_bundle,
                        f"{_remote_tmp}/openhands-extensions.bundle",
                    )
                    await ssh.run(
                        f"git clone {_remote_tmp}/openhands-extensions.bundle {_skills_cache}/public-skills && "
                        f"rm -f {_remote_tmp}/openhands-extensions.bundle",
                        timeout=30,
                    )
                    # Verify it worked
                    _verify, _, _ = await ssh.run(
                        f"test -d {_skills_cache}/public-skills/skills && echo OK || echo FAIL",
                        timeout=5,
                    )
                    logger.info(f"[RECONNECT] Public skills upload result: {_verify.strip()}")
                else:
                    logger.info(f"No extensions bundle found at {extensions_bundle}, skipping")

            # 4. Custom skills sync
            await self._clone_skills_repo(ssh, machine)

        except Exception as e:
            logger.warning(f"Reconnect health checks failed (non-fatal): {e}")

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
                    await ssh.run(f"pkill -f 'agent.server --port {machine.agent_server_port}' || true", timeout=10)
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
        _save_machines_state(self._machines)  # >>> CUSTOM: HiClaw <<<
        logger.info(f"Machine {machine_id} cleaned up")
