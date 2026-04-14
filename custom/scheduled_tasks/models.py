"""SQLAlchemy models + Pydantic schemas for scheduled tasks.

Two tables:
- ``scheduled_task``: one row per scheduled agent run. Stores the agent
  id, schedule definition (friendly kind + params JSON), the preset
  form values that get template-substituted into the agent's
  ``submit_message`` on fire, and a few operational fields
  (enabled, last_fire_at, next_fire_at, last_status).
- ``scheduled_task_fire``: one row per actual fire — even failures.
  Acts as the fire log / history feed for the detail page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy import UUID as SQLUUID

from openhands.app_server.utils.sql_utils import Base, UtcDateTime


# ─── SQLAlchemy ORM ──────────────────────────────────────────────────


class StoredScheduledTask(Base):  # type: ignore
    __tablename__ = 'scheduled_task'

    id = Column(SQLUUID, primary_key=True, default=uuid4)
    agent_id = Column(
        SQLUUID,
        ForeignKey('managed_agent.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name = Column(String, nullable=False)
    schedule_kind = Column(
        String, nullable=False
    )  # every_n_minutes / hourly / daily / weekly / custom_cron
    schedule_params = Column(Text, nullable=False)  # JSON string
    form_values = Column(Text, nullable=False, server_default='{}')  # JSON string
    enabled = Column(Boolean, nullable=False, server_default='1', index=True)
    created_by = Column(String, nullable=True, index=True)
    created_at = Column(UtcDateTime, server_default=func.now(), index=True)
    updated_at = Column(UtcDateTime, server_default=func.now())
    last_fire_at = Column(UtcDateTime, nullable=True)
    next_fire_at = Column(UtcDateTime, nullable=True)
    last_status = Column(String, nullable=True)  # success / failed / running / null


class StoredScheduledTaskFire(Base):  # type: ignore
    __tablename__ = 'scheduled_task_fire'

    id = Column(SQLUUID, primary_key=True, default=uuid4)
    scheduled_task_id = Column(
        SQLUUID,
        ForeignKey('scheduled_task.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    started_at = Column(UtcDateTime, server_default=func.now(), index=True)
    completed_at = Column(UtcDateTime, nullable=True)
    status = Column(
        String, nullable=False, server_default='running', index=True
    )  # running / success / failed / skipped_concurrent
    task_id = Column(String, nullable=True)  # agent_task.id created by this fire
    conversation_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)


# ─── Pydantic schemas (router I/O) ───────────────────────────────────


class SchedulePayload(BaseModel):
    """Friendly schedule definition the UI sends and stores.

    Examples:
        {"kind": "every_n_minutes", "params": {"minutes": 15}}
        {"kind": "daily", "params": {"hour": 9, "minute": 0}}
        {"kind": "weekly", "params": {"day_of_week": "mon,wed,fri", "hour": 18, "minute": 30}}
        {"kind": "custom_cron", "params": {"cron": "0 9 * * 1-5"}}
    """

    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class ScheduledTaskCreate(BaseModel):
    agent_id: str
    name: str
    schedule: SchedulePayload
    form_values: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ScheduledTaskUpdate(BaseModel):
    name: str | None = None
    schedule: SchedulePayload | None = None
    form_values: dict[str, Any] | None = None
    enabled: bool | None = None


class ScheduledTaskInfo(BaseModel):
    id: str
    agent_id: str
    agent_name: str | None = None
    name: str
    schedule: SchedulePayload
    schedule_description: str  # human string like "每天 09:00"
    form_values: dict[str, Any]
    enabled: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    last_fire_at: datetime | None
    next_fire_at: datetime | None
    last_status: str | None


class ScheduledTaskFireInfo(BaseModel):
    id: str
    scheduled_task_id: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    task_id: str | None
    conversation_id: str | None
    error_message: str | None
