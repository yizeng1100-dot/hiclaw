"""Thin wrapper that gives command_scheduler its own session factory alias.

Backed by the same openhands.db SQLite used by scheduled_tasks,
so tables live side-by-side.
"""

from __future__ import annotations

from custom.agent_mgmt.db import get_agent_db as get_cs_db  # noqa: F401
