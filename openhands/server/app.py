# IMPORTANT: LEGACY V0 CODE - Deprecated since version 1.0.0, scheduled for removal April 1, 2026
# This file is part of the legacy (V0) implementation of OpenHands and will be removed soon as we complete the migration to V1.
# OpenHands V1 uses the Software Agent SDK for the agentic core and runs a new application server. Please refer to:
#   - V1 agentic core (SDK): https://github.com/OpenHands/software-agent-sdk
#   - V1 application server (in this repo): openhands/app_server/
# Unless you are working on deprecation, please avoid extending this legacy file and consult the V1 codepaths above.
# Tag: Legacy-V0
# This module belongs to the old V0 web server. The V1 application server lives under openhands/app_server/.
import contextlib
import warnings
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi.routing import Mount

with warnings.catch_warnings():
    warnings.simplefilter('ignore')

from fastapi import (
    FastAPI,
    Request,
)
from fastapi.responses import JSONResponse

import openhands.agenthub  # noqa F401 (we import this to get the agents registered)
from openhands.app_server import v1_router
from openhands.app_server.config import get_app_lifespan_service
from openhands.app_server.status.status_router import router as health_router
from openhands.integrations.service_types import AuthenticationError
from openhands.server.routes.conversation import app as conversation_api_router
from openhands.server.routes.feedback import app as feedback_api_router
from openhands.server.routes.files import app as files_api_router
from openhands.server.routes.git import app as git_api_router
from openhands.server.routes.manage_conversations import (
    app as manage_conversation_api_router,
)
from openhands.server.routes.mcp import mcp_server
from openhands.server.routes.public import app as public_api_router
from openhands.server.routes.secrets import app as secrets_router
from openhands.server.routes.security import app as security_api_router
from openhands.server.routes.settings import app as settings_router
from openhands.server.routes.trajectory import app as trajectory_router
from openhands.server.shared import conversation_manager, server_config
from openhands.server.types import AppMode
from openhands.version import get_version

mcp_app = mcp_server.http_app(path='/mcp', stateless_http=True)


def combine_lifespans(*lifespans):
    # Create a combined lifespan to manage multiple session managers
    @contextlib.asynccontextmanager
    async def combined_lifespan(app):
        async with contextlib.AsyncExitStack() as stack:
            for lifespan in lifespans:
                await stack.enter_async_context(lifespan(app))
            yield

    return combined_lifespan


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # >>> CUSTOM: HiClaw — DB migration + seed skills on startup <<<
    try:
        import logging as _logging
        import os as _os
        import sqlite3 as _sqlite3
        from pathlib import Path as _Path

        from custom.skill_mgmt.seed import seed_skills

        # Auto-migrate: add missing columns to conversation_metadata
        _db_path = _os.environ.get(
            'OH_PERSISTENCE_DIR', str(_Path.home() / '.openhands')
        )
        _db_file = str(_Path(_db_path) / 'openhands.db')
        if _Path(_db_file).exists():
            _conn = _sqlite3.connect(_db_file)
            _cur = _conn.cursor()
            _cur.execute('PRAGMA table_info(conversation_metadata)')
            _existing = {r[1] for r in _cur.fetchall()}
            _new_cols = {
                'remote_working_dir': 'TEXT',
                'runtime_mode': 'TEXT',
                'remote_host': 'TEXT',
            }
            for col, typ in _new_cols.items():
                if col not in _existing:
                    _cur.execute(
                        f'ALTER TABLE conversation_metadata ADD COLUMN {col} {typ}'
                    )
                    _logging.getLogger(__name__).info(
                        f'DB migration: added column {col}'
                    )
            _conn.commit()
            _conn.close()

        seed_skills()

        # Auto-import OpenHands extensions to Gitea (public skills mirror)
        _bundle = (
            _Path(__file__).resolve().parent.parent.parent
            / 'agent-worker-manager'
            / 'deps'
            / 'openhands-extensions.bundle'
        )
        if _bundle.exists():
            try:
                import subprocess as _sp

                import httpx as _httpx

                from openhands.server.routes.hiclaw_config import (
                    GITEA_ADMIN_PASSWORD,
                    GITEA_ADMIN_USER,
                    GITEA_URL,
                )

                # Check if repo already exists in Gitea.
                # Intentionally blocking during lifespan startup — the
                # server hasn't started accepting requests yet, so a sync
                # httpx call is fine here and keeps this one-shot import
                # readable. noqa: ASYNC210.
                _check = _httpx.get(  # noqa: ASYNC210
                    f'{GITEA_URL}/api/v1/repos/{GITEA_ADMIN_USER}/extensions',
                    auth=(GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD),
                    timeout=5,
                )
                if _check.status_code == 404:
                    _logging.getLogger(__name__).info(
                        'Importing OpenHands extensions to Gitea...'
                    )
                    # Create repo
                    _httpx.post(  # noqa: ASYNC210
                        f'{GITEA_URL}/api/v1/user/repos',
                        json={'name': 'extensions', 'private': False},
                        auth=(GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD),
                        timeout=10,
                    )
                    # Clone from bundle and push
                    _tmp_dir = _Path('/tmp/_extensions_import')
                    _tmp_dir.mkdir(exist_ok=True)
                    _sp.run(
                        ['git', 'clone', str(_bundle), str(_tmp_dir / 'repo')],
                        capture_output=True,
                        timeout=30,
                    )
                    _gitea_url = f'http://{GITEA_ADMIN_USER}:{GITEA_ADMIN_PASSWORD}@localhost:{GITEA_URL.split(":")[-1]}/{GITEA_ADMIN_USER}/extensions.git'
                    _sp.run(
                        [
                            'git',
                            '-C',
                            str(_tmp_dir / 'repo'),
                            'remote',
                            'add',
                            'gitea',
                            _gitea_url,
                        ],
                        capture_output=True,
                        timeout=5,
                    )
                    _sp.run(
                        ['git', '-C', str(_tmp_dir / 'repo'), 'push', 'gitea', '--all'],
                        capture_output=True,
                        timeout=30,
                    )
                    _sp.run(
                        [
                            'git',
                            '-C',
                            str(_tmp_dir / 'repo'),
                            'push',
                            'gitea',
                            '--tags',
                        ],
                        capture_output=True,
                        timeout=30,
                    )
                    import shutil

                    shutil.rmtree(_tmp_dir, ignore_errors=True)
                    _logging.getLogger(__name__).info(
                        'OpenHands extensions imported to Gitea'
                    )
                else:
                    _logging.getLogger(__name__).debug(
                        'Extensions repo already in Gitea'
                    )
            except Exception as _e:
                _logging.getLogger(__name__).debug(f'Extensions import skipped: {_e}')

    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f'HiClaw startup: {e}')

    # >>> CUSTOM: HiClaw — Scheduled tasks (AsyncIOScheduler lifecycle) <<<
    _scheduled_tasks_shutdown = None
    try:
        from custom.scheduled_tasks.scheduler import (
            shutdown as _sched_shutdown,
        )
        from custom.scheduled_tasks.scheduler import (
            start as _sched_start,
        )

        await _sched_start()
        _scheduled_tasks_shutdown = _sched_shutdown
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f'Scheduled tasks start: {e}')
    # >>> END CUSTOM <<<

    # >>> CUSTOM: HiClaw — Command Scheduler (shell commands, shared APScheduler) <<<
    try:
        from custom.command_scheduler.db import get_cs_db as _cs_db_get
        from custom.command_scheduler.holidays import (
            sync_preset_holidays as _cs_sync_holidays,
        )
        from custom.command_scheduler.scheduler_integration import (
            init as _cs_init,
        )

        _cs_db = await _cs_db_get()
        try:
            await _cs_sync_holidays(_cs_db)
        finally:
            await _cs_db.close()

        await _cs_init()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f'command_scheduler start: {e}')
    # >>> END CUSTOM <<<
    # >>> END CUSTOM <<<
    async with conversation_manager:
        try:
            yield
        finally:
            if _scheduled_tasks_shutdown is not None:
                try:
                    await _scheduled_tasks_shutdown()
                except Exception:
                    pass


