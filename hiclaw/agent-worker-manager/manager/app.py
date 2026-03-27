"""Agent Worker Manager — FastAPI application (machine-centric)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .models import ConnectMachineRequest, MachineInfo
from .machine_manager import MachineManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

manager = MachineManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Agent Worker Manager starting")
    yield
    for mid in list(manager._machines.keys()):
        await manager.disconnect_machine(mid)
    logger.info("Agent Worker Manager stopped")


app = FastAPI(
    title="Agent Worker Manager",
    description="Manages agent-server on remote machines via SSH (machine-centric)",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Machine endpoints ──────────────────────────────────

@app.post("/api/machines/connect", response_model=MachineInfo)
async def connect_machine(req: ConnectMachineRequest):
    """Connect to a remote machine (idempotent). Returns immediately."""
    logger.info(f"Connect request: {req.host}:{req.port} user={req.username}")
    machine = await manager.connect_machine(req)
    return machine


@app.get("/api/machines", response_model=list[MachineInfo])
async def list_machines():
    return manager.list_machines()


@app.get("/api/machines/{machine_id}", response_model=MachineInfo)
async def get_machine(machine_id: str):
    machine = manager.get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


@app.delete("/api/machines/{machine_id}")
async def disconnect_machine(machine_id: str):
    ok = await manager.disconnect_machine(machine_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Machine not found")
    return {"status": "disconnected"}


# ─── SSE — provisioning progress stream ──────────────────

@app.get("/api/machines/{machine_id}/events")
async def machine_events(machine_id: str):
    """SSE endpoint for provisioning progress."""
    machine = manager.get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")

    # If already done, send final state immediately — no need for SSE stream
    if machine.status in ("ready", "error"):
        async def done_generator():
            # Send unique steps only (deduplicate by step+status)
            seen = set()
            for evt in machine.provision_steps:
                key = f"{evt.step}:{evt.status}"
                if key not in seen:
                    seen.add(key)
                    yield {"data": evt.model_dump_json()}
            yield {"data": machine.model_dump_json()}
        return EventSourceResponse(done_generator())

    # Still provisioning — stream live events
    q = manager.subscribe_events(machine_id)

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=60)
                    yield {"data": event.model_dump_json()}
                    m = manager.get_machine(machine_id)
                    if m and m.status in ("ready", "error"):
                        yield {"data": m.model_dump_json()}
                        break
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            manager.unsubscribe_events(machine_id, q)

    return EventSourceResponse(event_generator())


# ─── Proxy — forward requests to remote agent-server via tunnel ──────

@app.api_route(
    "/api/machines/{machine_id}/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_to_machine(machine_id: str, path: str, request: Request):
    """Proxy HTTP to the remote agent-server via SSH tunnel."""
    machine = manager.get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    if machine.status != "ready":
        raise HTTPException(status_code=503, detail=f"Machine not ready: {machine.status}")

    port = manager.get_tunnel_port(machine_id)
    if not port:
        raise HTTPException(status_code=502, detail="No tunnel available")

    target_url = f"http://localhost:{port}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)

    import httpx
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="Tunnel not available")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Remote agent-server timeout")


# ─── Legacy compat — old /api/workers endpoints redirect to machines ──────

@app.post("/api/workers")
async def create_worker_compat(req: ConnectMachineRequest):
    """Legacy compatibility: maps to connect_machine."""
    machine = await manager.connect_machine(req)
    # Wait for ready (for legacy clients that expect blocking behavior)
    for _ in range(60):
        m = manager.get_machine(machine.id)
        if m and m.status == "ready":
            return m
        if m and m.status == "error":
            raise HTTPException(status_code=500, detail=m.error)
        await asyncio.sleep(2)
    raise HTTPException(status_code=504, detail="Machine provisioning timeout")


# ─── Skills Git operations ──────────────────────────────────

@app.get("/api/machines/{machine_id}/skills/diff")
async def skills_diff(machine_id: str):
    """Get git diff of modified skills on remote machine."""
    machine = manager.get_machine(machine_id)
    if not machine or machine.status != "ready":
        raise HTTPException(status_code=404, detail="Machine not ready")
    ssh = manager.get_ssh_client(machine_id)
    if not ssh:
        raise HTTPException(status_code=502, detail="SSH not available")

    skills_dir = f"{machine.workspace}/.hiclaw/skills"
    # Get status and diff
    stdout_status, _, _ = await ssh.run(f"cd {skills_dir} && git status --porcelain", timeout=10)
    stdout_diff, _, _ = await ssh.run(f"cd {skills_dir} && git diff", timeout=10)
    # Also get diff for new files
    stdout_untracked, _, _ = await ssh.run(
        f"cd {skills_dir} && git ls-files --others --exclude-standard", timeout=10)

    files = []
    for line in stdout_status.strip().split("\n"):
        if line.strip():
            status_code = line[:2].strip()
            filepath = line[3:].strip()
            files.append({"status": status_code, "path": filepath})

    for line in stdout_untracked.strip().split("\n"):
        if line.strip():
            files.append({"status": "??", "path": line.strip()})

    return {
        "has_changes": len(files) > 0,
        "files": files,
        "diff": stdout_diff,
    }


@app.post("/api/machines/{machine_id}/skills/commit")
async def skills_commit(machine_id: str, request: Request):
    """Commit and push skill changes from remote to server."""
    machine = manager.get_machine(machine_id)
    if not machine or machine.status != "ready":
        raise HTTPException(status_code=404, detail="Machine not ready")
    ssh = manager.get_ssh_client(machine_id)
    if not ssh:
        raise HTTPException(status_code=502, detail="SSH not available")

    body = await request.json()
    message = body.get("message", "Update skills")

    skills_dir = f"{machine.workspace}/.hiclaw/skills"
    GIT_PORT = 19418

    # Start git daemon for push
    import subprocess
    git_daemon = subprocess.Popen(
        ["git", "daemon", "--reuseaddr", f"--port={GIT_PORT}",
         "--export-all", "--enable=receive-pack",
         "--base-path=/opt/hiclaw", "/opt/hiclaw"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        # Reverse tunnel for git push
        listener = await ssh._conn.forward_remote_port("", GIT_PORT, "localhost", GIT_PORT)

        # Stage all changes
        await ssh.run(f"cd {skills_dir} && git add -A", timeout=10)

        # Commit
        stdout, stderr, ec = await ssh.run(
            f"cd {skills_dir} && git commit -m '{message}'",
            timeout=15,
        )

        if ec != 0:
            listener.close()
            return {"status": "no_changes", "detail": "Nothing to commit"}

        # Push
        stdout, stderr, ec = await ssh.run(
            f"cd {skills_dir} && git push origin master",
            timeout=30,
        )

        listener.close()

        if ec != 0:
            raise HTTPException(status_code=500, detail=f"Push failed: {stderr[:200]}")

        return {"status": "committed", "message": message}
    finally:
        git_daemon.terminate()
        git_daemon.wait()


# ─── Health ──────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "machines": len(manager._machines)}
