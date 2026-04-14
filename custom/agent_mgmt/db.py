"""Database session management for agent/task management.

Uses the same SQLite database as OpenHands (~/.openhands/openhands.db).
Creates tables on first use if they don't exist.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from custom.agent_mgmt.models import StoredAgent, AgentSkillLink, AgentFavorite, StoredTask
from custom.scheduled_tasks.models import StoredScheduledTask, StoredScheduledTaskFire
from openhands.app_server.utils.sql_utils import Base

_engine = None
_session_factory = None
_tables_created = False


def _get_db_url() -> str:
    persistence_dir = os.environ.get('OH_PERSISTENCE_DIR', str(Path.home() / '.openhands'))
    db_path = Path(persistence_dir) / 'openhands.db'
    return f'sqlite+aiosqlite:///{db_path}'


async def _ensure_tables():
    global _engine, _session_factory, _tables_created

    if _engine is None:
        _engine = create_async_engine(_get_db_url(), echo=False)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    if not _tables_created:
        async with _engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[
                    StoredAgent.__table__,
                    AgentSkillLink.__table__,
                    AgentFavorite.__table__,
                    StoredTask.__table__,
                    StoredScheduledTask.__table__,
                    StoredScheduledTaskFire.__table__,
                ],
            )
        _tables_created = True

        # Seed built-in agents on first startup
        session = _session_factory()
        try:
            from custom.agent_mgmt.seed import seed_perf_agent, seed_kernel_diff_agent, seed_render_agent
            await seed_perf_agent(session)
            await seed_kernel_diff_agent(session)
            await seed_render_agent(session)
        finally:
            await session.close()


async def get_agent_db() -> AsyncSession:
    await _ensure_tables()
    assert _session_factory is not None
    return _session_factory()
