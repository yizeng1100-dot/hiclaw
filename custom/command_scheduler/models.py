"""SQLAlchemy models + Pydantic schemas for the command scheduler.

Three tables:
- ``command_schedules``:  one row per scheduled shell command
- ``command_fires``:      one row per fire attempt (including skipped)
- ``holidays``:           preset + user-defined holidays and makeup workdays
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, func
from sqlalchemy import UUID as SQLUUID

from openhands.app_server.utils.sql_utils import Base, UtcDateTime


# ─── SQLAlchemy ORM ──────────────────────────────────────────────────

ScheduleKind = Literal['one_time', 'daily', 'weekly', 'monthly', 'yearly']
HolidayPolicy = Literal['normal', 'skip', 'run_before', 'run_after']
ShellKind = Literal['linux', 'windows']
EnvTag = Literal['formal', 'test']
FireStatus = Literal[
    'running',
    'success',
    'failed',
    'timeout',
    'skipped',
    'pending_runner',
]
TriggerSource = Literal['scheduled', 'manual']


class StoredCommandSchedule(Base):  # type: ignore
    __tablename__ = 'command_schedules'

    id = Column(SQLUUID, primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    env_tag = Column(String, nullable=False, server_default='formal')
    shell_kind = Column(String, nullable=False, server_default='linux')
    kind = Column(String, nullable=False)
    cron_expr = Column(String, nullable=True)
    run_at = Column(UtcDateTime, nullable=True)
    command = Column(Text, nullable=False)
    working_dir = Column(String, nullable=True)
    max_duration_sec = Column(Integer, nullable=False, server_default='300')
    holiday_policy = Column(String, nullable=False, server_default='normal')
    log_path = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, server_default='1', index=True)
    created_at = Column(UtcDateTime, server_default=func.now())
    updated_at = Column(UtcDateTime, server_default=func.now())
    last_fire_at = Column(UtcDateTime, nullable=True)
    next_fire_at = Column(UtcDateTime, nullable=True)


class StoredCommandFire(Base):  # type: ignore
    __tablename__ = 'command_fires'

    id = Column(SQLUUID, primary_key=True, default=uuid4)
    schedule_id = Column(
        SQLUUID,
        ForeignKey('command_schedules.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    started_at = Column(UtcDateTime, server_default=func.now(), index=True)
    completed_at = Column(UtcDateTime, nullable=True)
    status = Column(String, nullable=False, server_default='running')
    skip_reason = Column(String, nullable=True)
    exit_code = Column(Integer, nullable=True)
    stdout_tail = Column(Text, nullable=True)
    stderr_tail = Column(Text, nullable=True)
    log_file_path = Column(String, nullable=True)
    trigger_source = Column(String, nullable=False, server_default='scheduled')


class StoredHoliday(Base):  # type: ignore
    __tablename__ = 'holidays'

    date = Column(String, primary_key=True)  # YYYY-MM-DD
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # holiday / makeup_workday
    source = Column(String, nullable=False)  # preset / user
    created_at = Column(UtcDateTime, server_default=func.now())


# ─── Pydantic schemas (router I/O) ───────────────────────────────────


class CommandScheduleCreate(BaseModel):
    name: str
    env_tag: EnvTag = 'formal'
    shell_kind: ShellKind = 'linux'
    kind: ScheduleKind
    cron_expr: str | None = None
    run_at: datetime | None = None
    command: str
    working_dir: str | None = None
    max_duration_sec: int = 300
    holiday_policy: HolidayPolicy = 'normal'
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
    kind: Literal['holiday', 'makeup_workday']
    source: Literal['preset', 'user']
    created_at: datetime


class HolidayCheckResult(BaseModel):
    date: str
    is_holiday: bool
    is_makeup_workday: bool
    is_workday: bool
    name: str | None = None


# ─── Windows runner protocol ────────────────────────────────────────


class PendingFireForRunner(BaseModel):
    """What the Windows runner needs to execute one fire."""

    fire_id: str
    schedule_id: str
    schedule_name: str
    command: str
    working_dir: str | None
    max_duration_sec: int
    created_at: datetime


class RunnerCompleteRequest(BaseModel):
    """Result payload the runner posts after finishing a fire."""

    exit_code: int
    stdout: str = ''
    stderr: str = ''
    # Optional: runner can explicitly mark the fire as 'timeout' even if
    # it managed to kill the process; otherwise we classify by exit_code.
    status: Literal['success', 'failed', 'timeout'] | None = None


class RunnerHeartbeatRequest(BaseModel):
    runner_id: str  # arbitrary tag — hostname / user-supplied
    runner_version: str = '1.0.0'
