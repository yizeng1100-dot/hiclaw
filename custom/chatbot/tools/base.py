"""Tool protocol + registry + OpenAI function-calling spec converter.

A Tool is a stateless async callable with a stable name, a
natural-language description, and a JSON schema for its parameters.
The executor exposes all registered tools to the LLM via the OpenAI
function-calling format; when the LLM picks one, the executor
dispatches to ``run_tool(name, args)`` which calls the tool's ``run``
method.

All tool failures are converted to ``{"error": "..."}`` dicts so the
LLM can read and react to them rather than the executor crashing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

_logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    # OpenAI JSON schema for parameters, e.g.:
    #   {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any]], Awaitable[Any]]


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in _REGISTRY:
        _logger.warning(f'Tool {tool.name!r} is being re-registered')
    _REGISTRY[tool.name] = tool
    return tool


def openai_tools_spec() -> list[dict[str, Any]]:
    """Return the registry in OpenAI function-calling format.

    Passed to litellm as the ``tools=`` kwarg.
    """
    return [
        {
            'type': 'function',
            'function': {
                'name': t.name,
                'description': t.description,
                'parameters': t.parameters,
            },
        }
        for t in _REGISTRY.values()
    ]


async def run_tool(name: str, args: dict[str, Any]) -> Any:
    """Dispatch a tool call. Never raises — returns ``{"error": ...}``."""
    tool = _REGISTRY.get(name)
    if tool is None:
        return {'error': f'unknown tool: {name}'}
    try:
        return await tool.run(args or {})
    except Exception as e:
        _logger.exception(f'Tool {name} raised')
        return {'error': f'{type(e).__name__}: {e}'}


def dumps(value: Any) -> str:
    """JSON-serialize a tool result for injection into a tool message.

    Keeps non-JSON-serializable values readable (datetimes, UUIDs, ...).
    """
    return json.dumps(value, ensure_ascii=False, default=str)
