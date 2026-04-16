"""Async CRUD + fire-log service for the command scheduler tables.

Pure DB access — no APScheduler coupling. The scheduler_integration
module is responsible for keeping the in-memory job store in sync.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from custom.command_scheduler.cron_util import describe
from custom.command_scheduler.models import (
    CommandFireInfo,
    CommandScheduleCreate,
    CommandScheduleInfo,
    CommandScheduleUpdate,
    StoredCommandFire,
    StoredCommandSchedule,
)


def _hex(v: Any) -> str:
    return str(v).replace('-', '')


def _to_uuid(v: Any) -> UUID:
    if isinstance(v, UUID):
        return v
    s = str(v)
    try:
        return UUID(s)
    except ValueError:
        return UUID(s.replace('-', ''))


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class CommandScheduleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ─── Schedules ────────────────────────────────────────────────

    async def list_schedules(
        self,
        enabled: bool | None = None,
        env_tag: str | None = None,
        q: str | None = None,
    ) -> list[CommandScheduleInfo]:
        stmt = select(StoredCommandSchedule)
        if enabled is not None:
            stmt = stmt.where(StoredCommandSchedule.enabled == enabled)
        if env_tag is not None:
            stmt = stmt.where(StoredCommandSchedule.env_tag == env_tag)
        if q:
            stmt = stmt.where(StoredCommandSchedule.name.ilike(f'%{q}%'))
        stmt = stmt.order_by(desc(StoredCommandSchedule.created_at))
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_info(r) for r in rows]

    async def get_schedule(
        self, schedule_id: str
    ) -> CommandScheduleInfo | None:
        row = await self.db.get(StoredCommandSchedule, _to_uuid(schedule_id))
        if row is None:
            return None
        return self._row_to_info(row)

    async def create_schedule(
        self, payload: CommandScheduleCreate
    ) -> CommandScheduleInfo:
        row = StoredCommandSchedule(
            id=uuid4(),
            name=payload.name,
            env_tag=payload.env_tag,
            shell_kind=payload.shell_kind,
            kind=payload.kind,
            cron_expr=payload.cron_expr,
            run_at=_to_naive_utc(payload.run_at),
            command=payload.command,
            working_dir=payload.working_dir,
            max_duration_sec=payload.max_duration_sec,
            holiday_policy=payload.holiday_policy,
            log_path=payload.log_path,
            enabled=payload.enabled,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self._row_to_info(row)

    async def update_schedule(
        self, schedule_id: str, patch: CommandScheduleUpdate
    ) -> CommandScheduleInfo | None:
        row = await self.db.get(StoredCommandSchedule, _to_uuid(schedule_id))
        if row is None:
            return None
        data = patch.model_dump(exclude_unset=True)
        if 'run_at' in data:
            data['run_at'] = _to_naive_utc(data['run_at'])
        for field, value in data.items():
            setattr(row, field, value)
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        await self.db.refresh(row)
        return self._row_to_info(row)

    async def delete_schedule(self, schedule_id: str) -> bool:
        row = await self.db.get(StoredCommandSchedule, _to_uuid(schedule_id))
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def set_next_fire_at(
        self, schedule_id: str, next_fire: datetime | None
    ) -> None:
        row = await self.db.get(StoredCommandSchedule, _to_uuid(schedule_id))
        if row is None:
            return
        row.next_fire_at = _to_naive_utc(next_fire)
        await self.db.commit()

    async def pause_all(self) -> int:
        stmt = select(StoredCommandSchedule).where(
            StoredCommandSchedule.enabled.is_(True)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            row.enabled = False
        await self.db.commit()
        return len(rows)

    async def resume_all(self) -> int:
        stmt = select(StoredCommandSchedule).where(
            StoredCommandSchedule.enabled.is_(False)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            row.enabled = True
        await self.db.commit()
        return len(rows)

    async def count_status(self) -> dict[str, int]:
        """Return counts for the stats bar."""
        total_stmt = select(func.count(StoredCommandSchedule.id))
        enabled_stmt = select(func.count(StoredCommandSchedule.id)).where(
            StoredCommandSchedule.enabled.is_(True)
        )
        running_stmt = select(func.count(StoredCommandFire.id)).where(
            StoredCommandFire.status == 'running'
        )
        total = (await self.db.execute(total_stmt)).scalar() or 0
        enabled = (await self.db.execute(enabled_stmt)).scalar() or 0
        running = (await self.db.execute(running_stmt)).scalar() or 0
        return {
            'total': total,
            'running': running,
            'enabled': enabled,
            'disabled': total - enabled,
        }

    # ─── Fires ────────────────────────────────────────────────────

    async def list_fires(
        self, schedule_id: str, limit: int = 20, offset: int = 0
    ) -> list[CommandFireInfo]:
        stmt = (
            select(StoredCommandFire)
            .where(StoredCommandFire.schedule_id == _to_uuid(schedule_id))
            .order_by(desc(StoredCommandFire.started_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._fire_row_to_info(r) for r in rows]

    async def get_fire(self, fire_id: str) -> CommandFireInfo | None:
        row = await self.db.get(StoredCommandFire, _to_uuid(fire_id))
        if row is None:
            return None
        return self._fire_row_to_info(row)

    async def create_fire(
        self,
        schedule_id: str,
        trigger_source: str = 'scheduled',
    ) -> CommandFireInfo:
        row = StoredCommandFire(
            id=uuid4(),
            schedule_id=_to_uuid(schedule_id),
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status='running',
            trigger_source=trigger_source,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self._fire_row_to_info(row)

    async def update_fire(
        self,
        fire_id: str,
        *,
        status: str | None = None,
        skip_reason: str | None = None,
        exit_code: int | None = None,
        stdout_tail: str | None = None,
        stderr_tail: str | None = None,
        log_file_path: str | None = None,
        completed: bool = False,
    ) -> None:
        row = await self.db.get(StoredCommandFire, _to_uuid(fire_id))
        if row is None:
            return
        if status is not None:
            row.status = status
        if skip_reason is not None:
            row.skip_reason = skip_reason
        if exit_code is not None:
            row.exit_code = exit_code
        if stdout_tail is not None:
            row.stdout_tail = stdout_tail
        if stderr_tail is not None:
            row.stderr_tail = stderr_tail
        if log_file_path is not None:
            row.log_file_path = log_file_path
        if completed:
            row.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()

    async def list_pending_runner_fires(self) -> list[tuple[StoredCommandFire, StoredCommandSchedule]]:
        """All fires stuck in ``pending_runner`` plus their schedule rows.

        Used by the Windows runner pull endpoint to hand out work.
        Oldest fires first so nothing starves.
        """
        stmt = (
            select(StoredCommandFire, StoredCommandSchedule)
            .join(
                StoredCommandSchedule,
                StoredCommandFire.schedule_id == StoredCommandSchedule.id,
            )
            .where(StoredCommandFire.status == 'pending_runner')
            .order_by(StoredCommandFire.started_at)
        )
        result = await self.db.execute(stmt)
        return list(result.all())

    async def has_running_fire_excluding(
        self, schedule_id: str, fire_id: str
    ) -> bool:
        stmt = select(StoredCommandFire).where(
            StoredCommandFire.schedule_id == _to_uuid(schedule_id),
            StoredCommandFire.status == 'running',
            StoredCommandFire.id != _to_uuid(fire_id),
        )
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None

    # ─── Row → Info ───────────────────────────────────────────────

    def _row_to_info(
        self, row: StoredCommandSchedule
    ) -> CommandScheduleInfo:
        return CommandScheduleInfo(
            id=_hex(row.id),
            name=row.name,
            env_tag=row.env_tag,  # type: ignore[arg-type]
            shell_kind=row.shell_kind,  # type: ignore[arg-type]
            kind=row.kind,  # type: ignore[arg-type]
            cron_expr=row.cron_expr,
            run_at=row.run_at,
            command=row.command,
            working_dir=row.working_dir,
            max_duration_sec=row.max_duration_sec,
            holiday_policy=row.holiday_policy,  # type: ignore[arg-type]
            log_path=row.log_path,
            enabled=row.enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_fire_at=row.last_fire_at,
            next_fire_at=row.next_fire_at,
            schedule_description=describe(
                row.kind,  # type: ignore[arg-type]
                row.cron_expr,
                row.run_at,
            ),
        )

    @staticmethod
    def _fire_row_to_info(row: StoredCommandFire) -> CommandFireInfo:
        return CommandFireInfo(
            id=_hex(row.id),
            schedule_id=_hex(row.schedule_id),
            started_at=row.started_at,
            completed_at=row.completed_at,
            status=row.status,  # type: ignore[arg-type]
            skip_reason=row.skip_reason,
            exit_code=row.exit_code,
            stdout_tail=row.stdout_tail,
            stderr_tail=row.stderr_tail,
            log_file_path=row.log_file_path,
            trigger_source=row.trigger_source,  # type: ignore[arg-type]
        )
