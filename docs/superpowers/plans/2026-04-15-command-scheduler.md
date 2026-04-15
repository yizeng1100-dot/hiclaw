# Command Scheduler — Implementation Plan (P1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the P1 slice of HiClaw's Command Scheduler — a new platform feature that lets users schedule shell commands (linux only, windows stored-not-executed), runs them in a shared persistent Process sandbox with a preinstalled venv, supports preset + custom holidays, and exposes a dedicated page in the sidebar.

**Architecture:** New module `custom/command_scheduler/` with 3 tables (`command_schedules`, `command_fires`, `holidays`), a FastAPI router at `/api/v1/command-schedules`, and APScheduler jobs registered onto the **shared scheduler instance** owned by `custom.scheduled_tasks.scheduler`. Frontend page at `/command-scheduler` with a split layout (task grid + calendar). Full design and ADRs live in `custom/docs/command_scheduler/DESIGN.md`.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, SQLAlchemy async, APScheduler (shared with scheduled_tasks), Pydantic v2
- DB: SQLite at `~/.openhands/openhands.db`
- Sandbox: HiClaw Process sandbox (lazy, single instance id `cmd-scheduler`)
- Frontend: React 19, react-router v7, Vite, Tailwind, existing dark theme
- Verification: curl + sqlite3 + browser DevTools (no pytest — HiClaw `custom/` is E2E verified)

**Prerequisites:**
- Branch: `feat/command-scheduler` (already created, has docs committed)
- Read first: `custom/docs/command_scheduler/DESIGN.md` sections 2 (ADRs), 4 (data model), 5 (execution model), 6 (API)
- Existing patterns to follow:
  - `custom/scheduled_tasks/models.py` — SQLAlchemy + Pydantic layout
  - `custom/scheduled_tasks/service.py` — async CRUD pattern
  - `custom/scheduled_tasks/scheduler.py` — AsyncIOScheduler lifecycle (we SHARE this)
  - `custom/scheduled_tasks/router.py` — FastAPI router shape
  - `frontend/src/components/features/custom/task-center/` — task-center-style page layout reference
  - `frontend/src/components/features/custom/chatbot/` — modal and API-client reference

**Phases:**
1. Tasks 1–5: Backend foundations (DB, holidays, services, executor, shared scheduler integration)
2. Tasks 6–7: Sandbox manager + switching executor to sandbox
3. Tasks 8: Router wiring + lifespan integration
4. Tasks 9–13: Frontend (API client → page → modals)
5. Task 14: E2E verification

**Out of scope for P1** (see DESIGN.md §9 for P2+):
- `run_before` / `run_after` compensation scanner (holiday_policy field exists but simple same-day semantics only)
- Failed task auto-retry
- User / department permission isolation
- Windows Runner (windows commands are stored, not executed)

---

## Task 1: Module skeleton, SQLAlchemy models, initial migration

**Files:**
- Create: `custom/command_scheduler/__init__.py`
- Create: `custom/command_scheduler/db.py` (session factory + Base re-export)
- Create: `custom/command_scheduler/models.py` (SQLAlchemy ORM + Pydantic schemas)
- Create: `custom/command_scheduler/migrations/__init__.py`
- Create: `custom/command_scheduler/migrations/001_initial.sql`

Follow the pattern in `custom/scheduled_tasks/models.py` closely: co-locate SQLAlchemy and Pydantic.

- [ ] **Step 1: Create empty package marker**

```python
# custom/command_scheduler/__init__.py
"""HiClaw Command Scheduler — shell-command scheduling with sandbox execution."""
```

- [ ] **Step 2: Create `db.py` that re-exports the shared session factory**

```python
# custom/command_scheduler/db.py
"""Thin wrapper that gives command_scheduler its own session factory
alias. Backed by the same openhands.db SQLite used by scheduled_tasks,
so tables live side-by-side.
"""
from __future__ import annotations

# Reuse the same agent_mgmt DB machinery — it's the one that already
# knows where ~/.openhands/openhands.db lives and how to hand out
# AsyncSessions.
from custom.agent_mgmt.db import get_agent_db as get_cs_db  # noqa: F401
```

- [ ] **Step 3: Create `models.py` with SQLAlchemy ORM classes**

```python
# custom/command_scheduler/models.py
"""SQLAlchemy models + Pydantic schemas for the command scheduler.

Three tables:
- command_schedules:  one row per scheduled shell command
- command_fires:      one row per fire attempt (including skipped)
- holidays:           preset + user-defined holidays and makeup workdays
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, func
from sqlalchemy import UUID as SQLUUID

from openhands.app_server.utils.sql_utils import Base, UtcDateTime


# ─── SQLAlchemy ORM ──────────────────────────────────────────────────

ScheduleKind = Literal["one_time", "daily", "weekly", "monthly", "yearly"]
HolidayPolicy = Literal["normal", "skip", "run_before", "run_after"]
ShellKind = Literal["linux", "windows"]
EnvTag = Literal["formal", "test"]
FireStatus = Literal["running", "success", "failed", "timeout", "skipped"]
TriggerSource = Literal["scheduled", "manual"]


class StoredCommandSchedule(Base):  # type: ignore
    __tablename__ = "command_schedules"

    id = Column(SQLUUID, primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    env_tag = Column(String, nullable=False, server_default="formal")
    shell_kind = Column(String, nullable=False, server_default="linux")
    kind = Column(String, nullable=False)
    cron_expr = Column(String, nullable=True)
    run_at = Column(UtcDateTime, nullable=True)
    command = Column(Text, nullable=False)
    working_dir = Column(String, nullable=True)
    max_duration_sec = Column(Integer, nullable=False, server_default="300")
    holiday_policy = Column(String, nullable=False, server_default="normal")
    log_path = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, server_default="1", index=True)
    created_at = Column(UtcDateTime, server_default=func.now())
    updated_at = Column(UtcDateTime, server_default=func.now())
    last_fire_at = Column(UtcDateTime, nullable=True)
    next_fire_at = Column(UtcDateTime, nullable=True)


class StoredCommandFire(Base):  # type: ignore
    __tablename__ = "command_fires"

    id = Column(SQLUUID, primary_key=True, default=uuid4)
    schedule_id = Column(
        SQLUUID,
        ForeignKey("command_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at = Column(UtcDateTime, server_default=func.now(), index=True)
    completed_at = Column(UtcDateTime, nullable=True)
    status = Column(String, nullable=False, server_default="running")
    skip_reason = Column(String, nullable=True)
    exit_code = Column(Integer, nullable=True)
    stdout_tail = Column(Text, nullable=True)
    stderr_tail = Column(Text, nullable=True)
    log_file_path = Column(String, nullable=True)
    trigger_source = Column(String, nullable=False, server_default="scheduled")


class StoredHoliday(Base):  # type: ignore
    __tablename__ = "holidays"

    date = Column(String, primary_key=True)  # YYYY-MM-DD
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # holiday / makeup_workday
    source = Column(String, nullable=False)  # preset / user
    created_at = Column(UtcDateTime, server_default=func.now())


# ─── Pydantic schemas (router I/O) ──────────────────────────────────


class CommandScheduleCreate(BaseModel):
    name: str
    env_tag: EnvTag = "formal"
    shell_kind: ShellKind = "linux"
    kind: ScheduleKind
    cron_expr: str | None = None
    run_at: datetime | None = None
    command: str
    working_dir: str | None = None
    max_duration_sec: int = 300
    holiday_policy: HolidayPolicy = "normal"
    log_path: str | None = None
    enabled: bool = True


class CommandScheduleUpdate(BaseModel):
    name: str | None = None
    env_tag: EnvTag | None = None
    shell_kind: ShellKind | None = None
    kind: ScheduleKind | None = None
    cron_expr: str | None = None
    run_at: datetime | None = None
    command: str | None = None
    working_dir: str | None = None
    max_duration_sec: int | None = None
    holiday_policy: HolidayPolicy | None = None
    log_path: str | None = None
    enabled: bool | None = None


class CommandScheduleInfo(BaseModel):
    id: str
    name: str
    env_tag: EnvTag
    shell_kind: ShellKind
    kind: ScheduleKind
    cron_expr: str | None
    run_at: datetime | None
    command: str
    working_dir: str | None
    max_duration_sec: int
    holiday_policy: HolidayPolicy
    log_path: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_fire_at: datetime | None
    next_fire_at: datetime | None
    schedule_description: str  # human-friendly, e.g., "每天 09:00"


class CommandFireInfo(BaseModel):
    id: str
    schedule_id: str
    started_at: datetime
    completed_at: datetime | None
    status: FireStatus
    skip_reason: str | None
    exit_code: int | None
    stdout_tail: str | None
    stderr_tail: str | None
    log_file_path: str | None
    trigger_source: TriggerSource


class HolidayInfo(BaseModel):
    date: str  # YYYY-MM-DD
    name: str
    kind: Literal["holiday", "makeup_workday"]
    source: Literal["preset", "user"]
    created_at: datetime


class HolidayCheckResult(BaseModel):
    date: str
    is_holiday: bool
    is_makeup_workday: bool
    is_workday: bool
    name: str | None = None
```

- [ ] **Step 3.5: Check that existing scheduled_tasks models are found and tables auto-create via Base.metadata**

Run:
```bash
grep -rn "Base.metadata.create_all\|create_all" /home/wq/workspace/OpenHands/custom/scheduled_tasks/ /home/wq/workspace/OpenHands/custom/agent_mgmt/ | head
```
Expected: there is a central `create_all` somewhere (probably `custom/agent_mgmt/db.py` or server lifespan). If not, the initial migration is handled by SQLAlchemy metadata auto-create since our models use the same `Base`. Document findings in your working notes.

- [ ] **Step 4: Create a plain SQL migration as backup / documentation**

```sql
-- custom/command_scheduler/migrations/001_initial.sql
-- Reference schema for command_scheduler tables.
-- Actual table creation happens via SQLAlchemy Base.metadata at app startup
-- (inherited from the shared Base used by agent_mgmt and scheduled_tasks).
-- This file exists so ops can diff against the live DB schema.

CREATE TABLE IF NOT EXISTS command_schedules (
    id VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    env_tag VARCHAR NOT NULL DEFAULT 'formal',
    shell_kind VARCHAR NOT NULL DEFAULT 'linux',
    kind VARCHAR NOT NULL,
    cron_expr VARCHAR,
    run_at DATETIME,
    command TEXT NOT NULL,
    working_dir VARCHAR,
    max_duration_sec INTEGER NOT NULL DEFAULT 300,
    holiday_policy VARCHAR NOT NULL DEFAULT 'normal',
    log_path VARCHAR,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_fire_at DATETIME,
    next_fire_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_cs_enabled ON command_schedules(enabled);

CREATE TABLE IF NOT EXISTS command_fires (
    id VARCHAR NOT NULL PRIMARY KEY,
    schedule_id VARCHAR NOT NULL,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    status VARCHAR NOT NULL DEFAULT 'running',
    skip_reason VARCHAR,
    exit_code INTEGER,
    stdout_tail TEXT,
    stderr_tail TEXT,
    log_file_path VARCHAR,
    trigger_source VARCHAR NOT NULL DEFAULT 'scheduled',
    FOREIGN KEY (schedule_id) REFERENCES command_schedules(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cf_schedule_id ON command_fires(schedule_id);
CREATE INDEX IF NOT EXISTS idx_cf_started_at ON command_fires(started_at);

CREATE TABLE IF NOT EXISTS holidays (
    date VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 5: Syntax-check imports**

```bash
cd /home/wq/workspace/OpenHands
.venv/bin/python -c "from custom.command_scheduler.models import (
    StoredCommandSchedule, StoredCommandFire, StoredHoliday,
    CommandScheduleCreate, CommandScheduleInfo, CommandFireInfo,
    HolidayInfo, HolidayCheckResult,
); print('imports ok')"
```
Expected: `imports ok`

- [ ] **Step 6: Commit**

```bash
git add custom/command_scheduler/__init__.py custom/command_scheduler/db.py \
        custom/command_scheduler/models.py custom/command_scheduler/migrations/
