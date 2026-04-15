"""Scheduled entry point called by APScheduler when a command schedule fires."""

from __future__ import annotations

import logging

from custom.command_scheduler.db import get_cs_db
from custom.command_scheduler.executor import execute
from custom.command_scheduler.runners import subprocess_runner
from custom.command_scheduler.service import CommandScheduleService

_logger = logging.getLogger(__name__)


async def fire_command_schedule(schedule_id: str) -> None:
    """Called by the shared APScheduler. Delegates to the executor."""
    db = await get_cs_db()
    try:
        svc = CommandScheduleService(db)
        schedule = await svc.get_schedule(schedule_id)
        if schedule is None:
            _logger.warning(
                'fire_command_schedule: schedule %s not found', schedule_id
            )
            return
        # P1 starts with subprocess_runner; Task 7 will swap in sandbox
        # with a subprocess fallback when the sandbox wiring isn't ready.
        await execute(schedule, db, subprocess_runner, trigger_source='scheduled')
    finally:
        await db.close()

    # Sync next_fire_at back into DB for the list page
    try:
        from custom.command_scheduler.scheduler_integration import (
            sync_next_fire_at,
        )

        await sync_next_fire_at()
    except Exception:
        _logger.exception('failed to sync next_fire_at after fire')
