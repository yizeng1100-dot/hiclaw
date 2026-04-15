"""Holiday lookup service: preset data + user additions.

On first use the service loads all bundled
``custom/command_scheduler/data/holidays_cn_*.yaml`` files and upserts
their entries into the ``holidays`` table with ``source='preset'``.
User-added rows (``source='user'``) are left untouched.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from custom.command_scheduler.models import (
    HolidayCheckResult,
    HolidayInfo,
    StoredHoliday,
)

_logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / 'data'


async def sync_preset_holidays(db: AsyncSession) -> int:
    """Read all holidays_cn_*.yaml and upsert into the holidays table.

    Idempotent — can be called every startup. Returns number of preset
    rows upserted. Doesn't touch source='user' rows.
    """
    count = 0
    for yaml_path in sorted(_DATA_DIR.glob('holidays_cn_*.yaml')):
        with yaml_path.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get('holidays') or []:
            await _upsert_preset(db, entry['date'], entry['name'], 'holiday')
            count += 1
        for entry in data.get('makeup_workdays') or []:
            await _upsert_preset(
                db, entry['date'], entry['name'], 'makeup_workday'
            )
            count += 1
    await db.commit()
    _logger.info('command_scheduler: synced %d preset holiday rows', count)
    return count


async def _upsert_preset(
    db: AsyncSession, d: str, name: str, kind: str
) -> None:
    existing = await db.get(StoredHoliday, d)
    if existing is None:
        db.add(
            StoredHoliday(date=d, name=name, kind=kind, source='preset')
        )
    elif existing.source == 'preset':
        existing.name = name
        existing.kind = kind


class HolidayService:
    """Query and mutate the holidays table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_year(self, year: int) -> list[HolidayInfo]:
        prefix = f'{year:04d}-'
        stmt = (
            select(StoredHoliday)
            .where(StoredHoliday.date.like(f'{prefix}%'))
            .order_by(StoredHoliday.date)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_info(r) for r in rows]

    async def add_user_holiday(
        self, d: str, name: str, kind: str
    ) -> HolidayInfo:
        existing = await self.db.get(StoredHoliday, d)
        if existing is not None:
            raise ValueError(
                f'date {d} already exists (source={existing.source})'
            )
        row = StoredHoliday(date=d, name=name, kind=kind, source='user')
        self.db.add(row)
        await self.db.commit()
        return self._row_to_info(row)

    async def delete_user_holiday(self, d: str) -> None:
        existing = await self.db.get(StoredHoliday, d)
        if existing is None:
            return
        if existing.source != 'user':
            raise ValueError(f'cannot delete preset row {d}')
        await self.db.execute(
            delete(StoredHoliday).where(StoredHoliday.date == d)
        )
        await self.db.commit()

    async def check_date(self, d: str) -> HolidayCheckResult:
        row = await self.db.get(StoredHoliday, d)
        weekend = _is_weekend(d)
        if row is None:
            return HolidayCheckResult(
                date=d,
                is_holiday=weekend,
                is_makeup_workday=False,
                is_workday=not weekend,
                name=None,
            )
        is_holiday = row.kind == 'holiday'
        is_makeup = row.kind == 'makeup_workday'
        return HolidayCheckResult(
            date=d,
            is_holiday=is_holiday,
            is_makeup_workday=is_makeup,
            is_workday=is_makeup or (not is_holiday and not weekend),
            name=row.name,
        )

    @staticmethod
    def _row_to_info(row: StoredHoliday) -> HolidayInfo:
        return HolidayInfo(
            date=row.date,
            name=row.name,
            kind=row.kind,  # type: ignore[arg-type]
            source=row.source,  # type: ignore[arg-type]
            created_at=row.created_at,
        )


def _is_weekend(d: str) -> bool:
    try:
        dt = datetime.strptime(d, '%Y-%m-%d').date()
    except ValueError:
        return False
    return dt.weekday() >= 5
