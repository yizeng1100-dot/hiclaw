"""Command dispatch pipeline.

Given a CommandSchedule + fire_id, runs the command (via an injectable
runner) and records the outcome on the fire row.

All "skip" policies (prev running, windows, holiday) short-circuit
before the runner is called.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Awaitable, Callable, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from custom.command_scheduler.holidays import HolidayService
from custom.command_scheduler.log_io import tail_bytes_and_lines, write_full_log
from custom.command_scheduler.models import CommandScheduleInfo, HolidayPolicy
from custom.command_scheduler.service import CommandScheduleService

_logger = logging.getLogger(__name__)


class RunResult(NamedTuple):
    exit_code: int
    stdout: str
    stderr: str


# A runner takes (command, working_dir, timeout_sec) and returns a RunResult.
CommandRunner = Callable[[str, str | None, int], Awaitable[RunResult]]


async def execute(
    schedule: CommandScheduleInfo,
    db: AsyncSession,
    runner: CommandRunner,
    trigger_source: str = 'scheduled',
) -> str:
    """Dispatch one fire for ``schedule``. Returns the fire_id."""
    svc = CommandScheduleService(db)
    fire = await svc.create_fire(schedule.id, trigger_source=trigger_source)

    # ── Pre-flight skips ──
    if await svc.has_running_fire_excluding(schedule.id, fire.id):
        await _mark_skipped(svc, fire.id, 'prev_running')
        return fire.id

    if schedule.shell_kind == 'windows':
        # Windows commands are executed by a separate pull-model runner
        # (see tools/windows_runner/). We leave the fire in
        # ``pending_runner`` state; the runner will flip it to
        # ``running`` when it picks up the work and finally to
        # ``success`` / ``failed`` / ``timeout`` via the runner API.
        await svc.update_fire(fire.id, status='pending_runner')
        return fire.id

    hsvc = HolidayService(db)
    today = date.today().isoformat()
    if not await _should_run_today(schedule.holiday_policy, today, hsvc):
        await _mark_skipped(svc, fire.id, 'holiday_skip')
        return fire.id

    # ── Run ──
    started = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        result = await runner(
            schedule.command,
            schedule.working_dir,
            schedule.max_duration_sec,
        )
    except TimeoutError:
        await svc.update_fire(
            fire.id,
            status='timeout',
            stderr_tail=f'exceeded max_duration_sec={schedule.max_duration_sec}',
            completed=True,
        )
        return fire.id
    except Exception as e:
        _logger.exception(
            'command_scheduler executor crashed for %s', schedule.id
        )
        await svc.update_fire(
            fire.id,
            status='failed',
            stderr_tail=f'{type(e).__name__}: {e}',
            completed=True,
        )
        return fire.id

    completed = datetime.now(timezone.utc).replace(tzinfo=None)
    log_path_str: str | None = None
    try:
        log_path = write_full_log(
            schedule.id,
            fire.id,
            result.stdout,
            result.stderr,
            started,
            completed,
            result.exit_code,
        )
        log_path_str = str(log_path)
    except Exception as e:
        _logger.warning('write_full_log failed: %s', e)

    await svc.update_fire(
        fire.id,
        status='success' if result.exit_code == 0 else 'failed',
        exit_code=result.exit_code,
        stdout_tail=tail_bytes_and_lines(result.stdout),
        stderr_tail=tail_bytes_and_lines(result.stderr),
        log_file_path=log_path_str,
        completed=True,
    )
    return fire.id


async def _mark_skipped(
    svc: CommandScheduleService, fire_id: str, reason: str
) -> None:
    await svc.update_fire(
        fire_id,
        status='skipped',
        skip_reason=reason,
        completed=True,
    )


async def _should_run_today(
    policy: HolidayPolicy, today: str, hsvc: HolidayService
) -> bool:
    if policy == 'normal':
        return True
    check = await hsvc.check_date(today)
    if policy == 'skip':
        return not check.is_holiday
    # P1 simple semantics: run_before / run_after only skip on the holiday
    # day. The "advance one workday" compensation is a P2 scanner job.
    return not check.is_holiday
