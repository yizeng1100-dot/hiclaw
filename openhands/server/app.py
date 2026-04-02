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
from openhands.integrations.service_types import AuthenticationError
from openhands.server.routes.conversation import app as conversation_api_router
from openhands.server.routes.feedback import app as feedback_api_router
from openhands.server.routes.files import app as files_api_router
from openhands.server.routes.git import app as git_api_router
from openhands.server.routes.health import add_health_endpoints
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
        from custom.skill_mgmt.seed import seed_skills
        import logging as _logging
        import os as _os
        import sqlite3 as _sqlite3
        from pathlib import Path as _Path

        # Auto-migrate: add missing columns to conversation_metadata
        _db_path = _os.environ.get('OH_PERSISTENCE_DIR', str(_Path.home() / '.openhands'))
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
                    _cur.execute(f'ALTER TABLE conversation_metadata ADD COLUMN {col} {typ}')
                    _logging.getLogger(__name__).info(f'DB migration: added column {col}')
            _conn.commit()
            _conn.close()

        seed_skills()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'HiClaw startup: {e}')
    # >>> END CUSTOM <<<
    async with conversation_manager:
        yield


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
# >>> CUSTOM: HiClaw <<<
import openhands.server.routes.hiclaw_skills as _hiclaw_skills  # noqa: E402
import openhands.server.routes.runtime_proxy as _runtime_proxy  # noqa: E402

app.include_router(_runtime_proxy.router)
app.include_router(_hiclaw_skills.router)
# >>> END CUSTOM <<<
add_health_endpoints(app)