lifespans = [_lifespan, mcp_app.lifespan]
app_lifespan_ = get_app_lifespan_service()
if app_lifespan_:
    lifespans.append(app_lifespan_.lifespan)


app = FastAPI(
    title='OpenHands',
    description='OpenHands: Code Less, Make More',
    version=get_version(),
    lifespan=combine_lifespans(*lifespans),
    routes=[Mount(path='/mcp', app=mcp_app)],
)


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(
        status_code=401,
        content=str(exc),
    )


app.include_router(public_api_router)
app.include_router(files_api_router)
app.include_router(security_api_router)
app.include_router(feedback_api_router)
app.include_router(conversation_api_router)
app.include_router(manage_conversation_api_router)
app.include_router(settings_router)
app.include_router(secrets_router)
if server_config.app_mode == AppMode.OPENHANDS:
    app.include_router(git_api_router)
if server_config.enable_v1:
    app.include_router(v1_router.router)
app.include_router(trajectory_router)
app.include_router(health_router)
# >>> CUSTOM: HiClaw <<<
import openhands.server.routes.hiclaw_skills as _hiclaw_skills  # noqa: E402
import openhands.server.routes.runtime_proxy as _runtime_proxy  # noqa: E402

app.include_router(_runtime_proxy.router)
app.include_router(_hiclaw_skills.router)

try:
    from custom.agent_mgmt.router import router as _agent_router
    from custom.agent_mgmt.task_router import router as _task_router
    from custom.chatbot.router import router as _chatbot_router
    from custom.command_scheduler.router import router as _cs_router
    from custom.file_uploads.router import router as _file_uploads_router
    from custom.scheduled_tasks.router import router as _scheduled_tasks_router

    app.include_router(_agent_router, prefix='/api/v1')
    app.include_router(_task_router, prefix='/api/v1')
    app.include_router(_file_uploads_router, prefix='/api/v1')
    app.include_router(_scheduled_tasks_router, prefix='/api/v1')
    app.include_router(_chatbot_router, prefix='/api/v1')
    app.include_router(_cs_router, prefix='/api/v1')
except ImportError:
    pass
# >>> END CUSTOM <<<
