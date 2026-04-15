"""Stub: lazy lifecycle wrapper for a dedicated command_scheduler sandbox.

**P1 status: NOT IMPLEMENTED — using subprocess fallback instead.**

Why this is a stub:

The P1 design (see DESIGN.md ADR-02) planned to use HiClaw's existing
``ProcessSandboxService`` as a shared "scheduler sandbox" that all
command schedules would exec into. That plan was based on a wrong
assumption: HiClaw's Process sandbox actually spawns an **agent-server
HTTP process** (see ``openhands/app_server/sandbox/process_sandbox_service.py``
``_start_agent_process``), not a general-purpose shell executor. It
has ``start_sandbox`` / ``get_sandbox`` / ``delete_sandbox``, but no
``exec_command`` primitive; agent tools that want to run shell commands
go through the agent-server's bash tool via HTTP, which is not a
natural fit for scheduled task dispatch.

P1 therefore falls back to ``runners.subprocess_runner``, which runs
each scheduled command as a child process of the HiClaw backend. This
matches the user's explicit instruction:

    "用 HiClaw sandbox 先试一下，不行再进程级" (2026-04-15 chat)

... with the sandbox path resolved to "not a fit → use subprocess".

When a real shell-exec sandbox is needed (P2+), fill in this module:

- ``SANDBOX_ID``, ``WORKSPACE_ROOT``, ``VENV_ROOT``, ``PROVISION_CMD``
  constants describe the desired layout.
- ``get_or_start_sandbox()`` should return a handle for the
  long-lived shell-exec sandbox.
- ``exec_in_sandbox(cmd, cwd, timeout)`` should run ``cmd`` inside it
  and return ``(exit_code, stdout, stderr)``.
- ``runners.sandbox_runner`` already delegates here, so swapping P1
  subprocess → P2 sandbox is just a matter of changing which runner
  ``fire.fire_command_schedule`` imports.

Until then, calling anything in this module raises ``NotImplementedError``
so any accidental wiring fails loudly.
"""

from __future__ import annotations

from pathlib import Path

SANDBOX_ID = 'cmd-scheduler'
WORKSPACE_ROOT = Path('/opt/hiclaw/command_scheduler/workspace')
VENV_ROOT = Path('/opt/hiclaw/command_scheduler/venv')
PROVISIONED_MARKER = VENV_ROOT / '.provisioned'

PROVISION_CMD = (
    f'python -m venv {VENV_ROOT} && '
    f'{VENV_ROOT}/bin/pip install --no-cache-dir '
    f'requests httpx python-dateutil pyyaml openpyxl pandas && '
    f'mkdir -p {WORKSPACE_ROOT} && '
    f'touch {PROVISIONED_MARKER}'
)


async def get_or_start_sandbox():  # pragma: no cover - P2+ only
    raise NotImplementedError(
        'command_scheduler sandbox is a P2+ feature; '
        'P1 uses runners.subprocess_runner instead. '
        'See the module docstring for details.'
    )


async def exec_in_sandbox(
    command: str, working_dir: str | None, timeout_sec: int
) -> tuple[int, str, str]:  # pragma: no cover - P2+ only
    raise NotImplementedError(
        'command_scheduler sandbox is a P2+ feature; '
        'P1 uses runners.subprocess_runner instead.'
    )
