"""CRUD + fire-log service for the ``scheduled_task`` + ``scheduled_task_fire`` tables.

Pure DB access — no APScheduler coupling. The scheduler module owns its
own lifecycle and just calls into this service to persist changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from custom.agent_mgmt.models import StoredAgent
from custom.scheduled_tasks.cron_util import describe_schedule
from custom.scheduled_tasks.models import (
    ScheduledTaskCreate,
    ScheduledTaskFireInfo,
    ScheduledTaskInfo,
    ScheduledTaskUpdate,
    SchedulePayload,
    StoredScheduledTask,
    StoredScheduledTaskFire,
)


def _to_uuid_hex(val: Any) -> str:
    return str(val).replace('-', '')


def _to_uuid(val: Any) -> UUID:
    """Coerce a hex-or-hyphenated string / UUID into a UUID instance."""
    if isinstance(val, UUID):
        return val
    s = str(val)
    try:
        return UUID(s)
    except ValueError:
        return UUID(s.replace('-', ''))


def _row_to_info(
    row: StoredScheduledTask, agent_name: str | None
) -> ScheduledTaskInfo:
    try:
        params = json.loads(row.schedule_params or '{}')
    except Exception:
        params = {}
    try:
        form_values = json.loads(row.form_values or '{}')
    except Exception:
        form_values = {}

    return ScheduledTaskInfo(
        id=_to_uuid_hex(row.id),
        agent_id=_to_uuid_hex(row.agent_id),
        agent_name=agent_name,
        name=row.name,
        schedule=SchedulePayload(kind=row.schedule_kind, params=params),
        schedule_description=describe_schedule(row.schedule_kind, params),
        form_values=form_values,
        enabled=bool(row.enabled),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_fire_at=row.last_fire_at,
        next_fire_at=row.next_fire_at,
        last_status=row.last_status,
    )


def _fire_row_to_info(row: StoredScheduledTaskFire) -> ScheduledTaskFireInfo:
    return ScheduledTaskFireInfo(
        id=_to_uuid_hex(row.id),
        scheduled_task_id=_to_uuid_hex(row.scheduled_task_id),
        started_at=row.started_at,
        completed_at=row.completed_at,
        status=row.status,
        task_id=row.task_id,
        conversation_id=row.conversation_id,
        error_message=row.error_message,
    )


class ScheduledTaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─── schedules ─────────────────────────────────────────────────

    async def list_schedules(
        self, enabled: bool | None = None
    ) -> list[ScheduledTaskInfo]:
        stmt = (
            select(StoredScheduledTask, StoredAgent.name.label('agent_name'))
            .outerjoin(StoredAgent, StoredScheduledTask.agent_id == StoredAgent.id)
            .order_by(StoredScheduledTask.created_at.desc())
        )
        if enabled is not None:
            stmt = stmt.where(StoredScheduledTask.enabled == enabled)
        rows = (await self.db.execute(stmt)).all()
        return [_row_to_info(r[0], r[1]) for r in rows]

    async def get_schedule(
        self, schedule_id: str
    ) -> ScheduledTaskInfo | None:
        stmt = (
            select(StoredScheduledTask, StoredAgent.name.label('agent_name'))
            .outerjoin(StoredAgent, StoredScheduledTask.agent_id == StoredAgent.id)
            .where(StoredScheduledTask.id == _to_uuid(schedule_id))
        )
        row = (await self.db.execute(stmt)).first()
        if not row:
            return None
        return _row_to_info(row[0], row[1])

    async def create_schedule(self, data: ScheduledTaskCreate) -> str:
        now = datetime.now(timezone.utc)
        sched_id = uuid4()
        row = StoredScheduledTask(
            id=sched_id,
            agent_id=_to_uuid(data.agent_id),
            name=data.name,
            schedule_kind=data.schedule.kind,
            schedule_params=json.dumps(data.schedule.params, ensure_ascii=False),
            form_values=json.dumps(data.form_values, ensure_ascii=False),
            enabled=data.enabled,
            created_at=now,
            updated_at=now,
        )
        self.db.add(row)
        await self.db.commit()
        return sched_id.hex

    async def update_schedule(
        self, schedule_id: str, data: ScheduledTaskUpdate
    ) -> bool:
        kwargs: dict[str, Any] = {}
        if data.name is not None:
            kwargs['name'] = data.name
        if data.schedule is not None:
            kwargs['schedule_kind'] = data.schedule.kind
            kwargs['schedule_params'] = json.dumps(
                data.schedule.params, ensure_ascii=False
            )
        if data.form_values is not None:
            kwargs['form_values'] = json.dumps(data.form_values, ensure_ascii=False)
        if data.enabled is not None:
            kwargs['enabled'] = data.enabled
        if not kwargs:
            return True
        kwargs['updated_at'] = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(StoredScheduledTask)
            .where(StoredScheduledTask.id == _to_uuid(schedule_id))
            .values(**kwargs)
        )
        await self.db.commit()
        return bool(result.rowcount)

    async def delete_schedule(self, schedule_id: str) -> bool:
        result = await self.db.execute(
            delete(StoredScheduledTask).where(
                StoredScheduledTask.id == _to_uuid(schedule_id)
            )
        )
        await self.db.commit()
        return bool(result.rowcount)

    async def set_next_fire_at(
        self, schedule_id: str, next_fire_at: datetime | None
    ) -> None:
        await self.db.execute(
            update(StoredScheduledTask)
            .where(StoredScheduledTask.id == _to_uuid(schedule_id))
            .values(next_fire_at=next_fire_at)
        )
        await self.db.commit()

    # ─── fire history ──────────────────────────────────────────────

    async def list_fires(
        self, schedule_id: str, limit: int = 50
    ) -> list[ScheduledTaskFireInfo]:
        stmt = (
            select(StoredScheduledTaskFire)
            .where(
                StoredScheduledTaskFire.scheduled_task_id == _to_uuid(schedule_id)
            )
            .order_by(desc(StoredScheduledTaskFire.started_at))
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [_fire_row_to_info(r) for r in rows]

    async def create_fire(self, schedule_id: str) -> str:
        now = datetime.now(timezone.utc)
        fire_id = uuid4()
        row = StoredScheduledTaskFire(
            id=fire_id,
            scheduled_task_id=_to_uuid(schedule_id),
            started_at=now,
            status='running',
        )
        self.db.add(row)
        # Touch schedule's last_fire_at + last_status so the list page
        # reflects "running" immediately, not only after completion.
        await self.db.execute(
            update(StoredScheduledTask)
            .where(StoredScheduledTask.id == _to_uuid(schedule_id))
            .values(last_fire_at=now, last_status='running')
        )
        await self.db.commit()
        return fire_id.hex

    async def finish_fire(
        self,
        fire_id: str,
        status: str,
        task_id: str | None = None,
        conversation_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(StoredScheduledTaskFire)
            .where(StoredScheduledTaskFire.id == _to_uuid(fire_id))
            .values(
                completed_at=now,
                status=status,
                task_id=task_id,
                conversation_id=conversation_id,
                error_message=error_message,
            )
        )
        # Mirror final status back onto the schedule row.
        row = (
            await self.db.execute(
                select(StoredScheduledTaskFire).where(
                    StoredScheduledTaskFire.id == _to_uuid(fire_id)
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await self.db.execute(
                update(StoredScheduledTask)
                .where(StoredScheduledTask.id == row.scheduled_task_id)
                .values(last_status=status)
            )
        await self.db.commit()
