"""Data models for Agent Worker Manager — machine-centric design."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class WorkerMode(str, Enum):
    DOCKER = "docker"
    HOST = "host"


class MachineStatus(str, Enum):
    CONNECTING = "connecting"
    PROVISIONING = "provisioning"
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ProvisionStep(str, Enum):
    SSH_CONNECT = "ssh_connect"
    CHECK_PYTHON = "check_python"
    INSTALL_PYTHON = "install_python"
    CHECK_AGENT_SDK = "check_agent_sdk"
    INSTALL_AGENT_SDK = "install_agent_sdk"
    CHECK_CODE_SERVER = "check_code_server"
    INSTALL_CODE_SERVER = "install_code_server"
    SCP_DEPENDENCIES = "scp_dependencies"
    CLONE_SKILLS = "clone_skills"
    START_AGENT_SERVER = "start_agent_server"
    HEALTH_CHECK = "health_check"
    SETUP_TUNNEL = "setup_tunnel"


class ProvisionEvent(BaseModel):
    """SSE event sent during provisioning."""
    step: ProvisionStep
    status: str  # "started" | "completed" | "skipped" | "failed"
    detail: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def compute_machine_id(host: str, port: int, username: str) -> str:
    """Deterministic machine ID from connection params."""
    return hashlib.sha256(f"{host}:{port}:{username}".encode()).hexdigest()[:12]


class ConnectMachineRequest(BaseModel):
    """Request to connect to a remote machine."""
    host: str
    port: int = 22
    username: str
    password: str | None = None
    private_key: str | None = None
    mode: WorkerMode = WorkerMode.HOST
    template: str = "openhands"
    workspace: str = "/root/workspace"  # User must specify via frontend
    agent_server_port: int = 8000


class MachineInfo(BaseModel):
    """Machine state — one machine can serve multiple conversations."""
    id: str
    host: str
    port: int = 22
    username: str
    mode: WorkerMode
    template: str
    workspace: str
    status: MachineStatus = MachineStatus.CONNECTING
    agent_server_port: int = 8000
    code_server_port: int = 8443  # code-server port on remote
    tunnel_port: int = 0  # Local port of SSH tunnel (agent-server)
    code_server_tunnel_port: int = 0  # Local port of SSH tunnel (code-server)
    proxy_url: str = ""  # How to reach the agent-server
    vscode_url: str = ""  # How to reach VS Code
    active_conversations: int = 0
    provision_steps: list[ProvisionEvent] = Field(default_factory=list)
    error: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