git commit -m "feat(cs): module skeleton + SQLAlchemy/Pydantic models"
```

---

## Task 2: Preset holiday YAML + HolidayService + preset loader

**Files:**
- Create: `custom/command_scheduler/data/__init__.py`
- Create: `custom/command_scheduler/data/holidays_cn_2026.yaml`
- Create: `custom/command_scheduler/data/holidays_cn_2027.yaml`
- Create: `custom/command_scheduler/holidays.py`

- [ ] **Step 1: Create 2026 holidays YAML from State Council data**

```yaml
# custom/command_scheduler/data/holidays_cn_2026.yaml
year: 2026
holidays:
  - {date: "2026-01-01", name: "元旦"}
  - {date: "2026-02-16", name: "春节"}
  - {date: "2026-02-17", name: "春节"}
  - {date: "2026-02-18", name: "春节"}
  - {date: "2026-02-19", name: "春节"}
  - {date: "2026-02-20", name: "春节"}
  - {date: "2026-02-21", name: "春节"}
  - {date: "2026-02-22", name: "春节"}
  - {date: "2026-04-04", name: "清明节"}
  - {date: "2026-04-05", name: "清明节"}
  - {date: "2026-04-06", name: "清明节"}
  - {date: "2026-05-01", name: "劳动节"}
  - {date: "2026-05-02", name: "劳动节"}
  - {date: "2026-05-03", name: "劳动节"}
  - {date: "2026-05-04", name: "劳动节"}
  - {date: "2026-05-05", name: "劳动节"}
  - {date: "2026-06-19", name: "端午节"}
  - {date: "2026-06-20", name: "端午节"}
  - {date: "2026-06-21", name: "端午节"}
  - {date: "2026-09-25", name: "中秋节"}
  - {date: "2026-09-26", name: "中秋节"}
  - {date: "2026-09-27", name: "中秋节"}
  - {date: "2026-10-01", name: "国庆节"}
  - {date: "2026-10-02", name: "国庆节"}
  - {date: "2026-10-03", name: "国庆节"}
  - {date: "2026-10-04", name: "国庆节"}
  - {date: "2026-10-05", name: "国庆节"}
  - {date: "2026-10-06", name: "国庆节"}
  - {date: "2026-10-07", name: "国庆节"}
  - {date: "2026-10-08", name: "国庆节"}
makeup_workdays:
  - {date: "2026-02-14", name: "春节调休上班"}
  - {date: "2026-02-28", name: "春节调休上班"}
  - {date: "2026-09-19", name: "中秋调休上班"}
  - {date: "2026-10-10", name: "国庆调休上班"}
