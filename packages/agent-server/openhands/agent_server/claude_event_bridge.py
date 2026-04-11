"""Bridge between Claude Agent SDK message types and OpenHands Event types.

Converts Claude SDK streaming messages into OpenHands Events so the
existing WebSocket/PubSub event pipeline can display them in the frontend.
"""

from __future__ import annotations

import logging
from typing import Any

from openhands.sdk.event.base import Event
from openhands.sdk.event.llm_convertible.action import ActionEvent
from openhands.sdk.event.llm_convertible.message import MessageEvent
from openhands.sdk.event.llm_convertible.observation import ObservationEvent

_logger = logging.getLogger(__name__)


def _text_from_content(content: list[Any]) -> str:
    """Extract text from Claude SDK content blocks."""
    parts = []
    for block in content:
        if hasattr(block, 'text'):
            parts.append(block.text)
        elif hasattr(block, 'type') and block.type == 'text':
            parts.append(getattr(block, 'text', ''))
    return '\n'.join(parts)


def _get_thought_text(content: list[Any]) -> str | None:
    """Extract thinking/reasoning text from content blocks."""
    for block in content:
        if hasattr(block, 'type') and block.type == 'thinking':
            return getattr(block, 'thinking', '') or getattr(block, 'text', '')
    return None


def claude_message_to_events(message: Any) -> list[Event]:
    """Convert a Claude Agent SDK message to one or more OpenHands Events.

    Supported message types (from claude_agent_sdk.types):
    - AssistantMessage: Claude's text response + tool calls
    - SystemMessage: System notifications
    - ResultMessage: Task completion signal
    - UserMessage: Echo of user messages
    - TaskStartedMessage / TaskProgressMessage / TaskNotificationMessage: Task events

    Returns a list of Events (may be empty for unsupported message types).
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ResultMessage,
        SystemMessage,
        TaskNotificationMessage,
        UserMessage,
    )

    events: list[Event] = []

    try:
        if isinstance(message, AssistantMessage):
            events.extend(_convert_assistant_message(message))
        elif isinstance(message, ResultMessage):
            events.extend(_convert_result_message(message))
        elif isinstance(message, UserMessage):
            # Usually we don't need to emit user messages as events
            # (they're already in the conversation)
            pass
        elif isinstance(message, SystemMessage):
            _logger.debug(f'Claude system message: {message}')
        elif isinstance(message, TaskNotificationMessage):
            _logger.info(f'Claude task notification: status={message.status}')
        else:
            _logger.debug(f'Unhandled Claude message type: {type(message).__name__}')
    except Exception as e:
        _logger.warning(f'Failed to convert Claude message: {e}', exc_info=True)

    return events


def _convert_assistant_message(message: Any) -> list[Event]:
    """Convert AssistantMessage to OpenHands Events."""
    from claude_agent_sdk import TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock

    events: list[Event] = []
    text_parts = []
    thought = None

    for block in message.content:
        if isinstance(block, ThinkingBlock):
            thought = block.thinking
        elif isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            # Tool call from Claude
            events.append(_tool_use_to_action_event(block))
        elif isinstance(block, ToolResultBlock):
            # Tool result
            events.append(_tool_result_to_observation_event(block))

    # Emit text response as MessageEvent
    if text_parts:
        from openhands.sdk import Message, TextContent

        text = '\n'.join(text_parts)
        msg_event = MessageEvent(
            source='agent',
            llm_message=Message(
                role='assistant',
                content=[TextContent(type='text', text=text)],
            ),
        )
        if thought:
            msg_event.thought = thought
        events.insert(0, msg_event)  # Text before tool calls

    return events


def _tool_use_to_action_event(block: Any) -> ActionEvent:
    """Convert a Claude ToolUseBlock to an OpenHands ActionEvent."""
    tool_name = block.name
    tool_input = block.input if hasattr(block, 'input') else {}

    # Map Claude tool names to OpenHands action descriptions
    summary = f'[Claude] {tool_name}'
    if tool_name == 'Bash' and isinstance(tool_input, dict):
        cmd = tool_input.get('command', '')
        summary = f'$ {cmd[:100]}'
    elif tool_name in ('Read', 'Write', 'Edit') and isinstance(tool_input, dict):
        path = tool_input.get('file_path', tool_input.get('path', ''))
        summary = f'{tool_name}: {path}'

    # Create a generic ActionEvent
    from openhands.sdk.tool.builtins.finish import FinishAction

    # Use a simple action wrapper
    event = ActionEvent(
        tool_name=tool_name,
        tool_call_id=getattr(block, 'id', ''),
        action=_make_generic_action(tool_name, tool_input),
        thought=None,
        summary=summary,
    )
    return event


def _tool_result_to_observation_event(block: Any) -> ObservationEvent:
    """Convert a Claude ToolResultBlock to an OpenHands ObservationEvent."""
    content = ''
    if hasattr(block, 'content'):
        if isinstance(block.content, str):
            content = block.content
        elif isinstance(block.content, list):
            content = _text_from_content(block.content)

    from openhands.sdk.tool import Observation

    event = ObservationEvent(
        tool_call_id=getattr(block, 'tool_use_id', ''),
        observation=_make_generic_observation(content),
    )
    return event


def _convert_result_message(message: Any) -> list[Event]:
    """Convert ResultMessage to a finish event."""
    # ResultMessage means Claude finished the task
    _logger.info(
        f'Claude task finished: cost=${getattr(message, "total_cost_usd", 0):.4f}'
    )
    # We don't emit a FinishAction event here because the conversation
    # status change is handled by ClaudeConversation.run()
    return []


def _make_generic_action(tool_name: str, tool_input: dict) -> Any:
    """Create a generic Action for display purposes."""
    # For now, return a simple dict-like object that can be serialized
    # The frontend mainly needs: tool_name, summary, and the input params
    from pydantic import BaseModel

    class GenericAction(BaseModel):
        kind: str = tool_name
        params: dict = tool_input

    return GenericAction(kind=tool_name, params=tool_input)


def _make_generic_observation(content: str) -> Any:
    """Create a generic Observation for display purposes."""
    from pydantic import BaseModel

    class GenericObservation(BaseModel):
        kind: str = 'GenericObservation'
        content: str = content

    return GenericObservation(content=content)
