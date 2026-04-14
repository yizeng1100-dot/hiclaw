"""Streaming multi-turn executor.

Emits events as the LLM generates tokens and calls tools. Each loop
turn:

  1. Call ``stream_completion`` with the full message history.
  2. Accumulate streamed deltas:
       - text deltas → ``token`` events to the caller
       - tool_call deltas → buffered until the turn finishes
  3. When the stream ends with ``finish_reason == 'tool_calls'``,
     execute each tool, emit ``tool_call`` and ``tool_result``
     events, append a matching tool message to the history, and loop.
  4. When the stream ends with any other finish reason (usually
     ``stop``) or turn cap is hit, emit ``done`` and return.

Tool execution errors never raise out of this generator — they get
serialized into tool result messages so the LLM can see them and
potentially recover.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from custom.chatbot.llm_client import ChatbotError, stream_completion
from custom.chatbot.system_prompt import get_system_prompt
from custom.chatbot.tools import dumps, openai_tools_spec, run_tool

_logger = logging.getLogger(__name__)

_MAX_TURNS = 8


def _strip_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove any incoming system messages so we can prepend our own."""
    return [m for m in messages if m.get('role') != 'system']


def _accumulate_tool_call_deltas(
    buffer: dict[int, dict[str, Any]], delta_tool_calls: list[Any]
) -> None:
    """Merge a streamed tool_call delta chunk into ``buffer`` in place.

    OpenAI / litellm streams tool calls as a list of partial objects
    (one per index). Each chunk carries some of id / name / arguments;
    the full call is reconstructed by accumulating across chunks.
    """
    for part in delta_tool_calls:
        # litellm returns dict-like or object — normalise to dict
        if hasattr(part, 'model_dump'):
            part = part.model_dump()
        elif not isinstance(part, dict):
            part = dict(part)
        idx = part.get('index', 0)
        slot = buffer.setdefault(
            idx,
            {
                'id': None,
                'type': 'function',
                'function': {'name': '', 'arguments': ''},
            },
        )
        if part.get('id'):
            slot['id'] = part['id']
        fn = part.get('function') or {}
        if fn.get('name'):
            slot['function']['name'] = fn['name']
        if fn.get('arguments'):
            slot['function']['arguments'] += fn['arguments']


async def run_chat(
    messages: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Drive a streamed multi-turn chat with tool calling.

    Yields events of the shape:

        {"type": "token",        "text": "..."}
        {"type": "assistant_end", "message": {...}}
        {"type": "tool_call",    "call": {id, name, arguments}}
        {"type": "tool_result",  "call_id": "...", "result": <json>}
        {"type": "done",         "messages": [...full history...]}
        {"type": "error",        "message": "..."}
    """
    history: list[dict[str, Any]] = [
        {'role': 'system', 'content': get_system_prompt()},
        *_strip_system_messages(messages),
    ]

    for _turn in range(_MAX_TURNS):
        assistant_text = ''
        tool_call_buf: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None

        try:
            async for chunk in stream_completion(
                history, tools=openai_tools_spec()
            ):
                try:
                    choice = chunk.choices[0]
                except Exception:
                    continue
                delta = getattr(choice, 'delta', None) or {}
                # litellm deltas can be either objects or plain dicts;
                # normalise.
                if not isinstance(delta, dict):
                    try:
                        delta = delta.model_dump()
                    except Exception:
                        delta = {
                            'content': getattr(delta, 'content', None),
                            'tool_calls': getattr(delta, 'tool_calls', None),
                        }

                if delta.get('content'):
                    piece = delta['content']
                    assistant_text += piece
                    yield {'type': 'token', 'text': piece}

                if delta.get('tool_calls'):
                    _accumulate_tool_call_deltas(
                        tool_call_buf, delta['tool_calls']
                    )

                fr = getattr(choice, 'finish_reason', None)
                if fr:
                    finish_reason = fr
        except ChatbotError as e:
            yield {'type': 'error', 'message': str(e)}
            return
        except Exception as e:
            _logger.exception('chatbot llm stream failed')
            yield {'type': 'error', 'message': f'LLM 请求失败: {e}'}
            return

        tool_calls = [tool_call_buf[i] for i in sorted(tool_call_buf)]
        assistant_message: dict[str, Any] = {
            'role': 'assistant',
            'content': assistant_text or None,
        }
        if tool_calls:
            assistant_message['tool_calls'] = tool_calls
        history.append(assistant_message)
        yield {'type': 'assistant_end', 'message': assistant_message}

        if not tool_calls:
            # Normal end of turn. Done.
            break

        # Execute tool calls, emit events, append tool result messages.
        for call in tool_calls:
            call_id = call.get('id') or ''
            fn = call.get('function') or {}
            name = fn.get('name') or ''
            args_raw = fn.get('arguments') or '{}'
            try:
                args = json.loads(args_raw) if args_raw else {}
            except Exception:
                args = {}

            yield {
                'type': 'tool_call',
                'call': {'id': call_id, 'name': name, 'arguments': args},
            }

            result = await run_tool(name, args)

            yield {
                'type': 'tool_result',
                'call_id': call_id,
                'name': name,
                'result': result,
            }

            history.append(
                {
                    'role': 'tool',
                    'tool_call_id': call_id,
                    'name': name,
                    'content': dumps(result),
                }
            )

        # Loop back to let the LLM respond to tool results.
    else:
        yield {
            'type': 'error',
            'message': f'chat loop hit max turn cap ({_MAX_TURNS})',
        }

    yield {'type': 'done', 'messages': history[1:]}  # drop system msg from reply
