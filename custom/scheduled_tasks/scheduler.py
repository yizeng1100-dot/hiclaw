"""AsyncIOScheduler lifecycle wrapper.

Owns a module-level ``AsyncIOScheduler`` instance tied to the uvicorn
event loop. On lifespan startup we call :func:`start` which:

1. Creates the scheduler (if not already).
2. Loads every enabled schedule from the DB.
3. Registers a job per schedule pointing at ``fire.fire_schedule``.

On lifespan shutdown we call :func:`shutdown`.

The router calls :func:`register_schedule` / :func:`unregister_schedule`
whenever CRUD operations land so the in-memory scheduler stays in sync
with the DB.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from custom.agent_mgmt.db import get_agent_db
from custom.scheduled_tasks.cron_util import schedule_params_to_trigger
from custom.scheduled_tasks.fire import fire_schedule
from custom.scheduled_tasks.models import ScheduledTaskInfo
from custom.scheduled_tasks.service import ScheduledTaskService

_logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            job_defaults={
                'coalesce': True,           # collapse misfire bursts into one
                'max_instances': 1,         # queue, don't run concurrently
                'misfire_grace_time': 3600, # catch up within 1h after downtime
            },
            timezone='Asia/Shanghai',
        )
    return _scheduler


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running


async def start() -> None:
    """Start the scheduler and load all enabled schedules from the DB."""
    sched = _get_scheduler()
    if sched.running:
        return

    sched.start()
    _logger.info('AsyncIOScheduler started')

    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        schedules = await svc.list_schedules(enabled=True)
    finally:
        await db.close()

    loaded = 0
    for schedule in schedules:
        try:
            _register(schedule)
            loaded += 1
        except Exception:
            _logger.exception('failed to register schedule %s at startup', schedule.id)
    _logger.info('scheduler loaded %d enabled schedules from DB', loaded)

    # Best-effort: push next_fire_at back into the DB so the task-center
    # list can show it without a separate RPC to the scheduler.
    await _refresh_next_fire_at_column()


async def shutdown() -> None:
    global _scheduler
    if _scheduler is None or not _scheduler.running:
        return
    try:
        _scheduler.shutdown(wait=False)
        _logger.info('AsyncIOScheduler stopped')
    except Exception:
        _logger.exception('AsyncIOScheduler shutdown raised')


def _register(schedule: ScheduledTaskInfo) -> None:
    sched = _get_scheduler()
    trigger = schedule_params_to_trigger(
        schedule.schedule.kind, schedule.schedule.params
    )
    sched.add_job(
        fire_schedule,
        trigger=trigger,
        args=[schedule.id],
        id=schedule.id,
        name=schedule.name,
        replace_existing=True,
    )


def register_schedule(schedule: ScheduledTaskInfo) -> None:
    """Add or replace a job for an enabled schedule."""
    if not schedule.enabled:
        unregister_schedule(schedule.id)
        return
    _register(schedule)


def unregister_schedule(schedule_id: str) -> None:
    """Remove a scheduler job by id. Safe to call on absent jobs."""
    sched = _get_scheduler()
    try:
        sched.remove_job(schedule_id)
    except JobLookupError:
        pass


def reschedule(schedule: ScheduledTaskInfo) -> None:
    """Shorthand for unregister + register."""
    unregister_schedule(schedule.id)
    register_schedule(schedule)


def get_next_fire_at(schedule_id: str) -> Any:
    """Return the APScheduler next_run_time for a job, or None."""
    sched = _get_scheduler()
    try:
        job = sched.get_job(schedule_id)
    except JobLookupError:
        return None
    if job is None:
        return None
    return job.next_run_time


async def _refresh_next_fire_at_column() -> None:
    """Sync in-memory next_run_time into the DB ``next_fire_at`` column.

    Invoked by :func:`start` once at boot, by the router after any
    CRUD, and by :func:`fire.fire_schedule` after each fire. The list
    page reads this column directly so it doesn't need a live RPC
    to the scheduler.

    Iterates DB schedules (not scheduler jobs) so that one-shot
    DateTrigger jobs that have already fired — and are therefore
    removed from APScheduler's jobstore — get their ``next_fire_at``
    explicitly cleared to NULL.
    """
    sched = _get_scheduler()
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        schedules = await svc.list_schedules()
        for schedule in schedules:
            try:
                job = sched.get_job(schedule.id)
            except Exception:
                job = None
            nrt = job.next_run_time if job is not None else None
            if nrt is not None:
                # Convert to naive UTC for storage consistency with
                # other UtcDateTime columns.
                nrt = nrt.astimezone(timezone.utc).replace(tzinfo=None)
            await svc.set_next_fire_at(schedule.id, nrt)
    finally:
        await db.close()


async def sync_next_fire_at() -> None:
    """Public variant of :func:`_refresh_next_fire_at_column`."""
    await _refresh_next_fire_at_column()
