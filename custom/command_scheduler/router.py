"""FastAPI router for command_scheduler endpoints.

Mounted at ``/api/v1/command-schedules`` (schedules CRUD + fires) and
``/api/v1/command-scheduler/holidays`` (holiday management).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from custom.command_scheduler import scheduler_integration
from custom.command_scheduler.cron_util import (
    InvalidScheduleError,
    build_trigger,
)
from custom.command_scheduler.db import get_cs_db
from custom.command_scheduler.executor import execute
from custom.command_scheduler.holidays import HolidayService
from custom.command_scheduler.log_io import (
    tail_bytes_and_lines,
    write_full_log,
)
from custom.command_scheduler.models import (
    CommandFireInfo,
    CommandScheduleCreate,
    CommandScheduleInfo,
    CommandScheduleUpdate,
    HolidayCheckResult,
    HolidayInfo,
    PendingFireForRunner,
    RunnerCompleteRequest,
    RunnerHeartbeatRequest,
)
from custom.command_scheduler.runners import subprocess_runner
from custom.command_scheduler.service import CommandScheduleService

_logger = logging.getLogger(__name__)

# In-memory runner heartbeat cache. Lost on backend restart — the
# runner sends heartbeats on every poll cycle so the cache refills
# within 10 seconds. Keyed by runner_id so multiple runners (future
# multi-target) register independently.
_last_heartbeat: dict[str, dict[str, Any]] = {}


def _require_runner_key(
    x_hiclaw_runner_key: str | None = Header(None),
) -> None:
    """Check the optional API key for runner endpoints.

    If ``HICLAW_WINDOWS_RUNNER_KEY`` is unset, auth is disabled (dev
    mode). If set, the header must match exactly or the request is
    rejected with 401. The env var is read every call so rotation
    without restart works.
    """
    expected = os.environ.get('HICLAW_WINDOWS_RUNNER_KEY')
    if not expected:
        return  # auth disabled
    if x_hiclaw_runner_key != expected:
        raise HTTPException(status_code=401, detail='Invalid runner key')

router = APIRouter(tags=['command_scheduler'])


async def _db() -> Any:
    db = await get_cs_db()
    try:
        yield db
    finally:
        await db.close()


# ─── Schedules ─────────────────────────────────────────────────────


@router.get(
    '/command-schedules', response_model=list[CommandScheduleInfo]
)
async def list_schedules(
    enabled: bool | None = None,
    env_tag: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(_db),
) -> list[CommandScheduleInfo]:
    return await CommandScheduleService(db).list_schedules(
        enabled=enabled, env_tag=env_tag, q=q
    )


@router.get('/command-schedules/stats')
async def stats(db: AsyncSession = Depends(_db)) -> dict[str, int]:
    return await CommandScheduleService(db).count_status()


@router.get(
    '/command-schedules/{schedule_id}',
    response_model=CommandScheduleInfo,
)
async def get_schedule(
    schedule_id: str, db: AsyncSession = Depends(_db)
) -> CommandScheduleInfo:
    row = await CommandScheduleService(db).get_schedule(schedule_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Schedule not found')
    return row


@router.post('/command-schedules', response_model=CommandScheduleInfo)
async def create_schedule(
    payload: CommandScheduleCreate, db: AsyncSession = Depends(_db)
) -> CommandScheduleInfo:
    svc = CommandScheduleService(db)
    try:
        build_trigger(payload.kind, payload.cron_expr, payload.run_at)
    except InvalidScheduleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    info = await svc.create_schedule(payload)
    scheduler_integration.register_schedule(info)
    await scheduler_integration.sync_next_fire_at()
    out = await svc.get_schedule(info.id)
    assert out is not None
    return out


@router.put(
    '/command-schedules/{schedule_id}',
    response_model=CommandScheduleInfo,
)
@router.patch(
    '/command-schedules/{schedule_id}',
    response_model=CommandScheduleInfo,
)
async def update_schedule(
    schedule_id: str,
    patch: CommandScheduleUpdate,
    db: AsyncSession = Depends(_db),
) -> CommandScheduleInfo:
    svc = CommandScheduleService(db)
    info = await svc.update_schedule(schedule_id, patch)
    if info is None:
        raise HTTPException(status_code=404, detail='Schedule not found')
    scheduler_integration.reschedule(info)
    await scheduler_integration.sync_next_fire_at()
    out = await svc.get_schedule(info.id)
    assert out is not None
    return out


@router.delete('/command-schedules/{schedule_id}')
async def delete_schedule(
    schedule_id: str, db: AsyncSession = Depends(_db)
) -> dict[str, bool]:
    ok = await CommandScheduleService(db).delete_schedule(schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail='Schedule not found')
    scheduler_integration.unregister_schedule(schedule_id)
    return {'deleted': True}


@router.post('/command-schedules/{schedule_id}/run')
async def run_now(
    schedule_id: str, db: AsyncSession = Depends(_db)
) -> dict[str, str]:
    svc = CommandScheduleService(db)
    schedule = await svc.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail='Schedule not found')
    fire_id = await execute(
        schedule, db, subprocess_runner, trigger_source='manual'
    )
    return {'fire_id': fire_id}


@router.post('/command-schedules/pause-all')
async def pause_all(db: AsyncSession = Depends(_db)) -> dict[str, int]:
    svc = CommandScheduleService(db)
    all_rows = await svc.list_schedules()
    for row in all_rows:
        scheduler_integration.unregister_schedule(row.id)
    n = await svc.pause_all()
    return {'paused': n}


@router.post('/command-schedules/resume-all')
async def resume_all(db: AsyncSession = Depends(_db)) -> dict[str, int]:
    svc = CommandScheduleService(db)
    n = await svc.resume_all()
    for row in await svc.list_schedules(enabled=True):
        scheduler_integration.register_schedule(row)
    await scheduler_integration.sync_next_fire_at()
    return {'resumed': n}


@router.get(
    '/command-schedules/{schedule_id}/fires',
    response_model=list[CommandFireInfo],
)
async def list_fires(
    schedule_id: str,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(_db),
) -> list[CommandFireInfo]:
    return await CommandScheduleService(db).list_fires(
        schedule_id, limit, offset
    )


@router.get(
    '/command-schedules/fires/{fire_id}', response_model=CommandFireInfo
)
async def get_fire(
    fire_id: str, db: AsyncSession = Depends(_db)
) -> CommandFireInfo:
    row = await CommandScheduleService(db).get_fire(fire_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Fire not found')
    return row


@router.get('/command-schedules/fires/{fire_id}/log')
async def download_fire_log(
    fire_id: str, db: AsyncSession = Depends(_db)
) -> FileResponse:
    row = await CommandScheduleService(db).get_fire(fire_id)
    if row is None or not row.log_file_path:
        raise HTTPException(status_code=404, detail='Log not found')
    return FileResponse(row.log_file_path, filename=f'{fire_id}.log')


# ─── Holidays ──────────────────────────────────────────────────────


@router.get(
    '/command-scheduler/holidays', response_model=list[HolidayInfo]
)
async def list_holidays(
    year: int, db: AsyncSession = Depends(_db)
) -> list[HolidayInfo]:
    return await HolidayService(db).list_year(year)


@router.post('/command-scheduler/holidays', response_model=HolidayInfo)
async def add_holiday(
    payload: dict, db: AsyncSession = Depends(_db)
) -> HolidayInfo:
    try:
        return await HolidayService(db).add_user_holiday(
            payload['date'],
            payload['name'],
            payload.get('kind', 'holiday'),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete('/command-scheduler/holidays/{date}')
async def remove_holiday(
    date: str, db: AsyncSession = Depends(_db)
) -> dict[str, bool]:
    try:
        await HolidayService(db).delete_user_holiday(date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {'deleted': True}


@router.get(
    '/command-scheduler/holidays/check/{date}',
    response_model=HolidayCheckResult,
)
async def check_holiday(
    date: str, db: AsyncSession = Depends(_db)
) -> HolidayCheckResult:
    return await HolidayService(db).check_date(date)


# ─── Windows runner (pull model) ───────────────────────────────────


@router.get(
    '/command-scheduler/windows-runner/pending',
    response_model=list[PendingFireForRunner],
    dependencies=[Depends(_require_runner_key)],
)
async def runner_pending(
    db: AsyncSession = Depends(_db),
) -> list[PendingFireForRunner]:
    """Return all fires waiting for a Windows runner to pick up."""
    svc = CommandScheduleService(db)
    rows = await svc.list_pending_runner_fires()
    return [
        PendingFireForRunner(
            fire_id=str(fire.id).replace('-', ''),
            schedule_id=str(fire.schedule_id).replace('-', ''),
            schedule_name=schedule.name,
            command=schedule.command,
            working_dir=schedule.working_dir,
            max_duration_sec=schedule.max_duration_sec,
            created_at=fire.started_at,
        )
        for fire, schedule in rows
    ]


@router.post(
    '/command-scheduler/windows-runner/fires/{fire_id}/start',
    dependencies=[Depends(_require_runner_key)],
)
async def runner_start(
    fire_id: str,
    db: AsyncSession = Depends(_db),
) -> dict[str, str]:
    """Mark a pending fire as running. Runner calls this right before
    executing the command. Returns 409 if the fire has already been
    claimed by another runner instance (race guard)."""
    svc = CommandScheduleService(db)
    fire = await svc.get_fire(fire_id)
    if fire is None:
        raise HTTPException(status_code=404, detail='Fire not found')
    if fire.status != 'pending_runner':
        raise HTTPException(
            status_code=409,
            detail=f'Fire is {fire.status}, not pending_runner',
        )
    await svc.update_fire(fire_id, status='running')
    return {'status': 'running'}


@router.post(
    '/command-scheduler/windows-runner/fires/{fire_id}/complete',
    dependencies=[Depends(_require_runner_key)],
)
async def runner_complete(
    fire_id: str,
    payload: RunnerCompleteRequest,
    db: AsyncSession = Depends(_db),
) -> dict[str, str]:
    """Record the runner's execution result. Writes the full log file
    the same way the local subprocess path does."""
    svc = CommandScheduleService(db)
    fire = await svc.get_fire(fire_id)
    if fire is None:
        raise HTTPException(status_code=404, detail='Fire not found')

    # Classify if the runner didn't explicitly.
    if payload.status is not None:
        status = payload.status
    elif payload.exit_code == 0:
        status = 'success'
    else:
        status = 'failed'

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    log_path_str: str | None = None
    try:
        log_path = write_full_log(
            fire.schedule_id,
            fire_id,
            payload.stdout,
            payload.stderr,
            fire.started_at,
            now,
            payload.exit_code,
        )
        log_path_str = str(log_path)
    except Exception as e:
        _logger.warning('runner_complete write_full_log failed: %s', e)

    await svc.update_fire(
        fire_id,
        status=status,
        exit_code=payload.exit_code,
        stdout_tail=tail_bytes_and_lines(payload.stdout),
        stderr_tail=tail_bytes_and_lines(payload.stderr),
        log_file_path=log_path_str,
        completed=True,
    )
    return {'status': status}


@router.post(
    '/command-scheduler/windows-runner/heartbeat',
    dependencies=[Depends(_require_runner_key)],
)
async def runner_heartbeat(
    payload: RunnerHeartbeatRequest,
) -> dict[str, Any]:
    """Runner pings every poll cycle; we cache the last-seen timestamp
    so the UI can surface whether a runner is online."""
    _last_heartbeat[payload.runner_id] = {
        'runner_id': payload.runner_id,
        'runner_version': payload.runner_version,
        'last_seen': datetime.now(timezone.utc).isoformat(),
    }
    return {'ok': True}


@router.get('/command-scheduler/windows-runner/status')
async def runner_status() -> dict[str, Any]:
    """Public status endpoint (no auth) — returns cached last-seen
    info for every known runner. UI uses this to show whether a
    Windows runner is currently online."""
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for info in _last_heartbeat.values():
        last = datetime.fromisoformat(info['last_seen'])
        seconds_ago = int((now - last).total_seconds())
        out.append(
            {
                **info,
                'seconds_ago': seconds_ago,
                'online': seconds_ago < 60,
            }
        )
    return {'runners': out}
