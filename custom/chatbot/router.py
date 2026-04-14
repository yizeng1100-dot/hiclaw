"""FastAPI router for the HiClaw chatbot.

Single SSE streaming endpoint: ``POST /api/v1/chat/stream``. The
client POSTs a message history; the server pipes the executor's
event stream back as Server-Sent Events.

Event envelope (one ``data:`` line per event, JSON-encoded):

    {"type": "token",         "text": "..."}
    {"type": "assistant_end", "message": {...}}
    {"type": "tool_call",     "call": {id, name, arguments}}
    {"type": "tool_result",   "call_id, name, result}
    {"type": "done",          "messages": [...]}
    {"type": "error",         "message": "..."}

Frontend uses a fetch-stream reader (not EventSource, because POST +
custom headers) to consume these.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from custom.chatbot.executor import run_chat

_logger = logging.getLogger(__name__)

router = APIRouter(prefix='/chat', tags=['Chatbot'])


class ChatMessage(BaseModel):
    role: str
    content: Any = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


@router.post('/stream')
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    """Stream chat events for the given message history.

    sse_starlette wraps our async generator into proper SSE framing
    (``data: <json>\\n\\n``). Each event from the executor becomes
    one SSE message.
    """
    messages = [m.model_dump(exclude_none=True) for m in request.messages]

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        try:
            async for evt in run_chat(messages):
                yield {'data': json.dumps(evt, ensure_ascii=False, default=str)}
        except Exception as e:
            _logger.exception('chatbot stream crashed')
            yield {
                'data': json.dumps(
                    {'type': 'error', 'message': f'stream crashed: {e}'},
                    ensure_ascii=False,
                )
            }

    return EventSourceResponse(event_source())
