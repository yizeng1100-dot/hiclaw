"""Pluggable command runners.

P1a: subprocess runner — for local testing + as fallback
P1b: sandbox runner — added in Task 7
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
