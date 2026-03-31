from fastapi import APIRouter

from openhands.app_server.app_conversation import app_conversation_router
from openhands.app_server.event import event_router
from openhands.app_server.event_callback import (
    webhook_router,
)
from openhands.app_server.pending_messages.pending_message_router import (
    router as pending_message_router,
)
from openhands.app_server.sandbox import sandbox_router, sandbox_spec_router
from openhands.app_server.user import user_router
from openhands.app_server.web_client import web_client_router

# Include routers
router = APIRouter(prefix='/api/v1')
router.include_router(event_router.router)
router.include_router(app_conversation_router.router)
router.include_router(pending_message_router)
router.include_router(sandbox_router.router)
router.include_router(sandbox_spec_router.router)
router.include_router(user_router.router)
router.include_router(webhook_router.router)
router.include_router(web_client_router.router)

# >>> CUSTOM: HiClaw extensions (safe to remove when merging upstream) <<<
try:
    from custom.skill_mgmt.conversation_router import router as _conv_router
    from custom.skill_mgmt.router import router as _skill_router

    router.include_router(_skill_router)
    router.include_router(_conv_router)
except ImportError:
    pass
# >>> END CUSTOM <<<