```

> **Note:** Verify these dates against the latest State Council announcement when filing — the dates above are placeholders if 2026 has not been officially published yet. Document deltas in the commit message.

- [ ] **Step 2: Create 2027 holidays YAML**

```yaml
# custom/command_scheduler/data/holidays_cn_2027.yaml
year: 2027
holidays: []
makeup_workdays: []
# Fill in once the State Council publishes the 2027 calendar.
```

- [ ] **Step 3: Implement HolidayService with preset loader**

```python
# custom/command_scheduler/holidays.py
"""Holiday lookup service: preset data + user additions.

On first use the service loads all bundled
``custom/command_scheduler/data/holidays_cn_*.yaml`` files and upserts
their entries into the ``holidays`` table with ``source='preset'``.
User-added rows (``source='user'``) are left untouched.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from custom.command_scheduler.models import StoredHoliday, HolidayInfo, HolidayCheckResult

_logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"
_PRESET_SYNCED = False


async def sync_preset_holidays(db: AsyncSession) -> int:
    """Read all holidays_cn_*.yaml and upsert into the holidays table.

    Idempotent — can be called every startup. Returns number of preset
    rows upserted. Doesn't touch source='user' rows.
    """
    global _PRESET_SYNCED
    count = 0
    for yaml_path in sorted(_DATA_DIR.glob("holidays_cn_*.yaml")):
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("holidays") or []:
            await _upsert_preset(db, entry["date"], entry["name"], "holiday")
            count += 1
        for entry in data.get("makeup_workdays") or []:
            await _upsert_preset(db, entry["date"], entry["name"], "makeup_workday")
            count += 1
    await db.commit()
    _PRESET_SYNCED = True
    _logger.info("command_scheduler: synced %d preset holiday rows", count)
    return count


async def _upsert_preset(db: AsyncSession, d: str, name: str, kind: str) -> None:
    existing = await db.get(StoredHoliday, d)
    if existing is None:
        db.add(StoredHoliday(date=d, name=name, kind=kind, source="preset"))
    elif existing.source == "preset":
        existing.name = name
        existing.kind = kind


class HolidayService:
    """Query and mutate the holidays table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_year(self, year: int) -> list[HolidayInfo]:
        prefix = f"{year:04d}-"
        stmt = (
            select(StoredHoliday)
            .where(StoredHoliday.date.like(f"{prefix}%"))
            .order_by(StoredHoliday.date)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_info(r) for r in rows]

    async def add_user_holiday(self, d: str, name: str, kind: str) -> HolidayInfo:
        existing = await self.db.get(StoredHoliday, d)
        if existing is not None:
            raise ValueError(f"date {d} already exists (source={existing.source})")
        row = StoredHoliday(date=d, name=name, kind=kind, source="user")
        self.db.add(row)
        await self.db.commit()
        return self._row_to_info(row)

    async def delete_user_holiday(self, d: str) -> None:
        existing = await self.db.get(StoredHoliday, d)
        if existing is None:
            return
        if existing.source != "user":
            raise ValueError(f"cannot delete preset row {d}")
        await self.db.execute(delete(StoredHoliday).where(StoredHoliday.date == d))
        await self.db.commit()

    async def check_date(self, d: str) -> HolidayCheckResult:
        row = await self.db.get(StoredHoliday, d)
        if row is None:
            return HolidayCheckResult(
                date=d,
                is_holiday=_is_weekend(d),
                is_makeup_workday=False,
                is_workday=not _is_weekend(d),
                name=None,
            )
        is_holiday = row.kind == "holiday"
        is_makeup = row.kind == "makeup_workday"
        return HolidayCheckResult(
            date=d,
            is_holiday=is_holiday,
            is_makeup_workday=is_makeup,
            is_workday=is_makeup or (not is_holiday and not _is_weekend(d)),
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
        dt = datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return False
    return dt.weekday() >= 5
```

- [ ] **Step 4: Smoke-test the YAML loader standalone**

```bash
cd /home/wq/workspace/OpenHands
.venv/bin/python -c "
import yaml, pathlib
for p in sorted(pathlib.Path('custom/command_scheduler/data').glob('holidays_cn_*.yaml')):
    d = yaml.safe_load(p.read_text())
    print(p.name, 'holidays=', len(d.get('holidays') or []), 'makeup=', len(d.get('makeup_workdays') or []))
"
```
Expected: prints row counts for each file, no YAML errors.

- [ ] **Step 5: Commit**

```bash
git add custom/command_scheduler/holidays.py custom/command_scheduler/data/
git commit -m "feat(cs): holiday service + preset 2026/2027 data loader"
```

---

## Task 3: CommandScheduleService (CRUD) + schedule_description helper

**Files:**
- Create: `custom/command_scheduler/cron_util.py`
- Create: `custom/command_scheduler/service.py`

- [ ] **Step 1: Create cron_util for kind→trigger + human description**

```python
# custom/command_scheduler/cron_util.py
"""Convert friendly schedule kinds into APScheduler triggers.

Shapes supported (P1):
  kind="one_time", run_at=datetime  →  DateTrigger
  kind="daily",    cron_expr="M H * * *"
  kind="weekly",   cron_expr="M H * * D,D,D"
  kind="monthly",  cron_expr="M H D * *"
  kind="yearly",   cron_expr="M H D MO *"   (month first then day)

For daily/weekly/monthly/yearly we store the full crontab string in
cron_expr and parse it with CronTrigger.from_crontab, which gives
users the full cron flexibility even though the UI picker only
exposes the friendly fields.
"""

from __future__ import annotations

from datetime import datetime

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from custom.command_scheduler.models import ScheduleKind


class InvalidScheduleError(ValueError):
    pass


def build_trigger(kind: ScheduleKind, cron_expr: str | None, run_at: datetime | None):
    if kind == "one_time":
        if run_at is None:
            raise InvalidScheduleError("one_time requires run_at")
        return DateTrigger(run_date=run_at, timezone="Asia/Shanghai")
    if cron_expr is None:
        raise InvalidScheduleError(f"{kind} requires cron_expr")
    try:
        return CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai")
    except Exception as e:
        raise InvalidScheduleError(f"bad cron expression {cron_expr!r}: {e}")


def describe(kind: ScheduleKind, cron_expr: str | None, run_at: datetime | None) -> str:
    """Return a Chinese human-friendly description for the UI."""
    if kind == "one_time":
        if run_at is None:
            return "一次性"
        return f"一次性 · {run_at.strftime('%Y-%m-%d %H:%M')}"
    if cron_expr is None:
        return str(kind)
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    m, h, dom, mon, dow = parts
    hm = f"{h.zfill(2)}:{m.zfill(2)}"
    if kind == "daily":
        return f"每天 {hm}"
    if kind == "weekly":
        return f"每周 {dow} · {hm}"
    if kind == "monthly":
        return f"每月 {dom} 号 · {hm}"
    if kind == "yearly":
        return f"每年 {mon} 月 {dom} 日 · {hm}"
    return cron_expr
```

- [ ] **Step 2: Create CommandScheduleService**

```python
# custom/command_scheduler/service.py
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
    return str(v).replace("-", "")


def _to_uuid(v: Any) -> UUID:
    if isinstance(v, UUID):
        return v
    s = str(v)
    try:
        return UUID(s)
    except ValueError:
        return UUID(s.replace("-", ""))


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
            stmt = stmt.where(StoredCommandSchedule.name.ilike(f"%{q}%"))
        stmt = stmt.order_by(desc(StoredCommandSchedule.created_at))
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_info(r) for r in rows]

    async def get_schedule(self, schedule_id: str) -> CommandScheduleInfo | None:
        row = await self.db.get(StoredCommandSchedule, _to_uuid(schedule_id))
        if row is None:
            return None
        return self._row_to_info(row)

    async def create_schedule(self, payload: CommandScheduleCreate) -> CommandScheduleInfo:
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
        if "run_at" in data:
            data["run_at"] = _to_naive_utc(data["run_at"])
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
            StoredCommandSchedule.enabled == True  # noqa: E712
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            row.enabled = False
        await self.db.commit()
        return len(rows)

    async def resume_all(self) -> int:
        stmt = select(StoredCommandSchedule).where(
            StoredCommandSchedule.enabled == False  # noqa: E712
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            row.enabled = True
        await self.db.commit()
        return len(rows)

    async def count_status(self) -> dict[str, int]:
        """Return {"total": n, "running": n, "enabled": n, "disabled": n} for the stats bar."""
        total_stmt = select(func.count(StoredCommandSchedule.id))
        enabled_stmt = select(func.count(StoredCommandSchedule.id)).where(
            StoredCommandSchedule.enabled == True  # noqa: E712
        )
        running_stmt = select(func.count(StoredCommandFire.id)).where(
            StoredCommandFire.status == "running"
        )
        total = (await self.db.execute(total_stmt)).scalar() or 0
        enabled = (await self.db.execute(enabled_stmt)).scalar() or 0
        running = (await self.db.execute(running_stmt)).scalar() or 0
        return {
            "total": total,
            "running": running,
            "enabled": enabled,
            "disabled": total - enabled,
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
        trigger_source: str = "scheduled",
    ) -> CommandFireInfo:
        row = StoredCommandFire(
            id=uuid4(),
            schedule_id=_to_uuid(schedule_id),
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="running",
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

    async def has_running_fire(self, schedule_id: str) -> bool:
        stmt = select(StoredCommandFire).where(
            StoredCommandFire.schedule_id == _to_uuid(schedule_id),
            StoredCommandFire.status == "running",
        )
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None

    # ─── Row → Info ───────────────────────────────────────────────

    def _row_to_info(self, row: StoredCommandSchedule) -> CommandScheduleInfo:
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


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
```

- [ ] **Step 3: Import-check**

```bash
.venv/bin/python -c "
from custom.command_scheduler.service import CommandScheduleService
from custom.command_scheduler.cron_util import build_trigger, describe, InvalidScheduleError
print('ok')
"
```
Expected: `ok`

- [ ] **Step 4: Pure-function test for describe()**

```bash
.venv/bin/python -c "
from custom.command_scheduler.cron_util import describe
from datetime import datetime
assert describe('daily', '0 9 * * *', None) == '每天 09:00'
assert describe('weekly', '30 18 * * 1,3,5', None).startswith('每周')
assert describe('monthly', '0 0 1 * *', None).startswith('每月 1 号')
assert describe('yearly', '0 0 1 1 *', None).startswith('每年')
assert describe('one_time', None, datetime(2026, 5, 1, 9, 0)) == '一次性 · 2026-05-01 09:00'
print('describe tests pass')
"
```
Expected: `describe tests pass`

- [ ] **Step 5: Commit**

```bash
git add custom/command_scheduler/cron_util.py custom/command_scheduler/service.py
git commit -m "feat(cs): CRUD service + cron util + human description"
```

---

## Task 4: Log I/O helpers

**Files:**
- Create: `custom/command_scheduler/log_io.py`

- [ ] **Step 1: Implement tail + full log writer + cleanup**

```python
# custom/command_scheduler/log_io.py
"""Command output log I/O.

Two sinks per fire:
- DB tail: last ~200 lines, capped at 32 KB, stored on the fire row
- File: full output at ~/.openhands/command_scheduler/logs/{sched}/{fire}.log
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

_logger = logging.getLogger(__name__)

LOG_ROOT = Path.home() / ".openhands" / "command_scheduler" / "logs"
MAX_TAIL_LINES = 200
MAX_TAIL_BYTES = 32 * 1024


def ensure_log_root() -> Path:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    return LOG_ROOT


def log_file_for(schedule_id: str, fire_id: str) -> Path:
    d = LOG_ROOT / schedule_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{fire_id}.log"


def write_full_log(
    schedule_id: str,
    fire_id: str,
    stdout: str,
    stderr: str,
    started_at: datetime,
    completed_at: datetime | None,
    exit_code: int | None,
) -> Path:
    ensure_log_root()
    p = log_file_for(schedule_id, fire_id)
    start_s = started_at.isoformat()
    end_s = completed_at.isoformat() if completed_at else "(not completed)"
    with p.open("w", encoding="utf-8") as f:
        f.write(f"=== STARTED {start_s} ===\n[stdout]\n{stdout}\n[stderr]\n{stderr}\n")
        f.write(f"=== COMPLETED {end_s} exit={exit_code} ===\n")
    return p


def tail_bytes_and_lines(text: str) -> str:
    if not text:
        return ""
    if len(text.encode("utf-8")) > MAX_TAIL_BYTES:
        text = text[-MAX_TAIL_BYTES:]
    lines = text.splitlines()
    if len(lines) > MAX_TAIL_LINES:
        lines = lines[-MAX_TAIL_LINES:]
    return "\n".join(lines)


def cleanup_old_logs(retention_days: int = 30) -> int:
    """Delete log files older than retention_days. Returns deleted count."""
    ensure_log_root()
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0
    for p in LOG_ROOT.rglob("*.log"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                p.unlink()
                deleted += 1
        except FileNotFoundError:
            continue
        except Exception as e:
            _logger.warning("log cleanup failed for %s: %s", p, e)
    return deleted
```

- [ ] **Step 2: Pure-function test**

```bash
.venv/bin/python -c "
from custom.command_scheduler.log_io import tail_bytes_and_lines
# short input — returned as-is
assert tail_bytes_and_lines('hello\nworld') == 'hello\nworld'
# long input — clipped to ~200 lines
big = '\n'.join(f'line{i}' for i in range(500))
out = tail_bytes_and_lines(big)
assert out.count('\n') <= 200
assert out.endswith('line499')
print('log_io tests pass')
"
```
Expected: `log_io tests pass`

- [ ] **Step 3: Commit**

```bash
git add custom/command_scheduler/log_io.py
git commit -m "feat(cs): log tail + full-log writer + retention cleanup"
```

---

## Task 5: Executor (subprocess path first — sandbox plugged in Task 7)

**Files:**
- Create: `custom/command_scheduler/executor.py`

Build the executor with a pluggable command runner. P1 starts with a plain subprocess runner to prove the pipeline; Task 7 swaps in the real HiClaw Process sandbox.

- [ ] **Step 1: Implement the executor skeleton**

```python
# custom/command_scheduler/executor.py
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
    trigger_source: str = "scheduled",
) -> str:
    """Dispatch one fire for `schedule`. Returns the fire_id."""
    svc = CommandScheduleService(db)
    fire = await svc.create_fire(schedule.id, trigger_source=trigger_source)

    # ── Pre-flight skips ──
    if await svc.has_running_fire_excluding(schedule.id, fire.id):
        await _mark_skipped(svc, fire.id, "prev_running")
        return fire.id

    if schedule.shell_kind == "windows":
        await _mark_skipped(svc, fire.id, "windows_not_supported")
        return fire.id

    hsvc = HolidayService(db)
    today = date.today().isoformat()
    if not await _should_run_today(schedule.holiday_policy, today, hsvc):
        await _mark_skipped(svc, fire.id, "holiday_skip")
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
            status="timeout",
            stderr_tail=f"exceeded max_duration_sec={schedule.max_duration_sec}",
            completed=True,
        )
        return fire.id
    except Exception as e:
        _logger.exception("command_scheduler executor crashed for %s", schedule.id)
        await svc.update_fire(
            fire.id,
            status="failed",
            stderr_tail=f"{type(e).__name__}: {e}",
            completed=True,
        )
        return fire.id

    completed = datetime.now(timezone.utc).replace(tzinfo=None)
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
    except Exception as e:
        _logger.warning("write_full_log failed: %s", e)
        log_path = None

    await svc.update_fire(
        fire.id,
        status="success" if result.exit_code == 0 else "failed",
        exit_code=result.exit_code,
        stdout_tail=tail_bytes_and_lines(result.stdout),
        stderr_tail=tail_bytes_and_lines(result.stderr),
        log_file_path=str(log_path) if log_path else None,
        completed=True,
    )
    return fire.id


async def _mark_skipped(svc: CommandScheduleService, fire_id: str, reason: str) -> None:
    await svc.update_fire(
        fire_id,
        status="skipped",
        skip_reason=reason,
        completed=True,
    )


async def _should_run_today(
    policy: HolidayPolicy, today: str, hsvc: HolidayService
) -> bool:
    if policy == "normal":
        return True
    check = await hsvc.check_date(today)
    if policy == "skip":
        return not check.is_holiday
    # P1 simple semantics: run_before / run_after only skip on the holiday day.
    # The "advance one workday" compensation is a P2 scanner job.
    return not check.is_holiday
```

- [ ] **Step 2: Add `has_running_fire_excluding` helper to service.py**

```python
# Add to CommandScheduleService:
    async def has_running_fire_excluding(self, schedule_id: str, fire_id: str) -> bool:
        stmt = select(StoredCommandFire).where(
            StoredCommandFire.schedule_id == _to_uuid(schedule_id),
            StoredCommandFire.status == "running",
            StoredCommandFire.id != _to_uuid(fire_id),
        )
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None
```

- [ ] **Step 3: Create a simple subprocess runner for P1 testing**

```python
# custom/command_scheduler/runners.py
"""Pluggable command runners.

P1a: subprocess runner — for local testing + as fallback
P1b: sandbox runner — added in Task 7
"""

from __future__ import annotations

import asyncio

from custom.command_scheduler.executor import RunResult


async def subprocess_runner(
    command: str, working_dir: str | None, timeout_sec: int
) -> RunResult:
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        raise TimeoutError(f"command timed out after {timeout_sec}s")
    return RunResult(
        exit_code=proc.returncode or 0,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
    )
```

- [ ] **Step 4: Import-check**

```bash
.venv/bin/python -c "
from custom.command_scheduler.executor import execute, RunResult
from custom.command_scheduler.runners import subprocess_runner
print('ok')
"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add custom/command_scheduler/executor.py custom/command_scheduler/runners.py custom/command_scheduler/service.py
git commit -m "feat(cs): executor pipeline + subprocess runner"
```

---

## Task 6: Shared APScheduler integration

**Files:**
- Modify: `custom/scheduled_tasks/scheduler.py` (add public `get_shared_scheduler()`)
- Create: `custom/command_scheduler/scheduler_integration.py`

- [ ] **Step 1: Expose public scheduler accessor in scheduled_tasks**

In `custom/scheduled_tasks/scheduler.py`, add **below** the existing `_get_scheduler` function:

```python
def get_shared_scheduler() -> AsyncIOScheduler:
    """Public accessor for the shared HiClaw AsyncIOScheduler instance.

    Used by other custom modules (e.g. command_scheduler) that want to
    register their own APScheduler jobs onto the same instance so we
    only have one event loop to manage.
    """
    return _get_scheduler()
```

- [ ] **Step 2: Create scheduler_integration.py**

```python
# custom/command_scheduler/scheduler_integration.py
"""Register command_scheduler jobs onto the shared AsyncIOScheduler.

Expects that `custom.scheduled_tasks.scheduler.start()` has already
been called (which owns the actual `scheduler.start()` invocation).
If this module's `init()` runs before that, jobs are still added to
the AsyncIOScheduler instance and will become active once start()
runs — APScheduler supports adding jobs to a not-yet-running
scheduler.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any

from apscheduler.jobstores.base import JobLookupError

from custom.command_scheduler.cron_util import build_trigger
from custom.command_scheduler.models import CommandScheduleInfo
from custom.command_scheduler.service import CommandScheduleService
from custom.command_scheduler.db import get_cs_db
from custom.scheduled_tasks.scheduler import get_shared_scheduler

_logger = logging.getLogger(__name__)

_JOB_PREFIX = "cs:"
_CLEANUP_JOB_ID = "cs:cleanup-logs"


def _job_id(schedule_id: str) -> str:
    return f"{_JOB_PREFIX}{schedule_id}"


async def init() -> None:
    """Load all enabled command schedules from DB and register jobs.

    Also registers the daily cleanup job.
    """
    sched = get_shared_scheduler()
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
                "command_scheduler: failed to register schedule %s at startup",
                row.id,
            )
    _logger.info("command_scheduler: loaded %d enabled schedules", loaded)

    _register_cleanup_job()
    await _refresh_next_fire_at_column()


def _register(schedule: CommandScheduleInfo) -> None:
    from custom.command_scheduler.fire import fire_command_schedule  # lazy

    sched = get_shared_scheduler()
    trigger = build_trigger(schedule.kind, schedule.cron_expr, schedule.run_at)
    sched.add_job(
        fire_command_schedule,
        trigger=trigger,
        args=[schedule.id],
        id=_job_id(schedule.id),
        name=f"cs:{schedule.name}",
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

    async def _cleanup():
        try:
            n = cleanup_old_logs(retention_days=30)
            _logger.info("command_scheduler cleanup: deleted %d old log files", n)
        except Exception:
            _logger.exception("command_scheduler cleanup job crashed")

    sched.add_job(
        _cleanup,
        trigger=CronTrigger.from_crontab("0 3 * * *", timezone="Asia/Shanghai"),
        id=_CLEANUP_JOB_ID,
        name="cs:cleanup-old-logs",
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
```

- [ ] **Step 3: Create the `fire_command_schedule` entry point**

```python
# custom/command_scheduler/fire.py
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
            _logger.warning("fire_command_schedule: schedule %s not found", schedule_id)
            return
        # P1: use subprocess_runner; Task 7 will swap in the sandbox runner.
        await execute(schedule, db, subprocess_runner, trigger_source="scheduled")
    finally:
        await db.close()

    # Sync next_fire_at back into DB for the list page
    try:
        from custom.command_scheduler.scheduler_integration import sync_next_fire_at
        await sync_next_fire_at()
    except Exception:
        _logger.exception("failed to sync next_fire_at after fire")
```

- [ ] **Step 4: Import-check**

```bash
.venv/bin/python -c "
from custom.command_scheduler.scheduler_integration import (
    init, register_schedule, unregister_schedule, reschedule, get_next_fire_at,
)
from custom.command_scheduler.fire import fire_command_schedule
print('ok')
"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add custom/scheduled_tasks/scheduler.py \
        custom/command_scheduler/scheduler_integration.py \
        custom/command_scheduler/fire.py
git commit -m "feat(cs): shared APScheduler integration + fire entry point"
```

---

## Task 7: Sandbox manager + swap runner

**Files:**
- Create: `custom/command_scheduler/sandbox_manager.py`
- Modify: `custom/command_scheduler/runners.py` (add sandbox runner)
- Modify: `custom/command_scheduler/fire.py` (use sandbox runner, fall back to subprocess)

> **Heads up:** The HiClaw Process sandbox API is the part of this plan most likely to need adjustment. Before writing the sandbox_manager, read `openhands/app_server/sandbox/process_sandbox_service.py` and pick whichever exec primitive is already exposed (`start_sandbox`, `exec_command`, or similar). Adjust the calls below to match.

- [ ] **Step 1: Read ProcessSandboxService to understand its API**

```bash
grep -n "async def\|def __init__\|class " /home/wq/workspace/OpenHands/openhands/app_server/sandbox/process_sandbox_service.py | head -40
```
Document the method names and expected arguments in a comment at the top of `sandbox_manager.py`.

- [ ] **Step 2: Implement `sandbox_manager.py`**

```python
# custom/command_scheduler/sandbox_manager.py
"""Lazy lifecycle wrapper for the command_scheduler's shared Process sandbox.

Single instance with id = "cmd-scheduler". Lazy-started on first use,
re-started if it enters ERROR state. venv provisioning runs once,
guarded by a marker file.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

SANDBOX_ID = "cmd-scheduler"
WORKSPACE_ROOT = Path("/opt/hiclaw/command_scheduler/workspace")
VENV_ROOT = Path("/opt/hiclaw/command_scheduler/venv")
PROVISIONED_MARKER = VENV_ROOT / ".provisioned"

PROVISION_CMD = (
    f"python -m venv {VENV_ROOT} && "
    f"{VENV_ROOT}/bin/pip install --no-cache-dir "
    f"requests httpx python-dateutil pyyaml openpyxl pandas && "
    f"mkdir -p {WORKSPACE_ROOT} && "
    f"touch {PROVISIONED_MARKER}"
)

_startup_lock = asyncio.Lock()
_sandbox_ref: Any = None  # holds the ProcessSandboxInfo or equivalent


async def get_or_start_sandbox() -> Any:
    """Return the running sandbox, lazy-starting if necessary."""
    global _sandbox_ref
    async with _startup_lock:
        if _sandbox_ref is not None and await _is_healthy(_sandbox_ref):
            return _sandbox_ref
        _sandbox_ref = await _start()
        if not PROVISIONED_MARKER.exists():
            await _provision(_sandbox_ref)
        return _sandbox_ref


async def _start() -> Any:
    # TODO (Task 7 impl): call ProcessSandboxService.start_sandbox(sandbox_id=SANDBOX_ID)
    # using the HiClaw DI container. Exact call site depends on whether we
    # can reach the service from here or need a thin factory passed in.
    raise NotImplementedError("wire this up to ProcessSandboxService")


async def _is_healthy(sbox: Any) -> bool:
    # TODO: poll sandbox.status; return True if RUNNING
    return False


async def _provision(sbox: Any) -> None:
    _logger.info("command_scheduler: provisioning venv…")
    # TODO: run PROVISION_CMD inside the sandbox via exec_command
    raise NotImplementedError("run PROVISION_CMD inside the sandbox")


async def exec_in_sandbox(
    command: str, working_dir: str | None, timeout_sec: int
) -> tuple[int, str, str]:
    """Run a command inside the scheduler sandbox. Returns (exit_code, stdout, stderr)."""
    sbox = await get_or_start_sandbox()
    # TODO: await sbox.exec_command(cmd, cwd=working_dir, timeout=timeout_sec)
    raise NotImplementedError("wire exec_command")
```

- [ ] **Step 3: Add sandbox runner to `runners.py`**

Append:

```python
async def sandbox_runner(
    command: str, working_dir: str | None, timeout_sec: int
) -> RunResult:
    from custom.command_scheduler.sandbox_manager import exec_in_sandbox

    exit_code, stdout, stderr = await exec_in_sandbox(
        command, working_dir, timeout_sec
    )
    return RunResult(exit_code=exit_code, stdout=stdout, stderr=stderr)
```

- [ ] **Step 4: Update fire.py with fallback logic**

```python
# Replace the execute() call in fire_command_schedule with:

from custom.command_scheduler.runners import subprocess_runner, sandbox_runner

async def _run_with_fallback(schedule, db):
    try:
        return await execute(schedule, db, sandbox_runner, trigger_source="scheduled")
    except NotImplementedError:
        # Sandbox wiring not complete yet — degrade to subprocess.
        _logger.warning("command_scheduler: sandbox not ready, using subprocess")
        return await execute(schedule, db, subprocess_runner, trigger_source="scheduled")
```

And call `await _run_with_fallback(schedule, db)` in place of the direct `execute(...)` call.

- [ ] **Step 5: Implement the three TODO methods**

This step is where you have to actually wire ProcessSandboxService. Rough shape — adjust for the real API:

```python
# In sandbox_manager.py replace the NotImplementedError stubs:

from openhands.app_server.sandbox.process_sandbox_service import ProcessSandboxService

_svc_singleton: ProcessSandboxService | None = None


def _svc() -> ProcessSandboxService:
    global _svc_singleton
    if _svc_singleton is None:
        _svc_singleton = ProcessSandboxService()
    return _svc_singleton


async def _start() -> Any:
    svc = _svc()
    # Try to find an existing one first
    sbox = await svc.get_sandbox(SANDBOX_ID)
    if sbox is not None:
        _logger.info("command_scheduler: reusing existing sandbox %s", SANDBOX_ID)
        return sbox
    _logger.info("command_scheduler: starting new sandbox %s", SANDBOX_ID)
    return await svc.start_sandbox(sandbox_id=SANDBOX_ID)


async def _is_healthy(sbox: Any) -> bool:
    if sbox is None:
        return False
    status = getattr(sbox, "status", None)
    return str(status) in ("RUNNING", "running")


async def _provision(sbox: Any) -> None:
    # assume ProcessSandboxService exposes exec_command(sandbox_id, cmd, ...)
    svc = _svc()
    _logger.info("command_scheduler: provisioning venv (%s)…", VENV_ROOT)
    result = await svc.exec_command(
        SANDBOX_ID,
        PROVISION_CMD,
        cwd=None,
        timeout=600,
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"provision failed exit={result.exit_code}: {result.stderr[:500]}"
        )


async def exec_in_sandbox(
    command: str, working_dir: str | None, timeout_sec: int
) -> tuple[int, str, str]:
    sbox = await get_or_start_sandbox()
    svc = _svc()
    result = await svc.exec_command(
        SANDBOX_ID,
        command,
        cwd=working_dir or str(WORKSPACE_ROOT),
        timeout=timeout_sec,
    )
    return result.exit_code, result.stdout, result.stderr
```

> **If the real ProcessSandboxService API differs** (e.g., needs a `user_context`, or `exec_command` isn't a public method), adjust this file but keep the public contract of `exec_in_sandbox`. If it's not feasible to wire the sandbox at all in P1, leave the `NotImplementedError` stubs — `_run_with_fallback` in fire.py will transparently use subprocess and P1 is still functional.

- [ ] **Step 6: Smoke-test (manual, requires running HiClaw)**

Start HiClaw dev server and create one schedule via the API (after Task 8 adds the router). Until then, skip this step.

- [ ] **Step 7: Commit**

```bash
git add custom/command_scheduler/sandbox_manager.py \
        custom/command_scheduler/runners.py \
        custom/command_scheduler/fire.py
git commit -m "feat(cs): lazy Process sandbox + fallback to subprocess"
```

---

## Task 8: FastAPI router + lifespan wiring

**Files:**
- Create: `custom/command_scheduler/router.py`
- Modify: `openhands/server/app.py` (include router + call `scheduler_integration.init()` in lifespan)

- [ ] **Step 1: Create router.py**

```python
# custom/command_scheduler/router.py
"""FastAPI router for command_scheduler endpoints.

Mounted at /api/v1/command-schedules (schedules CRUD + fires)
and /api/v1/command-scheduler/holidays (holiday management).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from custom.command_scheduler import scheduler_integration
from custom.command_scheduler.cron_util import InvalidScheduleError
from custom.command_scheduler.db import get_cs_db
from custom.command_scheduler.executor import execute
from custom.command_scheduler.holidays import HolidayService, sync_preset_holidays
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

router = APIRouter(tags=["command_scheduler"])


async def _db():
    db = await get_cs_db()
    try:
        yield db
    finally:
        await db.close()


# ─── Schedules ─────────────────────────────────────────────────────

@router.get("/command-schedules", response_model=list[CommandScheduleInfo])
async def list_schedules(
    enabled: bool | None = None,
    env_tag: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(_db),
) -> list[CommandScheduleInfo]:
    return await CommandScheduleService(db).list_schedules(
        enabled=enabled, env_tag=env_tag, q=q
    )


@router.get("/command-schedules/stats")
async def stats(db: AsyncSession = Depends(_db)) -> dict[str, int]:
    return await CommandScheduleService(db).count_status()


@router.get("/command-schedules/{schedule_id}", response_model=CommandScheduleInfo)
async def get_schedule(schedule_id: str, db: AsyncSession = Depends(_db)):
    row = await CommandScheduleService(db).get_schedule(schedule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return row


@router.post("/command-schedules", response_model=CommandScheduleInfo)
async def create_schedule(
    payload: CommandScheduleCreate, db: AsyncSession = Depends(_db)
):
    svc = CommandScheduleService(db)
    try:
        # Validate the schedule shape up front
        from custom.command_scheduler.cron_util import build_trigger
        build_trigger(payload.kind, payload.cron_expr, payload.run_at)
    except InvalidScheduleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    info = await svc.create_schedule(payload)
    scheduler_integration.register_schedule(info)
    await scheduler_integration.sync_next_fire_at()
    return await svc.get_schedule(info.id)


@router.put("/command-schedules/{schedule_id}", response_model=CommandScheduleInfo)
@router.patch("/command-schedules/{schedule_id}", response_model=CommandScheduleInfo)
async def update_schedule(
    schedule_id: str,
    patch: CommandScheduleUpdate,
    db: AsyncSession = Depends(_db),
):
    svc = CommandScheduleService(db)
    info = await svc.update_schedule(schedule_id, patch)
    if info is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    scheduler_integration.reschedule(info)
    await scheduler_integration.sync_next_fire_at()
    return await svc.get_schedule(info.id)


@router.delete("/command-schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, db: AsyncSession = Depends(_db)):
    ok = await CommandScheduleService(db).delete_schedule(schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Schedule not found")
    scheduler_integration.unregister_schedule(schedule_id)
    return {"deleted": True}


@router.post("/command-schedules/{schedule_id}/run")
async def run_now(schedule_id: str, db: AsyncSession = Depends(_db)):
    svc = CommandScheduleService(db)
    schedule = await svc.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    # Use subprocess runner for manual trigger to avoid blocking on sandbox provision
    fire_id = await execute(schedule, db, subprocess_runner, trigger_source="manual")
    return {"fire_id": fire_id}


@router.post("/command-schedules/pause-all")
async def pause_all(db: AsyncSession = Depends(_db)):
    n = await CommandScheduleService(db).pause_all()
    # Best effort: unregister all currently-registered jobs
    svc = CommandScheduleService(db)
    for row in await svc.list_schedules():
        scheduler_integration.unregister_schedule(row.id)
    return {"paused": n}


@router.post("/command-schedules/resume-all")
async def resume_all(db: AsyncSession = Depends(_db)):
    n = await CommandScheduleService(db).resume_all()
    svc = CommandScheduleService(db)
    for row in await svc.list_schedules(enabled=True):
        scheduler_integration.register_schedule(row)
    await scheduler_integration.sync_next_fire_at()
    return {"resumed": n}


@router.get("/command-schedules/{schedule_id}/fires", response_model=list[CommandFireInfo])
async def list_fires(
    schedule_id: str,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(_db),
):
    return await CommandScheduleService(db).list_fires(schedule_id, limit, offset)


@router.get("/command-schedules/fires/{fire_id}", response_model=CommandFireInfo)
async def get_fire(fire_id: str, db: AsyncSession = Depends(_db)):
    row = await CommandScheduleService(db).get_fire(fire_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Fire not found")
    return row


@router.get("/command-schedules/fires/{fire_id}/log")
async def download_fire_log(fire_id: str, db: AsyncSession = Depends(_db)):
    row = await CommandScheduleService(db).get_fire(fire_id)
    if row is None or not row.log_file_path:
        raise HTTPException(status_code=404, detail="Log not found")
    return FileResponse(row.log_file_path, filename=f"{fire_id}.log")


# ─── Holidays ──────────────────────────────────────────────────────

@router.get("/command-scheduler/holidays", response_model=list[HolidayInfo])
async def list_holidays(year: int, db: AsyncSession = Depends(_db)):
    return await HolidayService(db).list_year(year)


@router.post("/command-scheduler/holidays", response_model=HolidayInfo)
async def add_holiday(
    payload: dict, db: AsyncSession = Depends(_db)
):
    try:
        return await HolidayService(db).add_user_holiday(
            payload["date"], payload["name"], payload.get("kind", "holiday")
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/command-scheduler/holidays/{date}")
async def remove_holiday(date: str, db: AsyncSession = Depends(_db)):
    try:
        await HolidayService(db).delete_user_holiday(date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": True}


@router.get("/command-scheduler/holidays/check/{date}", response_model=HolidayCheckResult)
async def check_holiday(date: str, db: AsyncSession = Depends(_db)):
    return await HolidayService(db).check_date(date)
```

- [ ] **Step 2: Wire router + lifespan in `openhands/server/app.py`**

Find the section where `scheduled_tasks.scheduler.start()` is called (around line 198-214). **After** that block, add:

```python
    # >>> CUSTOM: HiClaw — Command Scheduler (independent module, shared AP) <<<
    try:
        from custom.command_scheduler.scheduler_integration import init as _cs_init
        from custom.command_scheduler.holidays import sync_preset_holidays as _cs_sync_holidays
        from custom.command_scheduler.db import get_cs_db as _cs_db_get

        _cs_db = await _cs_db_get()
        try:
            await _cs_sync_holidays(_cs_db)
        finally:
            await _cs_db.close()

        await _cs_init()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"command_scheduler start: {e}")
    # >>> END CUSTOM <<<
```

Find the router include block (around line 276) and add below `_scheduled_tasks_router`:

```python
    from custom.command_scheduler.router import router as _cs_router
    app.include_router(_cs_router, prefix="/api/v1")
```

- [ ] **Step 3: Start HiClaw dev server and curl-test**

```bash
# Restart backend
./start_dev.sh  # or whatever script is used

# Create a daily linux schedule
curl -sS -X POST http://127.0.0.1:12000/api/v1/command-schedules \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "【测试】smoke test",
    "shell_kind": "linux",
    "kind": "daily",
    "cron_expr": "0 9 * * *",
    "command": "echo hello from command scheduler",
    "max_duration_sec": 10
  }' | jq

# List
curl -sS http://127.0.0.1:12000/api/v1/command-schedules | jq

# Stats
curl -sS http://127.0.0.1:12000/api/v1/command-schedules/stats | jq

# Manual run
SCHED_ID=$(curl -sS http://127.0.0.1:12000/api/v1/command-schedules | jq -r '.[0].id')
curl -sS -X POST http://127.0.0.1:12000/api/v1/command-schedules/$SCHED_ID/run | jq

# Fire history
curl -sS http://127.0.0.1:12000/api/v1/command-schedules/$SCHED_ID/fires | jq

# Holiday check
curl -sS http://127.0.0.1:12000/api/v1/command-scheduler/holidays/check/2026-10-01 | jq

# Holiday list
curl -sS "http://127.0.0.1:12000/api/v1/command-scheduler/holidays?year=2026" | jq
```

Expected:
- Create returns a CommandScheduleInfo with `next_fire_at` set to the next 09:00
- List shows the created row
- Stats shows `{"total":1,"running":0,"enabled":1,"disabled":0}`
- Manual run returns `{"fire_id":"..."}`
- Fires list shows one fire with `status=success` and `exit_code=0`
- Holiday check for 2026-10-01 returns `is_holiday=true, name="国庆节"`
- Holiday list for 2026 returns ~30 rows

- [ ] **Step 4: Commit**

```bash
git add custom/command_scheduler/router.py openhands/server/app.py
git commit -m "feat(cs): router + lifespan wiring; backend E2E green"
```

---

## Task 9: Frontend API client + TypeScript types

**Files:**
- Create: `frontend/src/api/custom-skill-service/command-scheduler.api.ts`

- [ ] **Step 1: Write the API client**

```ts
// frontend/src/api/custom-skill-service/command-scheduler.api.ts
// HiClaw — API client for the command scheduler.

export type ScheduleKind = "one_time" | "daily" | "weekly" | "monthly" | "yearly";
export type ShellKind = "linux" | "windows";
export type EnvTag = "formal" | "test";
export type HolidayPolicy = "normal" | "skip" | "run_before" | "run_after";
export type FireStatus =
  | "running"
  | "success"
  | "failed"
  | "timeout"
  | "skipped";
export type TriggerSource = "scheduled" | "manual";

export interface CommandSchedule {
  id: string;
  name: string;
  env_tag: EnvTag;
  shell_kind: ShellKind;
  kind: ScheduleKind;
  cron_expr: string | null;
  run_at: string | null;
  command: string;
  working_dir: string | null;
  max_duration_sec: number;
  holiday_policy: HolidayPolicy;
  log_path: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  last_fire_at: string | null;
  next_fire_at: string | null;
  schedule_description: string;
}

export interface CommandScheduleInput {
  name: string;
  env_tag?: EnvTag;
  shell_kind?: ShellKind;
  kind: ScheduleKind;
  cron_expr?: string | null;
  run_at?: string | null;
  command: string;
  working_dir?: string | null;
  max_duration_sec?: number;
  holiday_policy?: HolidayPolicy;
  log_path?: string | null;
  enabled?: boolean;
}

export interface CommandFire {
  id: string;
  schedule_id: string;
  started_at: string;
  completed_at: string | null;
  status: FireStatus;
  skip_reason: string | null;
  exit_code: number | null;
  stdout_tail: string | null;
  stderr_tail: string | null;
  log_file_path: string | null;
  trigger_source: TriggerSource;
}

export interface Holiday {
  date: string;
  name: string;
  kind: "holiday" | "makeup_workday";
  source: "preset" | "user";
  created_at: string;
}

export interface HolidayCheck {
  date: string;
  is_holiday: boolean;
  is_makeup_workday: boolean;
  is_workday: boolean;
  name: string | null;
}

export interface Stats {
  total: number;
  running: number;
  enabled: number;
  disabled: number;
}

const BASE = "/api/v1/command-schedules";
const HOL = "/api/v1/command-scheduler/holidays";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!resp.ok) throw new Error(`${init?.method || "GET"} ${url} -> ${resp.status}`);
  if (resp.status === 204) return undefined as unknown as T;
  return (await resp.json()) as T;
}

// eslint-disable-next-line import/prefer-default-export
export class CommandSchedulerService {
  static list(params?: { enabled?: boolean; env_tag?: string; q?: string }): Promise<CommandSchedule[]> {
    const qs = new URLSearchParams();
    if (params?.enabled !== undefined) qs.set("enabled", String(params.enabled));
    if (params?.env_tag) qs.set("env_tag", params.env_tag);
    if (params?.q) qs.set("q", params.q);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<CommandSchedule[]>(`${BASE}${suffix}`);
  }
  static get(id: string) { return req<CommandSchedule>(`${BASE}/${id}`); }
  static stats() { return req<Stats>(`${BASE}/stats`); }
  static create(payload: CommandScheduleInput) {
    return req<CommandSchedule>(BASE, { method: "POST", body: JSON.stringify(payload) });
  }
  static update(id: string, payload: Partial<CommandScheduleInput>) {
    return req<CommandSchedule>(`${BASE}/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  }
  static delete(id: string) {
    return req<{ deleted: boolean }>(`${BASE}/${id}`, { method: "DELETE" });
  }
  static run(id: string) {
    return req<{ fire_id: string }>(`${BASE}/${id}/run`, { method: "POST" });
  }
  static pauseAll() { return req<{ paused: number }>(`${BASE}/pause-all`, { method: "POST" }); }
  static resumeAll() { return req<{ resumed: number }>(`${BASE}/resume-all`, { method: "POST" }); }
  static listFires(id: string, limit = 20, offset = 0) {
    return req<CommandFire[]>(`${BASE}/${id}/fires?limit=${limit}&offset=${offset}`);
  }
  static getFire(fireId: string) { return req<CommandFire>(`${BASE}/fires/${fireId}`); }
  static logUrl(fireId: string) { return `${BASE}/fires/${fireId}/log`; }
  // Holidays
  static listHolidays(year: number) { return req<Holiday[]>(`${HOL}?year=${year}`); }
  static addHoliday(payload: { date: string; name: string; kind?: string }) {
    return req<Holiday>(HOL, { method: "POST", body: JSON.stringify(payload) });
  }
  static deleteHoliday(date: string) { return req<{ deleted: boolean }>(`${HOL}/${date}`, { method: "DELETE" }); }
  static checkDate(date: string) { return req<HolidayCheck>(`${HOL}/check/${date}`); }
}
```

- [ ] **Step 2: Lint**

```bash
cd frontend
npx eslint --max-warnings=0 src/api/custom-skill-service/command-scheduler.api.ts
```
Expected: exit code 0, no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/custom-skill-service/command-scheduler.api.ts
git commit -m "feat(cs): frontend API client + TypeScript types"
```

---

## Task 10: Sidebar button + route + empty page

**Files:**
- Create: `frontend/src/components/shared/buttons/command-scheduler-button.tsx`
- Modify: `frontend/src/components/features/sidebar/sidebar.tsx`
- Modify: `frontend/src/routes.ts`
- Create: `frontend/src/routes/command-scheduler.tsx`
- Create: `frontend/src/components/features/custom/command-scheduler/command-scheduler-page.tsx`

- [ ] **Step 1: Sidebar button**

```tsx
// frontend/src/components/shared/buttons/command-scheduler-button.tsx
import { useNavigate, useLocation } from "react-router";
import { cn } from "#/utils/utils";

export function CommandSchedulerButton() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const isActive = pathname.startsWith("/command-scheduler");
  return (
    <button
      type="button"
      onClick={() => navigate("/command-scheduler")}
      title="定时任务中心"
      aria-label="定时任务中心"
      className={cn(
        "w-[36px] h-[36px] rounded flex items-center justify-center transition",
        isActive
          ? "bg-blue-600 text-white"
          : "text-gray-400 hover:text-white hover:bg-[#333]",
      )}
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <circle cx="12" cy="15" r="2" />
      </svg>
    </button>
  );
}
```

- [ ] **Step 2: Add button to sidebar**

In `frontend/src/components/features/sidebar/sidebar.tsx`, add the import with the other custom buttons:
```tsx
import { CommandSchedulerButton } from "#/components/shared/buttons/command-scheduler-button";
```
And in the JSX, place `<CommandSchedulerButton />` right before `<ChatButton />`.

- [ ] **Step 3: Add route**

In `frontend/src/routes.ts`, add a line after the existing `route("chat", "routes/chat.tsx"),`:
```tsx
route("command-scheduler", "routes/command-scheduler.tsx"),
```

- [ ] **Step 4: Route wrapper**

```tsx
// frontend/src/routes/command-scheduler.tsx
import { CommandSchedulerPage } from "#/components/features/custom/command-scheduler/command-scheduler-page";
export default function CommandSchedulerRoute() {
  return <CommandSchedulerPage />;
}
```

- [ ] **Step 5: Empty page shell**

```tsx
// frontend/src/components/features/custom/command-scheduler/command-scheduler-page.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";

export function CommandSchedulerPage() {
  return (
    <div className="h-full flex flex-col text-white bg-[#0d1117]">
      <div className="px-5 py-3 border-b border-[#30363d]">
        <h1 className="text-base font-semibold">定时任务管理中心</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          配置和监控定时执行的 shell / python 脚本
        </p>
      </div>
      <div className="flex-1 flex items-center justify-center text-gray-500">
        (placeholder — 任务列表将在 Task 11 落地)
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Visual check in browser**

Open `http://127.0.0.1:12001/command-scheduler`. Should see:
- Sidebar button highlighted
- Header with title
- Placeholder text

Hard-refresh (Ctrl+Shift+R) if the dev server hasn't picked up the new route.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/shared/buttons/command-scheduler-button.tsx \
        frontend/src/components/features/sidebar/sidebar.tsx \
        frontend/src/routes.ts \
        frontend/src/routes/command-scheduler.tsx \
        frontend/src/components/features/custom/command-scheduler/
git commit -m "feat(cs): sidebar entry + route + empty page shell"
```

---

## Task 11: Main page layout — stats bar, filter, task grid, task card

**Files:**
- Create: `frontend/src/components/features/custom/command-scheduler/use-command-scheduler.ts`
- Create: `frontend/src/components/features/custom/command-scheduler/stats-bar.tsx`
- Create: `frontend/src/components/features/custom/command-scheduler/filter-bar.tsx`
- Create: `frontend/src/components/features/custom/command-scheduler/task-grid.tsx`
- Create: `frontend/src/components/features/custom/command-scheduler/task-card.tsx`
- Modify: `command-scheduler-page.tsx` to use them

- [ ] **Step 1: Data hook**

```tsx
// use-command-scheduler.ts
import React from "react";
import {
  CommandSchedulerService,
  CommandSchedule,
  Stats,
} from "#/api/custom-skill-service/command-scheduler.api";

export function useCommandScheduler() {
  const [schedules, setSchedules] = React.useState<CommandSchedule[]>([]);
  const [stats, setStats] = React.useState<Stats>({ total: 0, running: 0, enabled: 0, disabled: 0 });
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [filter, setFilter] = React.useState<{ env_tag?: string; q?: string }>({});

  const refresh = React.useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [list, st] = await Promise.all([
        CommandSchedulerService.list(filter),
        CommandSchedulerService.stats(),
      ]);
      setSchedules(list); setStats(st);
    } catch (e) {
      const err = e as Error;
      setError(err.message || "failed to load");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  React.useEffect(() => { refresh(); }, [refresh]);

  const toggleEnabled = React.useCallback(
    async (id: string, enabled: boolean) => {
      await CommandSchedulerService.update(id, { enabled });
      await refresh();
    },
    [refresh],
  );

  const runNow = React.useCallback(
    async (id: string) => {
      await CommandSchedulerService.run(id);
      await refresh();
    },
    [refresh],
  );

  const remove = React.useCallback(
    async (id: string) => {
      await CommandSchedulerService.delete(id);
      await refresh();
    },
    [refresh],
  );

  return { schedules, stats, loading, error, filter, setFilter, refresh, toggleEnabled, runNow, remove };
}
```

- [ ] **Step 2: Stats bar**

```tsx
// stats-bar.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import { Stats } from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

export function StatsBar({ stats }: { stats: Stats }) {
  const cells: { label: string; value: number; color: string }[] = [
    { label: "总任务", value: stats.total, color: "text-white" },
    { label: "执行中", value: stats.running, color: "text-blue-400" },
    { label: "已启用", value: stats.enabled, color: "text-green-400" },
    { label: "已停用", value: stats.disabled, color: "text-gray-500" },
  ];
  return (
    <div className="grid grid-cols-4 gap-3 px-5 py-3 border-b border-[#30363d]">
      {cells.map((c) => (
        <div key={c.label} className="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-3">
          <div className="text-xs text-gray-500">{c.label}</div>
          <div className={cn("text-2xl font-semibold mt-1", c.color)}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Filter bar**

```tsx
// filter-bar.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import { cn } from "#/utils/utils";

interface Props {
  envTag: string | undefined;
  q: string;
  onChange: (f: { env_tag?: string; q?: string }) => void;
  onNew: () => void;
  onHolidays: () => void;
  onPauseAll: () => void;
}
export function FilterBar({ envTag, q, onChange, onNew, onHolidays, onPauseAll }: Props) {
  const tabs: { key: string | undefined; label: string }[] = [
    { key: undefined, label: "全部" },
    { key: "formal", label: "正式" },
    { key: "test", label: "测试" },
  ];
  return (
    <div className="flex items-center gap-3 px-5 py-3 border-b border-[#30363d]">
      <div className="flex gap-1 bg-[#161b22] rounded-lg p-1">
        {tabs.map((t) => (
          <button
            key={t.label}
            type="button"
            onClick={() => onChange({ env_tag: t.key, q })}
            className={cn(
              "px-3 py-1 rounded text-xs transition",
              envTag === t.key
                ? "bg-blue-600 text-white"
                : "text-gray-400 hover:text-white",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <input
        type="text"
        value={q}
        onChange={(e) => onChange({ env_tag: envTag, q: e.target.value })}
        placeholder="搜索任务名称"
        className="flex-1 bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 text-sm text-white placeholder:text-gray-600"
      />
      <button type="button" onClick={onPauseAll} className="text-xs px-3 py-1.5 rounded border border-[#30363d] text-gray-400 hover:text-white">
        暂停全部
      </button>
      <button type="button" onClick={onHolidays} className="text-xs px-3 py-1.5 rounded border border-[#30363d] text-gray-400 hover:text-white">
        节假日管理
      </button>
      <button type="button" onClick={onNew} className="text-xs px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-500">
        + 新建任务
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Task card**

```tsx
// task-card.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import { CommandSchedule } from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

interface Props {
  schedule: CommandSchedule;
  onRun: () => void;
  onEdit: () => void;
  onHistory: () => void;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}
export function TaskCard({ schedule, onRun, onEdit, onHistory, onToggle, onDelete }: Props) {
  const envBadge =
    schedule.env_tag === "formal"
      ? { bg: "bg-blue-900/40 text-blue-300", text: "【正式】" }
      : { bg: "bg-yellow-900/40 text-yellow-300", text: "【测试】" };
  const windowsBadge = schedule.shell_kind === "windows";

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded", envBadge.bg)}>
              {envBadge.text}
            </span>
            {windowsBadge && (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">
                ⚠ Windows 暂存
              </span>
            )}
          </div>
          <div className="font-semibold text-sm mt-1 truncate">{schedule.name}</div>
          <div className="text-xs text-gray-500 mt-0.5">{schedule.schedule_description}</div>
        </div>
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={schedule.enabled}
            onChange={(e) => onToggle(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-9 h-5 bg-gray-700 rounded-full peer peer-checked:bg-green-600 transition-colors" />
          <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full peer-checked:translate-x-4 transition-transform" />
        </label>
      </div>
      <div className="text-[11px] text-gray-500 space-y-0.5">
        <div>下次: {schedule.next_fire_at ? new Date(schedule.next_fire_at).toLocaleString("zh-CN") : "(未调度)"}</div>
        <div>上次: {schedule.last_fire_at ? new Date(schedule.last_fire_at).toLocaleString("zh-CN") : "(从未)"}</div>
      </div>
      <div className="flex gap-2 mt-1">
        <button type="button" onClick={onRun}
          className="text-[11px] px-2 py-1 rounded bg-green-900/30 text-green-400 hover:bg-green-900/50">
          ▶ 执行
        </button>
        <button type="button" onClick={onEdit}
          className="text-[11px] px-2 py-1 rounded bg-[#30363d] text-gray-300 hover:bg-[#444]">
          📝 编辑
        </button>
        <button type="button" onClick={onHistory}
          className="text-[11px] px-2 py-1 rounded bg-[#30363d] text-gray-300 hover:bg-[#444]">
          📜 历史
        </button>
        <button type="button" onClick={onDelete}
          className="text-[11px] px-2 py-1 rounded bg-red-900/30 text-red-400 hover:bg-red-900/50 ml-auto">
          🗑
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Task grid**

```tsx
// task-grid.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import { CommandSchedule } from "#/api/custom-skill-service/command-scheduler.api";
import { TaskCard } from "./task-card";

interface Props {
  schedules: CommandSchedule[];
  loading: boolean;
  onRun: (id: string) => void;
  onEdit: (s: CommandSchedule) => void;
  onHistory: (s: CommandSchedule) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}
export function TaskGrid({ schedules, loading, onRun, onEdit, onHistory, onToggle, onDelete }: Props) {
  if (loading && schedules.length === 0) {
    return <div className="p-6 text-sm text-gray-500">加载中…</div>;
  }
  if (schedules.length === 0) {
    return <div className="p-10 text-center text-sm text-gray-500">还没有任务，点右上角 "+新建任务" 创建</div>;
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 p-5 overflow-y-auto custom-scrollbar">
      {schedules.map((s) => (
        <TaskCard
          key={s.id}
          schedule={s}
          onRun={() => onRun(s.id)}
          onEdit={() => onEdit(s)}
          onHistory={() => onHistory(s)}
          onToggle={(e) => onToggle(s.id, e)}
          onDelete={() => {
            if (confirm(`确定删除 "${s.name}"?`)) onDelete(s.id);
          }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Wire into page**

```tsx
// command-scheduler-page.tsx (replace placeholder)
/* eslint-disable i18next/no-literal-string */
import React from "react";
import { CommandSchedulerService } from "#/api/custom-skill-service/command-scheduler.api";
import { StatsBar } from "./stats-bar";
import { FilterBar } from "./filter-bar";
import { TaskGrid } from "./task-grid";
import { useCommandScheduler } from "./use-command-scheduler";

export function CommandSchedulerPage() {
  const {
    schedules, stats, loading, error, filter, setFilter, refresh,
    toggleEnabled, runNow, remove,
  } = useCommandScheduler();

  return (
    <div className="h-full flex flex-col text-white bg-[#0d1117]">
      <div className="px-5 py-3 border-b border-[#30363d]">
        <h1 className="text-base font-semibold">定时任务管理中心</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          配置和监控定时执行的 shell / python 脚本
        </p>
      </div>
      <StatsBar stats={stats} />
      <FilterBar
        envTag={filter.env_tag}
        q={filter.q || ""}
        onChange={setFilter}
        onNew={() => alert("新建任务 modal: Task 12")}
        onHolidays={() => alert("节假日管理: Task 13")}
        onPauseAll={async () => {
          if (confirm("确定暂停所有任务?")) {
            await CommandSchedulerService.pauseAll();
            await refresh();
          }
        }}
      />
      {error && (
        <div className="mx-5 mt-3 px-3 py-2 rounded bg-red-900/30 border border-red-900/50 text-xs text-red-400">
          错误: {error}
        </div>
      )}
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-y-auto">
          <TaskGrid
            schedules={schedules}
            loading={loading}
            onRun={runNow}
            onEdit={() => alert("编辑 modal: Task 12")}
            onHistory={() => alert("历史 modal: Task 13")}
            onToggle={toggleEnabled}
            onDelete={remove}
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Lint + manual browser check**

```bash
cd frontend
npx eslint --max-warnings=0 src/components/features/custom/command-scheduler/ \
                           src/api/custom-skill-service/command-scheduler.api.ts
```
Expected: exit 0.

Reload `http://127.0.0.1:12001/command-scheduler`. Should see stats, filter bar, and the one test schedule created in Task 8 rendered as a card.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/features/custom/command-scheduler/
git commit -m "feat(cs): frontend main page — stats, filter, task grid"
```

---

## Task 12: Edit task modal

**Files:**
- Create: `frontend/src/components/features/custom/command-scheduler/edit-task-modal.tsx`
- Modify: `command-scheduler-page.tsx` to open it

- [ ] **Step 1: Modal with full form**

```tsx
// edit-task-modal.tsx
/* eslint-disable i18next/no-literal-string, @typescript-eslint/no-explicit-any */
import React from "react";
import {
  CommandSchedule,
  CommandScheduleInput,
  CommandSchedulerService,
  ScheduleKind,
  ShellKind,
  HolidayPolicy,
  EnvTag,
} from "#/api/custom-skill-service/command-scheduler.api";

interface Props {
  initial?: CommandSchedule;
  onClose: () => void;
  onSaved: () => void;
}

const DEFAULT: CommandScheduleInput = {
  name: "",
  env_tag: "formal",
  shell_kind: "linux",
  kind: "daily",
  cron_expr: "0 9 * * *",
  run_at: null,
  command: "",
  working_dir: null,
  max_duration_sec: 300,
  holiday_policy: "normal",
  enabled: true,
};

export function EditTaskModal({ initial, onClose, onSaved }: Props) {
  const [form, setForm] = React.useState<CommandScheduleInput>(() => {
    if (!initial) return DEFAULT;
    return {
      name: initial.name,
      env_tag: initial.env_tag,
      shell_kind: initial.shell_kind,
      kind: initial.kind,
      cron_expr: initial.cron_expr,
      run_at: initial.run_at,
      command: initial.command,
      working_dir: initial.working_dir,
      max_duration_sec: initial.max_duration_sec,
      holiday_policy: initial.holiday_policy,
      enabled: initial.enabled,
    };
  });
  const [saving, setSaving] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const update = <K extends keyof CommandScheduleInput>(k: K, v: CommandScheduleInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true); setErr(null);
    try {
      if (initial) await CommandSchedulerService.update(initial.id, form);
      else await CommandSchedulerService.create(form);
      onSaved();
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl w-[600px] max-h-[90vh] overflow-y-auto p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">{initial ? "编辑任务" : "新建任务"}</h2>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-white">✕</button>
        </div>
        <div className="space-y-3 text-sm">
          <Field label="任务名称">
            <input
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            />
          </Field>
          <Field label="环境标签">
            <div className="flex gap-4">
              {(["formal", "test"] as EnvTag[]).map((v) => (
                <label key={v} className="flex items-center gap-1">
                  <input type="radio" checked={form.env_tag === v} onChange={() => update("env_tag", v)} />
                  {v === "formal" ? "正式" : "测试"}
                </label>
              ))}
            </div>
          </Field>
          <Field label="命令类型">
            <div className="flex gap-4">
              {(["linux", "windows"] as ShellKind[]).map((v) => (
                <label key={v} className="flex items-center gap-1">
                  <input type="radio" checked={form.shell_kind === v} onChange={() => update("shell_kind", v)} />
                  {v === "linux" ? "Linux" : "Windows (暂存)"}
                </label>
              ))}
            </div>
          </Field>
          <Field label="调度类型">
            <select
              value={form.kind}
              onChange={(e) => update("kind", e.target.value as ScheduleKind)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            >
              <option value="one_time">一次性</option>
              <option value="daily">每天</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
              <option value="yearly">每年</option>
            </select>
          </Field>
          {form.kind === "one_time" ? (
            <Field label="执行时间">
              <input
                type="datetime-local"
                value={form.run_at?.slice(0, 16) || ""}
                onChange={(e) => update("run_at", e.target.value ? new Date(e.target.value).toISOString() : null)}
                className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
              />
            </Field>
          ) : (
            <Field label="Cron 表达式">
              <input
                value={form.cron_expr || ""}
                onChange={(e) => update("cron_expr", e.target.value)}
                placeholder="例: 0 9 * * * (每天 09:00)"
                className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 font-mono text-xs"
              />
            </Field>
          )}
          <Field label="节假日策略">
            <select
              value={form.holiday_policy}
              onChange={(e) => update("holiday_policy", e.target.value as HolidayPolicy)}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            >
              <option value="normal">照常运行</option>
              <option value="skip">节假日跳过</option>
              <option value="run_before">提前到前一工作日 (P1 同 skip)</option>
              <option value="run_after">延后到后一工作日 (P1 同 skip)</option>
            </select>
          </Field>
          <Field label="最大执行时长 (秒)">
            <input
              type="number"
              value={form.max_duration_sec}
              onChange={(e) => update("max_duration_sec", parseInt(e.target.value || "300", 10))}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5"
            />
          </Field>
          <Field label="执行命令">
            <textarea
              value={form.command}
              onChange={(e) => update("command", e.target.value)}
              rows={6}
              className="w-full bg-[#0d1117] border border-[#30363d] rounded px-3 py-2 font-mono text-xs"
              placeholder={`cd /opt/hiclaw/command_scheduler/workspace/nps\nsource /opt/hiclaw/command_scheduler/venv/bin/activate\npython send_nps.py --prod`}
            />
          </Field>
          {err && <div className="text-xs text-red-400">错误: {err}</div>}
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button type="button" onClick={onClose}
            className="text-sm px-3 py-1.5 rounded border border-[#30363d] text-gray-400 hover:text-white">
            取消
          </button>
          <button type="button" disabled={saving} onClick={save}
            className="text-sm px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50">
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] text-gray-500 mb-1">{label}</div>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Wire into page**

In `command-scheduler-page.tsx`, replace the two `alert("编辑 modal")` calls with state + modal:

```tsx
const [editing, setEditing] = React.useState<CommandSchedule | undefined | null>(null);
// ...
onNew={() => setEditing(undefined)}
// ...
onEdit={(s) => setEditing(s)}
// ...
{editing !== null && (
  <EditTaskModal
    initial={editing || undefined}
    onClose={() => setEditing(null)}
    onSaved={refresh}
  />
)}
```

Use `null` for "closed", `undefined` for "new", `CommandSchedule` for "edit". Don't forget to import `EditTaskModal` and `CommandSchedule` type.

- [ ] **Step 3: Lint + browser check**

```bash
cd frontend && npx eslint --max-warnings=0 src/components/features/custom/command-scheduler/
```

In browser, click `+新建任务` → fill in a test schedule → save → see it appear in the grid.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/features/custom/command-scheduler/edit-task-modal.tsx \
        frontend/src/components/features/custom/command-scheduler/command-scheduler-page.tsx
git commit -m "feat(cs): edit / create task modal with full form"
```

---

## Task 13: Calendar widget, upcoming runs, history modal, holiday manager

**Files:**
- Create: `frontend/src/components/features/custom/command-scheduler/month-calendar.tsx`
- Create: `frontend/src/components/features/custom/command-scheduler/upcoming-runs.tsx`
- Create: `frontend/src/components/features/custom/command-scheduler/task-history-modal.tsx`
- Create: `frontend/src/components/features/custom/command-scheduler/holiday-manager-modal.tsx`
- Modify: `command-scheduler-page.tsx` to use them

- [ ] **Step 1: Month calendar**

```tsx
// month-calendar.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import { CommandSchedulerService, Holiday } from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

export function MonthCalendar() {
  const now = new Date();
  const [year, setYear] = React.useState(now.getFullYear());
  const [month, setMonth] = React.useState(now.getMonth() + 1); // 1-12
  const [holidays, setHolidays] = React.useState<Holiday[]>([]);

  React.useEffect(() => {
    CommandSchedulerService.listHolidays(year).then(setHolidays).catch(() => setHolidays([]));
  }, [year]);

  const holidayByDate = React.useMemo(() => {
    const m = new Map<string, Holiday>();
    holidays.forEach((h) => m.set(h.date, h));
    return m;
  }, [holidays]);

  const firstDay = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const labelOf = (d: number) => `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

  const prev = () => {
    if (month === 1) { setYear(year - 1); setMonth(12); }
    else setMonth(month - 1);
  };
  const next = () => {
    if (month === 12) { setYear(year + 1); setMonth(1); }
    else setMonth(month + 1);
  };

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-3">
      <div className="flex items-center justify-between mb-2">
        <button type="button" onClick={prev} className="text-gray-400 hover:text-white">‹</button>
        <div className="text-sm font-semibold">{year} 年 {month} 月</div>
        <button type="button" onClick={next} className="text-gray-400 hover:text-white">›</button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-[11px]">
        {"日 一 二 三 四 五 六".split(" ").map((w) => (
          <div key={w} className="text-center text-gray-500 py-1">{w}</div>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <div key={i} />;
          const h = holidayByDate.get(labelOf(d));
          const isHoliday = h?.kind === "holiday";
          const isMakeup = h?.kind === "makeup_workday";
          return (
            <div
              key={i}
              title={h?.name}
              className={cn(
                "aspect-square flex items-center justify-center rounded text-xs",
                isHoliday && "bg-red-900/30 text-red-300",
                isMakeup && "bg-yellow-900/30 text-yellow-300",
                !h && "text-gray-400",
              )}
            >
              {d}
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Upcoming runs panel**

```tsx
// upcoming-runs.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import { CommandSchedule } from "#/api/custom-skill-service/command-scheduler.api";

export function UpcomingRuns({ schedules }: { schedules: CommandSchedule[] }) {
  const upcoming = schedules
    .filter((s) => s.enabled && s.next_fire_at)
    .map((s) => ({ s, t: new Date(s.next_fire_at as string) }))
    .sort((a, b) => a.t.getTime() - b.t.getTime())
    .slice(0, 8);

  return (
    <div className="bg-[#161b22] border border-[#30363d] rounded-xl p-3 mt-3">
      <div className="text-sm font-semibold mb-2">近期执行</div>
      {upcoming.length === 0 ? (
        <div className="text-xs text-gray-500">暂无计划</div>
      ) : (
        <div className="space-y-1.5 text-xs">
          {upcoming.map(({ s, t }) => (
            <div key={s.id} className="flex gap-2">
              <span className="text-gray-500 shrink-0">
                {t.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
              </span>
              <span className="truncate">{s.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: History modal**

```tsx
// task-history-modal.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import {
  CommandSchedule,
  CommandFire,
  CommandSchedulerService,
} from "#/api/custom-skill-service/command-scheduler.api";
import { cn } from "#/utils/utils";

const STATUS_COLOR: Record<string, string> = {
  success: "bg-green-900/40 text-green-400",
  failed: "bg-red-900/40 text-red-400",
  timeout: "bg-orange-900/40 text-orange-400",
  skipped: "bg-gray-800 text-gray-400",
  running: "bg-blue-900/40 text-blue-400",
};

export function TaskHistoryModal({ schedule, onClose }: { schedule: CommandSchedule; onClose: () => void }) {
  const [fires, setFires] = React.useState<CommandFire[]>([]);
  const [selected, setSelected] = React.useState<CommandFire | null>(null);

  React.useEffect(() => {
    CommandSchedulerService.listFires(schedule.id, 50).then(setFires).catch(() => setFires([]));
  }, [schedule.id]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl w-[800px] max-h-[90vh] flex flex-col p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">{schedule.name} — 执行历史</h2>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-white">✕</button>
        </div>
        <div className="grid grid-cols-[260px_1fr] gap-4 flex-1 overflow-hidden">
          <div className="overflow-y-auto custom-scrollbar space-y-1">
            {fires.map((f) => (
              <button
                type="button"
                key={f.id}
                onClick={() => setSelected(f)}
                className={cn(
                  "w-full text-left text-xs p-2 rounded hover:bg-[#222]",
                  selected?.id === f.id && "bg-[#222]",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-semibold", STATUS_COLOR[f.status])}>
                    {f.status}
                  </span>
                  <span className="text-gray-500">{new Date(f.started_at).toLocaleString("zh-CN")}</span>
                </div>
                {f.skip_reason && <div className="text-gray-600 mt-0.5">原因: {f.skip_reason}</div>}
              </button>
            ))}
            {fires.length === 0 && <div className="text-xs text-gray-500 p-2">暂无执行记录</div>}
          </div>
          <div className="overflow-y-auto custom-scrollbar bg-[#0d1117] rounded border border-[#30363d] p-3">
            {selected ? (
              <>
                <div className="text-xs text-gray-500 mb-2">
                  退出码: {selected.exit_code ?? "—"} ·
                  开始: {new Date(selected.started_at).toLocaleString("zh-CN")} ·
                  结束: {selected.completed_at ? new Date(selected.completed_at).toLocaleString("zh-CN") : "(未结束)"}
                </div>
                {selected.log_file_path && (
                  <a
                    href={CommandSchedulerService.logUrl(selected.id)}
                    className="text-xs text-blue-400 hover:underline"
                    download
                  >
                    下载完整日志
                  </a>
                )}
                <div className="mt-3">
                  <div className="text-[10px] text-gray-600">STDOUT</div>
                  <pre className="text-[11px] whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {selected.stdout_tail || "(空)"}
                  </pre>
                </div>
                <div className="mt-3">
                  <div className="text-[10px] text-gray-600">STDERR</div>
                  <pre className="text-[11px] whitespace-pre-wrap max-h-48 overflow-y-auto text-red-300">
                    {selected.stderr_tail || "(空)"}
                  </pre>
                </div>
              </>
            ) : (
              <div className="text-xs text-gray-500">从左侧选择一次执行查看详情</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Holiday manager modal**

```tsx
// holiday-manager-modal.tsx
/* eslint-disable i18next/no-literal-string */
import React from "react";
import {
  CommandSchedulerService,
  Holiday,
  HolidayCheck,
} from "#/api/custom-skill-service/command-scheduler.api";

export function HolidayManagerModal({ onClose }: { onClose: () => void }) {
  const now = new Date();
  const [year, setYear] = React.useState(now.getFullYear());
  const [holidays, setHolidays] = React.useState<Holiday[]>([]);
  const [checkDate, setCheckDate] = React.useState(now.toISOString().slice(0, 10));
  const [checkResult, setCheckResult] = React.useState<HolidayCheck | null>(null);
  const [addDate, setAddDate] = React.useState("");
  const [addName, setAddName] = React.useState("");
  const [addKind, setAddKind] = React.useState("holiday");

  const refresh = React.useCallback(() => {
    CommandSchedulerService.listHolidays(year).then(setHolidays).catch(() => setHolidays([]));
  }, [year]);
  React.useEffect(refresh, [refresh]);

  const doCheck = async () => {
    try {
      setCheckResult(await CommandSchedulerService.checkDate(checkDate));
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const doAdd = async () => {
    if (!addDate || !addName) return;
    try {
      await CommandSchedulerService.addHoliday({ date: addDate, name: addName, kind: addKind });
      setAddDate(""); setAddName("");
      refresh();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const doDelete = async (date: string) => {
    if (!confirm(`删除 ${date}?`)) return;
    try {
      await CommandSchedulerService.deleteHoliday(date);
      refresh();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const presets = holidays.filter((h) => h.source === "preset");
  const userRows = holidays.filter((h) => h.source === "user");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl w-[800px] max-h-[90vh] overflow-y-auto p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">节假日管理</h2>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-white">✕</button>
        </div>

        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs text-gray-500">年份:</span>
          <input type="number" value={year} onChange={(e) => setYear(parseInt(e.target.value, 10))}
            className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 w-20 text-xs" />
        </div>

        <Section title={`预置节假日 (${presets.length})`}>
          <div className="max-h-32 overflow-y-auto text-xs grid grid-cols-3 gap-1">
            {presets.map((h) => (
              <div key={h.date} className="px-2 py-1 bg-[#0d1117] rounded">
                <span className="text-gray-500">{h.date}</span> <span>{h.name}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title={`自定义节假日 (${userRows.length})`}>
          <div className="space-y-2">
            {userRows.map((h) => (
              <div key={h.date} className="flex items-center gap-2 text-xs">
                <span className="text-gray-500">{h.date}</span>
                <span>{h.name}</span>
                <span className="text-gray-600">· {h.kind}</span>
                <button type="button" onClick={() => doDelete(h.date)}
                  className="ml-auto text-red-400 hover:text-red-300">
                  删除
                </button>
              </div>
            ))}
            <div className="flex items-center gap-2 mt-2">
              <input type="date" value={addDate} onChange={(e) => setAddDate(e.target.value)}
                className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs" />
              <input type="text" value={addName} onChange={(e) => setAddName(e.target.value)}
                placeholder="名称" className="flex-1 bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs" />
              <select value={addKind} onChange={(e) => setAddKind(e.target.value)}
                className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-xs">
                <option value="holiday">节假日</option>
                <option value="makeup_workday">调休上班</option>
              </select>
              <button type="button" onClick={doAdd}
                className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500">
                添加
              </button>
            </div>
          </div>
        </Section>

        <Section title="日期检查">
          <div className="flex items-center gap-2 text-xs">
            <input type="date" value={checkDate} onChange={(e) => setCheckDate(e.target.value)}
              className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1" />
            <button type="button" onClick={doCheck}
              className="text-xs px-3 py-1 rounded bg-[#30363d] text-gray-300 hover:bg-[#444]">
              检查
            </button>
            {checkResult && (
              <span className="text-gray-400">
                {checkResult.is_holiday ? "节假日" : checkResult.is_makeup_workday ? "调休上班" : checkResult.is_workday ? "工作日" : "周末"}
                {checkResult.name ? ` · ${checkResult.name}` : ""}
              </span>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="text-xs text-gray-500 mb-2">{title}</div>
      {children}
    </div>
  );
}
```

- [ ] **Step 5: Wire into page**

In `command-scheduler-page.tsx`:
- Add state `const [history, setHistory] = React.useState<CommandSchedule | null>(null);`
- Add state `const [holidayModal, setHolidayModal] = React.useState(false);`
- Replace `onHistory={() => alert...}` with `onHistory={(s) => setHistory(s)}`
- Replace `onHolidays={() => alert...}` with `onHolidays={() => setHolidayModal(true)}`
- Add right-side panel in the flex layout containing `<MonthCalendar />` + `<UpcomingRuns schedules={schedules} />`
- Render modals conditionally

Suggested JSX for the main content area:
```tsx
<div className="flex-1 overflow-hidden flex">
  <div className="flex-1 overflow-y-auto">
    <TaskGrid ... />
  </div>
  <aside className="w-[280px] border-l border-[#30363d] p-3 overflow-y-auto custom-scrollbar">
    <MonthCalendar />
    <UpcomingRuns schedules={schedules} />
  </aside>
</div>
{history && (
  <TaskHistoryModal schedule={history} onClose={() => setHistory(null)} />
)}
{holidayModal && (
  <HolidayManagerModal onClose={() => setHolidayModal(false)} />
)}
```

- [ ] **Step 6: Lint + browser check**

```bash
cd frontend && npx eslint --max-warnings=0 src/components/features/custom/command-scheduler/
```

Verify in browser:
- Right-side panel shows calendar with holiday coloring
- "近期执行" shows upcoming runs
- Click `📜历史` on a card → modal opens, shows fires
- Click `节假日管理` → modal opens, lists preset holidays + allows adding

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/features/custom/command-scheduler/
git commit -m "feat(cs): calendar, upcoming runs, history modal, holiday manager"
```

---

## Task 14: End-to-end verification + bug sweep

No new files. Verify the whole system works end-to-end and fix anything broken.

- [ ] **Step 1: Backend restart + DB check**

Restart HiClaw backend. Confirm:
```bash
sqlite3 ~/.openhands/openhands.db ".tables" | tr ' ' '\n' | grep -E "command_|holidays"
```
Expected: `command_fires`, `command_schedules`, `holidays`

```bash
sqlite3 ~/.openhands/openhands.db "SELECT count(*) FROM holidays WHERE source='preset';"
```
Expected: >= 30 (2026 preset rows loaded)

- [ ] **Step 2: Full E2E scenario via browser**

1. Open `/command-scheduler`
2. Click `+新建任务` → create a `daily` linux task with command `echo hello; date`, time next minute
3. Wait up to 1 minute → watch stats update (`running` briefly, then back to 0)
4. Click `📜历史` → should see a `success` fire with stdout showing "hello" + timestamp
5. Click download full log → file downloads with correct content
6. Create a `windows` task → manually run → history shows `skipped: windows_not_supported`
7. Create a task with `holiday_policy=skip` and run on today (if today is a holiday via custom add) → skipped
8. Click `节假日管理` → add a custom holiday → verify it appears in the calendar in red
9. Pause all → all task toggles go to off, no next_fire_at
10. Resume all → toggles back on

- [ ] **Step 3: Fix anything broken**

Any issues found, fix in place, re-verify. Document any P1-limitation escape hatches.

- [ ] **Step 4: Doc updates**

If any ADR in `DESIGN.md` turned out wrong during implementation, update it. Bump the document version to 0.2 and add a row to the revision history.

- [ ] **Step 5: Final commit + merge**

```bash
git add -A
git commit -m "test(cs): E2E verification + doc updates"

# Merge to dev
git checkout dev
git merge --no-ff feat/command-scheduler -m "Merge branch 'feat/command-scheduler' into dev"

# Push (after user confirms — per feedback_dev_preferences)
# git push hiclaw dev
# git push hiclaw feat/command-scheduler
```

- [ ] **Step 6: Trigger finishing-a-development-branch**

**REQUIRED SUB-SKILL:** Use `superpowers:finishing-a-development-branch` to verify tests + present completion options.

---

## Notes and gotchas for the implementer

1. **`custom/agent_mgmt/db.get_agent_db`** is the session factory we're borrowing via `db.py`. If it opens a new session each call, make sure to close it in `finally` — see the pattern in `custom/scheduled_tasks/scheduler.py:64-69`.

2. **Shared scheduler startup order matters.** `custom/command_scheduler` depends on `custom/scheduled_tasks` having called `start()` first (which actually starts the AsyncIOScheduler). The lifespan wiring in Task 8 puts command_scheduler init **after** scheduled_tasks init, which is correct.

3. **Preset holiday data is a placeholder.** The 2026 YAML entries were drafted from memory — confirm against the official State Council release before merging to dev. If 2026 has not been published, leave the 2026 YAML empty-ish and let users populate via the custom-holiday UI.

4. **ProcessSandboxService API is uncertain.** Task 7 Step 5 is the most likely place to get stuck. The plan includes a subprocess fallback via `_run_with_fallback` so even if the sandbox wiring isn't finished, the scheduler still produces working fires. Leave a TODO comment and move on.

5. **`run_before` / `run_after` are not fully implemented in P1.** The field is persisted, UI shows the option, but executor only does "skip on the day". The compensation scanner is P2 work (DESIGN.md §5.5). The UI copy on the dropdown says "(P1 同 skip)" for clarity.

6. **Every task ends with a commit.** Don't batch. The reviewer / user wants granular history so they can cherry-pick or revert.

7. **No pytest.** HiClaw `custom/` modules are verified via curl + sqlite + browser, consistent with the existing `scheduled_tasks` pattern.

8. **Windows暂存** is wired end-to-end: create a windows task → the fire path short-circuits with `skipped: windows_not_supported`, and the UI shows the grey badge. No new runtime needed.
