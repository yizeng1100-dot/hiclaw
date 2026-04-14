"""FastAPI router for scheduled tasks: CRUD + fire-now + fire history.

Mounted from ``openhands/server/app.py`` under ``/api/v1`` so the
routes live at:

  GET    /api/v1/scheduled-tasks
  POST   /api/v1/scheduled-tasks
  GET    /api/v1/scheduled-tasks/{id}
  PATCH  /api/v1/scheduled-tasks/{id}
  DELETE /api/v1/scheduled-tasks/{id}
  POST   /api/v1/scheduled-tasks/{id}/fire-now
  GET    /api/v1/scheduled-tasks/{id}/fires
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

from custom.agent_mgmt.db import get_agent_db
from custom.scheduled_tasks import scheduler as scheduler_module
from custom.scheduled_tasks.cron_util import InvalidScheduleError, schedule_params_to_trigger
from custom.scheduled_tasks.fire import fire_schedule
from custom.scheduled_tasks.models import (
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from custom.scheduled_tasks.service import ScheduledTaskService

_logger = logging.getLogger(__name__)

router = APIRouter(prefix='/scheduled-tasks', tags=['Scheduled Tasks'])


@router.get('')
async def list_scheduled_tasks(enabled: bool | None = Query(None)):
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        tasks = await svc.list_schedules(enabled=enabled)
        return {'schedules': [t.model_dump(mode='json') for t in tasks]}
    finally:
        await db.close()


@router.post('')
async def create_scheduled_task(data: ScheduledTaskCreate):
    # Validate the schedule up front so callers get a clean 400, not a
    # background scheduler crash at first fire time.
    try:
        schedule_params_to_trigger(data.schedule.kind, data.schedule.params)
    except InvalidScheduleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        sched_id = await svc.create_schedule(data)
        created = await svc.get_schedule(sched_id)
    finally:
        await db.close()

    if created is not None:
        try:
            scheduler_module.register_schedule(created)
            await scheduler_module.sync_next_fire_at()
        except Exception:
            _logger.exception('failed to register new schedule with scheduler')

    return created.model_dump(mode='json') if created else {'id': sched_id}


@router.get('/{schedule_id}')
async def get_scheduled_task(schedule_id: str):
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        task = await svc.get_schedule(schedule_id)
    finally:
        await db.close()
    if task is None:
        raise HTTPException(status_code=404, detail='Scheduled task not found')
    return task.model_dump(mode='json')


@router.patch('/{schedule_id}')
async def update_scheduled_task(schedule_id: str, data: ScheduledTaskUpdate):
    # Validate new schedule (if provided) before touching the DB.
    if data.schedule is not None:
        try:
            schedule_params_to_trigger(data.schedule.kind, data.schedule.params)
        except InvalidScheduleError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        ok = await svc.update_schedule(schedule_id, data)
        if not ok:
            raise HTTPException(status_code=404, detail='Scheduled task not found')
        updated = await svc.get_schedule(schedule_id)
    finally:
        await db.close()

    if updated is not None:
        try:
            scheduler_module.reschedule(updated)
            await scheduler_module.sync_next_fire_at()
        except Exception:
            _logger.exception('failed to reschedule job after update')

    return updated.model_dump(mode='json') if updated else {'status': 'updated'}


@router.delete('/{schedule_id}')
async def delete_scheduled_task(schedule_id: str):
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        ok = await svc.delete_schedule(schedule_id)
    finally:
        await db.close()
    if not ok:
        raise HTTPException(status_code=404, detail='Scheduled task not found')

    scheduler_module.unregister_schedule(schedule_id)
    return {'status': 'deleted'}


@router.post('/{schedule_id}/fire-now')
async def fire_now(schedule_id: str):
    """Manually trigger a single fire immediately (bypass schedule).

    Runs ``fire_schedule`` as a detached task so the HTTP response
    returns quickly; the fire runs in the background and its outcome
    lands in the fire history (list via ``GET .../fires``).
    """
    # Verify existence first so the caller gets a proper 404.
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        task = await svc.get_schedule(schedule_id)
    finally:
        await db.close()
    if task is None:
        raise HTTPException(status_code=404, detail='Scheduled task not found')

    asyncio.create_task(fire_schedule(schedule_id))
    return {'status': 'fire_scheduled', 'schedule_id': schedule_id}


@router.get('/{schedule_id}/fires')
async def list_fires(schedule_id: str, limit: int = Query(50, ge=1, le=500)):
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        fires = await svc.list_fires(schedule_id, limit=limit)
    finally:
        await db.close()
    return {'fires': [f.model_dump(mode='json') for f in fires]}
