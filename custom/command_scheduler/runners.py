"""Pluggable command runners.

- ``subprocess_runner``: spawns a child process of HiClaw's backend.
  The P1 default — see ``sandbox_manager`` for the reasoning.
- ``sandbox_runner``: thin adapter that delegates to a future dedicated
  shell-exec sandbox. Raises ``NotImplementedError`` in P1 because the
  sandbox is stubbed (see ``sandbox_manager``).
"""

from __future__ import annotations

import asyncio

from custom.command_scheduler.executor import RunResult


async def subprocess_runner(
    command: str, working_dir: str | None, timeout_sec: int
) -> RunResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError as e:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        raise TimeoutError(f'command timed out after {timeout_sec}s') from e
    return RunResult(
        exit_code=proc.returncode or 0,
        stdout=stdout_b.decode('utf-8', errors='replace'),
        stderr=stderr_b.decode('utf-8', errors='replace'),
    )


async def sandbox_runner(
    command: str, working_dir: str | None, timeout_sec: int
) -> RunResult:
    """P2+ placeholder — delegates to the sandbox_manager stub."""
    from custom.command_scheduler.sandbox_manager import exec_in_sandbox

    exit_code, stdout, stderr = await exec_in_sandbox(
        command, working_dir, timeout_sec
    )
    return RunResult(exit_code=exit_code, stdout=stdout, stderr=stderr)
