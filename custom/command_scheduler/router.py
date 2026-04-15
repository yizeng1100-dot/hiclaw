"""FastAPI router for command_scheduler endpoints.

Mounted at ``/api/v1/command-schedules`` (schedules CRUD + fires) and
``/api/v1/command-scheduler/holidays`` (holiday management).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
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
from custom.command_scheduler.models import (
    CommandFireInfo,
    CommandScheduleCreate,
    CommandScheduleInfo,
    CommandScheduleUpdate,
    HolidayCheckResult,
    HolidayInfo,
)
from custom.command_scheduler.runners import subprocess_runner
from custom.command_scheduler.service import CommandScheduleService

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
