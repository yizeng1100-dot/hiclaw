"""Register command_scheduler jobs onto the shared AsyncIOScheduler.

Expects that ``custom.scheduled_tasks.scheduler.start()`` has already
been called (which owns the actual ``scheduler.start()`` invocation).
If this module's ``init()`` runs before that, jobs are still added to
the AsyncIOScheduler instance and will become active once ``start()``
runs — APScheduler supports adding jobs to a not-yet-running
scheduler.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any

from apscheduler.jobstores.base import JobLookupError

from custom.command_scheduler.cron_util import build_trigger
from custom.command_scheduler.db import get_cs_db
from custom.command_scheduler.models import CommandScheduleInfo
from custom.command_scheduler.service import CommandScheduleService
from custom.scheduled_tasks.scheduler import get_shared_scheduler

_logger = logging.getLogger(__name__)

_JOB_PREFIX = 'cs:'
_CLEANUP_JOB_ID = 'cs:cleanup-logs'


def _job_id(schedule_id: str) -> str:
    return f'{_JOB_PREFIX}{schedule_id}'


async def init() -> None:
    """Load all enabled command schedules from DB and register jobs.

    Also registers the daily cleanup job.
    """
    db = await get_cs_db()
    try:
        svc = CommandScheduleService(db)
        rows = await svc.list_schedules(enabled=True)
    finally:
        await db.close()

    loaded = 0
    for row in rows:
        try:
            _register(row)
            loaded += 1
        except Exception:
            _logger.exception(
                'command_scheduler: failed to register schedule %s at startup',
                row.id,
            )
    _logger.info('command_scheduler: loaded %d enabled schedules', loaded)

    _register_cleanup_job()
    await _refresh_next_fire_at_column()


def _register(schedule: CommandScheduleInfo) -> None:
    # Lazy import to avoid a circular dependency:
    # fire imports scheduler_integration (to call sync_next_fire_at).
    from custom.command_scheduler.fire import fire_command_schedule

    sched = get_shared_scheduler()
    trigger = build_trigger(schedule.kind, schedule.cron_expr, schedule.run_at)
    sched.add_job(
        fire_command_schedule,
        trigger=trigger,
        args=[schedule.id],
        id=_job_id(schedule.id),
        name=f'cs:{schedule.name}',
        replace_existing=True,
    )


def register_schedule(schedule: CommandScheduleInfo) -> None:
    if not schedule.enabled:
        unregister_schedule(schedule.id)
        return
    _register(schedule)


def unregister_schedule(schedule_id: str) -> None:
    sched = get_shared_scheduler()
    try:
        sched.remove_job(_job_id(schedule_id))
    except JobLookupError:
        pass


def reschedule(schedule: CommandScheduleInfo) -> None:
    unregister_schedule(schedule.id)
    register_schedule(schedule)


def get_next_fire_at(schedule_id: str) -> Any:
    sched = get_shared_scheduler()
    try:
        job = sched.get_job(_job_id(schedule_id))
    except JobLookupError:
        return None
    if job is None:
        return None
    return job.next_run_time


def _register_cleanup_job() -> None:
    from apscheduler.triggers.cron import CronTrigger

    from custom.command_scheduler.log_io import cleanup_old_logs

    sched = get_shared_scheduler()

    async def _cleanup() -> None:
        try:
            n = cleanup_old_logs(retention_days=30)
            _logger.info(
                'command_scheduler cleanup: deleted %d old log files', n
            )
        except Exception:
            _logger.exception('command_scheduler cleanup job crashed')

    sched.add_job(
        _cleanup,
        trigger=CronTrigger.from_crontab('0 3 * * *', timezone='Asia/Shanghai'),
        id=_CLEANUP_JOB_ID,
        name='cs:cleanup-old-logs',
        replace_existing=True,
    )


async def _refresh_next_fire_at_column() -> None:
    sched = get_shared_scheduler()
    db = await get_cs_db()
    try:
        svc = CommandScheduleService(db)
        rows = await svc.list_schedules()
        for row in rows:
            job = None
            try:
                job = sched.get_job(_job_id(row.id))
            except Exception:
                pass
            nrt = job.next_run_time if job is not None else None
            if nrt is not None:
                nrt = nrt.astimezone(timezone.utc).replace(tzinfo=None)
            await svc.set_next_fire_at(row.id, nrt)
    finally:
        await db.close()


async def sync_next_fire_at() -> None:
    await _refresh_next_fire_at_column()
