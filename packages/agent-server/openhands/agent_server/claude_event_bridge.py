"""Bridge between Claude Agent SDK message types and OpenHands Event types.

Converts Claude SDK streaming messages into OpenHands Events so the
existing WebSocket/PubSub event pipeline can display them in the frontend.

Surface coverage:

| Claude SDK type             | → OpenHands event(s)                              |
|-----------------------------|---------------------------------------------------|
| AssistantMessage (text)     | MessageEvent(role=assistant)                      |
| AssistantMessage (thinking) | wrapped in ```thinking code block in MessageEvent |
| AssistantMessage (tool_use) | ActionEvent (typed Action subclass per tool name) |
| AssistantMessage.error      | AgentErrorEvent                                   |
| AssistantMessage.usage      | ConversationStateUpdateEvent(key='stats', ...)    |
| UserMessage (tool_result)   | ObservationEvent (typed Observation per tool)     |
| SystemMessage(init)         | system MessageEvent — session header              |
| SystemMessage(compact_b...) | Condensation                                      |
| SystemMessage(other)        | logged only                                       |
| TaskStartedMessage          | system MessageEvent — sub-task started            |
| TaskProgressMessage         | system MessageEvent — progress (throttled)        |
| TaskNotificationMessage     | system MessageEvent — done/failed/stopped         |
| RateLimitEvent              | system MessageEvent + (rejected→AgentErrorEvent)  |
| ResultMessage               | system MessageEvent (success summary) OR error;   |
|                             | + ConversationStateUpdateEvent(key='stats')       |

The bridge is *stateful per conversation* via an opaque `stats` dict
threaded through by `ClaudeConversation`. The dict carries:
    - 'model' (str)
    - 'cost' (float)
    - 'token_usage' (dict, accumulated)
    - 'tool_name_by_id' (dict[str, str], so tool_results can be routed
       back to the typed observation matching the original tool call)
    - 'init_emitted' (bool, init header is one-shot)
    - 'last_task_progress_emit' (dict[str, float], throttling)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openhands.sdk.event.base import Event
from openhands.sdk.event.llm_convertible.action import ActionEvent
from openhands.sdk.event.llm_convertible.message import MessageEvent
from openhands.sdk.event.llm_convertible.observation import ObservationEvent

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model context window lookup (used for "Context X%" indicator)
# ---------------------------------------------------------------------------

_CLAUDE_CONTEXT_WINDOWS: dict[str, int] = {
    'claude-opus-4-6': 1_000_000,
    'claude-opus-4-5': 200_000,
    'claude-opus-4-1': 200_000,
    'claude-opus-4': 200_000,
    'claude-sonnet-4-6': 1_000_000,
    'claude-sonnet-4-5': 1_000_000,
    'claude-sonnet-4': 200_000,
    'claude-3-7-sonnet': 200_000,
    'claude-3-5-sonnet': 200_000,
    'claude-haiku-4-5': 200_000,
    'claude-3-5-haiku': 200_000,
}


def _context_window_for_model(model: str) -> int:
    if not model:
        return 200_000
    m = model.lower()
    for prefix, window in _CLAUDE_CONTEXT_WINDOWS.items():
        if m.startswith(prefix):
            return window
    return 200_000


def _text_from_content(content: list[Any]) -> str:
    """Extract text from a list of Claude SDK content blocks or dicts."""
    parts: list[str] = []
    for block in content:
        if hasattr(block, 'text'):
            parts.append(getattr(block, 'text', '') or '')
        elif isinstance(block, dict) and block.get('type') == 'text':
            parts.append(str(block.get('text', '')))
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def claude_message_to_events(
    message: Any,
    *,
    stats: dict[str, Any] | None = None,
) -> list[Event]:
    """Convert a Claude Agent SDK message to one or more OpenHands Events.

    `stats` is an optional mutable dict shared across an entire conversation
    run; the bridge uses it to (a) accumulate token/cost stats, (b) remember
    tool_use_id → tool_name so tool results can be routed back, and
    (c) throttle/dedupe sub-task lifecycle messages.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        RateLimitEvent,
        ResultMessage,
        SystemMessage,
        TaskNotificationMessage,
        TaskProgressMessage,
        TaskStartedMessage,
        UserMessage,
    )

    events: list[Event] = []
    _logger.info(f'[claude-event] received: type={type(message).__name__}')

    # Ensure stats dict has the slots we use, regardless of caller.
    if stats is not None:
        stats.setdefault('tool_name_by_id', {})
        stats.setdefault('last_task_progress_emit', {})

    try:
        # Order matters: Task* messages are SystemMessage subclasses, so
        # check them BEFORE the bare SystemMessage branch.
        if isinstance(message, AssistantMessage):
            events.extend(_convert_assistant_message(message, stats))
            _stats_evt = _maybe_build_stats_event(message, stats)
            if _stats_evt is not None:
                events.append(_stats_evt)
        elif isinstance(message, ResultMessage):
            events.extend(_convert_result_message(message))
            _stats_evt = _maybe_build_stats_event(message, stats)
            if _stats_evt is not None:
                events.append(_stats_evt)
        elif isinstance(message, UserMessage):
            events.extend(_convert_user_message_as_tool_result(message, stats))
        elif isinstance(message, TaskStartedMessage):
            evt = _convert_task_started(message)
            if evt is not None:
                events.append(evt)
        elif isinstance(message, TaskProgressMessage):
            evt = _convert_task_progress(message, stats)
            if evt is not None:
                events.append(evt)
        elif isinstance(message, TaskNotificationMessage):
            evt = _convert_task_notification(message)
            if evt is not None:
                events.append(evt)
        elif isinstance(message, SystemMessage):
            subtype = getattr(message, 'subtype', '')
            _logger.info(f'[claude-event] SystemMessage subtype={subtype}')
            if subtype == 'compact_boundary':
                cond = _build_condensation_event(message)
                if cond is not None:
                    events.append(cond)
            elif subtype == 'init':
                init_evt = _convert_init_system_message(message, stats)
                if init_evt is not None:
                    events.append(init_evt)
            # other subtypes (mcp_status, etc.): log only
        elif isinstance(message, RateLimitEvent):
            events.extend(_convert_rate_limit_event(message))
        else:
            _logger.warning(
                f'[claude-event] Unhandled type: {type(message).__name__}, '
                f'attrs={dir(message)[:20]}'
            )
    except Exception as e:
        _logger.warning(f'Failed to convert Claude message: {e}', exc_info=True)

    return events


# ---------------------------------------------------------------------------
# Stats / token usage
# ---------------------------------------------------------------------------

def _accumulate_claude_usage(
    stats: dict[str, Any],
    usage: dict[str, Any] | None,
    model: str,
) -> dict[str, int]:
    """Merge Claude's per-message usage into the running stats dict."""
    current: dict[str, int] = stats.setdefault('token_usage', {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'cache_read_tokens': 0,
        'cache_write_tokens': 0,
        'reasoning_tokens': 0,
        'per_turn_token': 0,
    })
    if usage:
        prompt = int(usage.get('input_tokens') or 0)
        completion = int(usage.get('output_tokens') or 0)
        cache_read = int(usage.get('cache_read_input_tokens') or 0)
        cache_write = int(usage.get('cache_creation_input_tokens') or 0)
        current['prompt_tokens'] += prompt
        current['completion_tokens'] += completion
        current['cache_read_tokens'] += cache_read
        current['cache_write_tokens'] += cache_write
        current['per_turn_token'] = prompt + completion
    if model:
        stats['model'] = model
    return current


def _maybe_build_stats_event(
    message: Any,
    stats: dict[str, Any] | None,
) -> Event | None:
    """Build a ConversationStateUpdateEvent(key='stats') after each Claude
    message that reports usage or cost, so the frontend's ContextUsageIndicator
    stays in sync.
    """
    if stats is None:
        return None

    usage = getattr(message, 'usage', None)
    model = getattr(message, 'model', '') or stats.get('model', '')
    cost = getattr(message, 'total_cost_usd', None)
    if cost is not None:
        try:
            stats['cost'] = float(cost)
        except (TypeError, ValueError):
            pass

    if usage is None and cost is None:
        return None

    accumulated = _accumulate_claude_usage(stats, usage, model)
    context_window = _context_window_for_model(stats.get('model', ''))

    try:
        from openhands.sdk.event.conversation_state import (
            ConversationStateUpdateEvent,
        )
    except Exception as e:
        _logger.warning(f'Cannot import ConversationStateUpdateEvent: {e}')
        return None

    payload = {
        'usage_to_metrics': {
            'agent': {
                'accumulated_cost': float(stats.get('cost') or 0.0),
                'max_budget_per_task': None,
                'accumulated_token_usage': {
                    'model': stats.get('model', ''),
                    'prompt_tokens': accumulated['prompt_tokens'],
                    'completion_tokens': accumulated['completion_tokens'],
                    'cache_read_tokens': accumulated['cache_read_tokens'],
                    'cache_write_tokens': accumulated['cache_write_tokens'],
                    'reasoning_tokens': accumulated.get('reasoning_tokens', 0),
                    'context_window': context_window,
                    'per_turn_token': accumulated['per_turn_token'],
                    'response_id': '',
                },
            },
        },
    }
    try:
        return ConversationStateUpdateEvent.model_construct(
            source='environment',
            key='stats',
            value=payload,
        )
    except Exception as e:
        _logger.warning(f'Failed to build stats event: {e}', exc_info=True)
        return None


# ---------------------------------------------------------------------------
# System helpers (Condensation, init header)
# ---------------------------------------------------------------------------

def _build_condensation_event(message: Any) -> Event | None:
    """Convert SystemMessage(subtype='compact_boundary') to a Condensation event."""
    try:
        from openhands.sdk.event.condenser import Condensation
    except Exception as e:
        _logger.warning(f'Cannot import Condensation: {e}')
        return None
    data = getattr(message, 'data', None) or {}
    summary = None
    if isinstance(data, dict):
        summary = (
            data.get('summary')
            or data.get('compact_summary')
            or (data.get('compact_metadata') or {}).get('summary')
        )
    try:
        return Condensation.model_construct(
            source='environment',
            forgotten_event_ids=[],
            summary=summary,
            summary_offset=None,
            llm_response_id='',
        )
    except Exception as e:
        _logger.warning(f'Failed to build Condensation event: {e}', exc_info=True)
        return None


def _convert_init_system_message(
    message: Any, stats: dict[str, Any] | None,
) -> Event | None:
    """First time we see SystemMessage(subtype='init'), emit a system message
    showing the model, cwd, MCP servers, and skill count from message.data."""
    if stats is not None:
        if stats.get('init_emitted'):
            return None
        stats['init_emitted'] = True

    data = getattr(message, 'data', None) or {}
    if not isinstance(data, dict):
        return None

    lines: list[str] = ['🚀 Claude session ready']

    model = data.get('model') or (stats.get('model') if stats else '') or ''
    if model:
        lines.append(f'- Model: `{model}`')

    cwd = data.get('cwd') or data.get('working_dir')
    if cwd:
        lines.append(f'- Working dir: `{cwd}`')

    mcp = data.get('mcp_servers') or []
    if isinstance(mcp, list) and mcp:
        names = []
        for srv in mcp:
            if isinstance(srv, dict):
                names.append(str(srv.get('name', '?')))
            else:
                names.append(str(srv))
        lines.append(f'- MCP servers: {", ".join(names)} ({len(names)})')

    tools = data.get('tools') or []
    if isinstance(tools, list) and tools:
        lines.append(f'- Tools available: {len(tools)}')

    slash_commands = data.get('slash_commands') or []
    if isinstance(slash_commands, list) and slash_commands:
        # Only show non-builtin slash commands (HiClaw skills)
        custom = [c for c in slash_commands if not str(c).startswith('/')]
        if custom:
            preview = ', '.join(custom[:8])
            more = f' (+{len(custom) - 8} more)' if len(custom) > 8 else ''
            lines.append(f'- Skills: {preview}{more}')

    return _build_system_message_event('\n'.join(lines))


# ---------------------------------------------------------------------------
# Sub-task lifecycle
# ---------------------------------------------------------------------------

def _convert_task_started(message: Any) -> Event | None:
    task_id = getattr(message, 'task_id', '') or ''
    description = getattr(message, 'description', '') or ''
    short_id = task_id[:8] if task_id else '?'
    return _build_system_message_event(
        f'🤖 Sub-task started — {description} `({short_id})`'
    )


def _convert_task_progress(
    message: Any, stats: dict[str, Any] | None,
) -> Event | None:
    """Emit a sub-task progress note, throttled to one per (task_id, 2 seconds)."""
    task_id = getattr(message, 'task_id', '') or ''
    description = getattr(message, 'description', '') or ''
    usage = getattr(message, 'usage', None) or {}

    if stats is not None:
        last_emit = stats.setdefault('last_task_progress_emit', {})
        now = time.monotonic()
        prev = last_emit.get(task_id, 0.0)
        if now - prev < 2.0:
            return None
        last_emit[task_id] = now

    tool_uses = 0
    total_tokens = 0
    if isinstance(usage, dict):
        tool_uses = int(usage.get('tool_uses') or 0)
        total_tokens = int(usage.get('total_tokens') or 0)

    short_id = task_id[:8] if task_id else '?'
    return _build_system_message_event(
        f'⏳ Sub-task progress — {description} `({short_id})` '
        f'· {tool_uses} tool calls · {total_tokens} tokens'
    )


def _convert_task_notification(message: Any) -> Event | None:
    task_id = getattr(message, 'task_id', '') or ''
    status = getattr(message, 'status', '') or ''
    summary = getattr(message, 'summary', '') or ''
    short_id = task_id[:8] if task_id else '?'

    icon = {
        'completed': '✅',
        'failed': '❌',
        'stopped': '⏹',
    }.get(status, '🔔')

    return _build_system_message_event(
        f'{icon} Sub-task {status} — `({short_id})` {summary}'
    )


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------

def _convert_rate_limit_event(message: Any) -> list[Event]:
    info = getattr(message, 'rate_limit_info', None)
    if info is None:
        return []
    status = getattr(info, 'status', '') or ''
    util = getattr(info, 'utilization', None)
    rate_type = getattr(info, 'rate_limit_type', '') or 'unknown'
    resets_at = getattr(info, 'resets_at', None)

    parts = [f'⚠️ Claude rate limit: **{status}**']
    if util is not None:
        try:
            parts.append(f'{int(float(util) * 100)}% used')
        except (TypeError, ValueError):
            pass
    if rate_type:
        parts.append(f'window={rate_type}')
    if resets_at is not None:
        try:
            from datetime import datetime
            ts = datetime.fromtimestamp(int(resets_at)).strftime('%H:%M:%S')
            parts.append(f'resets at {ts}')
        except Exception:
            pass

    text = ' · '.join(parts)
    events: list[Event] = []
    msg_evt = _build_system_message_event(text)
    if msg_evt is not None:
        events.append(msg_evt)

    if status == 'rejected':
        try:
            from openhands.sdk.event.llm_convertible.observation import (
                AgentErrorEvent,
            )
            events.append(AgentErrorEvent(
                tool_name='claude_agent',
                tool_call_id='',
                error=f'Claude rate limit hit ({rate_type}). {text}',
            ))
        except Exception as e:
            _logger.warning(f'Failed to build AgentErrorEvent: {e}')
    return events


# ---------------------------------------------------------------------------
# Assistant message → MessageEvent + ActionEvent + AgentErrorEvent
# ---------------------------------------------------------------------------

def _convert_assistant_message(
    message: Any, stats: dict[str, Any] | None,
) -> list[Event]:
    """Convert AssistantMessage to OpenHands events.

    The block ordering matters: text that appears BEFORE a tool_use block in
    the same assistant turn is treated as the *thought* for that tool call
    (so the UI shows "Why I'm doing this" above the action). Text that has no
    following tool call in the same turn becomes a standalone MessageEvent.
    """
    from claude_agent_sdk import (
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
    )

    events: list[Event] = []

    # Top-of-message: surface API-side errors (auth, billing, rate limit, etc.).
    err = getattr(message, 'error', None)
    if err is not None:
        try:
            from openhands.sdk.event.llm_convertible.observation import (
                AgentErrorEvent,
            )
            events.append(AgentErrorEvent(
                tool_name='claude_agent',
                tool_call_id='',
                error=f'Claude API error: {err}',
            ))
        except Exception as e:
            _logger.warning(f'Failed to construct AgentErrorEvent: {e}')

    pending_text: list[str] = []
    pending_thinking: list[str] = []

    def _flush_message(force_emit: bool = False) -> None:
        """If there is buffered text/thinking with no upcoming tool call,
        flush it as a standalone MessageEvent."""
        if not (pending_text or pending_thinking):
            return
        text = '\n'.join(pending_text).strip()
        thought_text = '\n'.join(t for t in pending_thinking if t).strip()
        thinking_block = (
            f'```thinking\n{thought_text}\n```\n' if thought_text else ''
        )
        if thinking_block and text:
            visible = f'{thinking_block}\n{text}'
        elif thinking_block:
            visible = thinking_block
        else:
            visible = text
        if visible:
            try:
                from openhands.sdk import Message, TextContent
                events.append(MessageEvent.model_construct(
                    source='agent',
                    llm_message=Message(
                        role='assistant',
                        content=[TextContent(type='text', text=visible)],
                    ),
                    llm_response_id=None,
                ))
            except Exception as e:
                _logger.warning(f'Failed to construct MessageEvent: {e}', exc_info=True)
        pending_text.clear()
        pending_thinking.clear()

    for block in message.content:
        if isinstance(block, ThinkingBlock):
            pending_thinking.append(block.thinking or '')
        elif isinstance(block, TextBlock):
            pending_text.append(block.text or '')
        elif isinstance(block, ToolUseBlock):
            # Use buffered text/thinking as the thought for THIS action.
            thought_text = '\n'.join(pending_text).strip()
            thinking_text = '\n'.join(t for t in pending_thinking if t).strip()
            evt = _tool_use_to_action_event(
                block,
                stats=stats,
                pre_text=thought_text,
                pre_thinking=thinking_text,
            )
            if evt is not None:
                events.append(evt)
            pending_text.clear()
            pending_thinking.clear()
        elif isinstance(block, ToolResultBlock):
            # Tool result inside an assistant message — rare but handle.
            obs = _tool_result_to_observation_event(block, stats)
            if obs is not None:
                events.append(obs)

    # Any trailing text/thinking with no following tool call → standalone msg.
    _flush_message()

    return events


# ---------------------------------------------------------------------------
# Tool USE: ActionEvent
# ---------------------------------------------------------------------------

def _tool_use_to_action_event(
    block: Any,
    *,
    stats: dict[str, Any] | None = None,
    pre_text: str = '',
    pre_thinking: str = '',
) -> ActionEvent | None:
    """Convert a Claude ToolUseBlock to an OpenHands ActionEvent.

    If `pre_text` is provided it becomes the action's `thought` (rendered
    above the action card). `pre_thinking` is wrapped in a ```thinking
    block and prepended to the thought text.
    """
    from openhands.sdk import TextContent
    from openhands.sdk.llm.message import MessageToolCall
    import json as _json
    import uuid as _uuid

    tool_name = block.name
    tool_input = block.input if hasattr(block, 'input') else {}
    tool_call_id = getattr(block, 'id', '') or f'claude-{_uuid.uuid4().hex[:12]}'

    # Remember tool_use_id → tool_name so that the ToolResultBlock that
    # arrives later can be routed back to the correct typed Observation.
    if stats is not None:
        stats.setdefault('tool_name_by_id', {})[tool_call_id] = tool_name

    real_action = _map_claude_tool_to_openhands_action(tool_name, tool_input)
    if real_action is None:
        _logger.warning(f'No mapping for Claude tool {tool_name}, skipping')
        return None

    try:
        _tool_call = MessageToolCall.model_construct(
            id=tool_call_id,
            name=tool_name,
            arguments=_json.dumps(tool_input, ensure_ascii=False)
            if isinstance(tool_input, dict)
            else str(tool_input),
            origin='completion',
        )
    except Exception:
        _tool_call = None  # type: ignore

    # Build thought TextContent list. If there was pre-tool reasoning
    # (thinking + text), include it; thinking goes inside ```thinking so the
    # frontend renders it as a collapsible details element.
    thought_parts: list[Any] = []
    if pre_thinking:
        thought_parts.append(TextContent(
            type='text',
            text=f'```thinking\n{pre_thinking}\n```',
        ))
    if pre_text:
        thought_parts.append(TextContent(type='text', text=pre_text))

    event = ActionEvent.model_construct(
        source='agent',
        thought=thought_parts,
        reasoning_content=None,
        thinking_blocks=[],
        responses_reasoning_item=None,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_call=_tool_call,
        llm_response_id=f'claude-{_uuid.uuid4().hex[:12]}',
        action=real_action,
    )
    return event


def _map_claude_tool_to_openhands_action(tool_name: str, tool_input: dict) -> Any:
    """Map a Claude tool call into a real OpenHands Action subclass.

    OpenHands SDK's discriminated-union serialization (`_serialize_by_kind`)
    requires real Action subclasses — we cannot use ad-hoc BaseModels here.
    Unknown tools fall back to a TerminalAction with an empty `command` and
    a descriptive comment that renders cleanly in the chat UI.
    """
    try:
        from openhands.tools.terminal.definition import TerminalAction
    except ImportError:
        TerminalAction = None  # type: ignore
    try:
        from openhands.tools.file_editor.definition import FileEditorAction
    except ImportError:
        FileEditorAction = None  # type: ignore
    try:
        from openhands.tools.glob.definition import GlobAction
    except ImportError:
        GlobAction = None  # type: ignore
    try:
        from openhands.tools.grep.definition import GrepAction
    except ImportError:
        GrepAction = None  # type: ignore
    try:
        from openhands.tools.task_tracker.definition import (
            TaskItem,
            TaskTrackerAction,
        )
    except ImportError:
        TaskItem = None  # type: ignore
        TaskTrackerAction = None  # type: ignore

    input_dict = tool_input if isinstance(tool_input, dict) else {}

    # Bash-like tools → TerminalAction
    if tool_name in ('Bash', 'Terminal', 'ExecuteBash') and TerminalAction:
        return TerminalAction.model_construct(
            command=str(input_dict.get('command', '')),
            is_input=False,
            timeout=None,
        )

    # File operations → FileEditorAction
    if FileEditorAction and tool_name in ('Read', 'View'):
        return FileEditorAction.model_construct(
            command='view',
            path=str(input_dict.get('file_path') or input_dict.get('path') or ''),
        )
    if FileEditorAction and tool_name == 'Write':
        return FileEditorAction.model_construct(
            command='create',
            path=str(input_dict.get('file_path') or input_dict.get('path') or ''),
            file_text=str(
                input_dict.get('content') or input_dict.get('file_text') or ''
            ),
        )
    if FileEditorAction and tool_name == 'Edit':
        return FileEditorAction.model_construct(
            command='str_replace',
            path=str(input_dict.get('file_path') or input_dict.get('path') or ''),
            old_str=str(
                input_dict.get('old_string') or input_dict.get('old_str') or ''
            ),
            new_str=str(
                input_dict.get('new_string') or input_dict.get('new_str') or ''
            ),
        )

    # Glob → GlobAction
    if GlobAction and tool_name == 'Glob':
        return GlobAction.model_construct(
            pattern=str(input_dict.get('pattern', '')),
            path=str(input_dict.get('path') or '') or None,
        )

    # Grep → GrepAction
    if GrepAction and tool_name == 'Grep':
        return GrepAction.model_construct(
            pattern=str(input_dict.get('pattern', '')),
            path=str(input_dict.get('path') or '') or None,
            include=str(input_dict.get('include') or '') or None,
        )

    # TodoWrite → TaskTrackerAction(plan, ...)
    if TaskTrackerAction and TaskItem and tool_name == 'TodoWrite':
        todos = input_dict.get('todos') or []
        items: list[Any] = []
        if isinstance(todos, list):
            for t in todos:
                if not isinstance(t, dict):
                    continue
                title = (
                    t.get('content')
                    or t.get('activeForm')
                    or t.get('title')
                    or ''
                )
                raw_status = str(t.get('status') or 'pending').lower()
                status = {
                    'pending': 'todo',
                    'todo': 'todo',
                    'in_progress': 'in_progress',
                    'completed': 'done',
                    'done': 'done',
                }.get(raw_status, 'todo')
                try:
                    items.append(TaskItem(title=str(title), status=status))
                except Exception:
                    items.append(TaskItem.model_construct(
                        title=str(title), notes='', status=status,
                    ))
        return TaskTrackerAction.model_construct(
            command='plan',
            task_list=items,
        )

    # Fallback: synthesize a TerminalAction with no command — render as a
    # simple "tool call" card. Carry args as a comment in the command field
    # so the user can still see what was called.
    if TerminalAction:
        import json as _json
        try:
            args_str = _json.dumps(input_dict, ensure_ascii=False)
        except Exception:
            args_str = str(input_dict)
        if len(args_str) > 400:
            args_str = args_str[:400] + '…'
        return TerminalAction.model_construct(
            command=f'# 🔧 {tool_name}({args_str})',
            is_input=False,
            timeout=None,
        )
    return None


# ---------------------------------------------------------------------------
# Tool RESULT: ObservationEvent (typed by tool)
# ---------------------------------------------------------------------------

def _tool_result_to_observation_event(
    block: Any, stats: dict[str, Any] | None,
) -> ObservationEvent | None:
    """Convert a Claude ToolResultBlock to an OpenHands ObservationEvent.

    Looks up the original tool name from `stats['tool_name_by_id']` so the
    result is wrapped in the matching typed Observation subclass — Glob results
    become GlobObservation (rendered with file list), Read results become
    FileEditorObservation (rendered with file viewer), etc.
    """
    import uuid as _uuid

    raw_content = getattr(block, 'content', '')
    if isinstance(raw_content, str):
        content_str = raw_content
    elif isinstance(raw_content, list):
        content_str = _text_from_content(raw_content)
    else:
        content_str = str(raw_content) if raw_content is not None else ''

    if not content_str or not content_str.strip():
        return None

    tool_use_id = getattr(block, 'tool_use_id', '') or f'claude-{_uuid.uuid4().hex[:12]}'
    is_error = bool(getattr(block, 'is_error', False))
    return _build_observation_event(
        stats=stats,
        tool_use_id=tool_use_id,
        content_str=content_str,
        is_error=is_error,
    )


def _dict_tool_result_to_observation_event(
    block: Any, stats: dict[str, Any] | None,
) -> ObservationEvent | None:
    """Defensive: handle dict-form ToolResultBlock from older SDK versions."""
    import uuid as _uuid

    if isinstance(block, dict):
        tool_use_id = block.get('tool_use_id', '')
        content_val = block.get('content', '')
        is_error = bool(block.get('is_error', False))
    else:
        tool_use_id = getattr(block, 'tool_use_id', '')
        content_val = getattr(block, 'content', '')
        is_error = bool(getattr(block, 'is_error', False))

    if isinstance(content_val, list):
        content_str = _text_from_content(content_val)
    else:
        content_str = str(content_val) if content_val is not None else ''

    if not content_str or not content_str.strip():
        return None

    tool_use_id = tool_use_id or f'claude-{_uuid.uuid4().hex[:12]}'
    return _build_observation_event(
        stats=stats,
        tool_use_id=tool_use_id,
        content_str=content_str,
        is_error=is_error,
    )


def _build_observation_event(
    *,
    stats: dict[str, Any] | None,
    tool_use_id: str,
    content_str: str,
    is_error: bool,
) -> ObservationEvent | None:
    """Resolve original tool name from stats and dispatch to the right
    typed Observation builder."""
    tool_name = ''
    if stats is not None:
        tool_name = stats.get('tool_name_by_id', {}).get(tool_use_id, '') or ''

    obs = _build_typed_observation(tool_name, content_str, is_error)
    if obs is None:
        return None

    return ObservationEvent.model_construct(
        source='environment',
        tool_name=tool_name or 'Terminal',
        tool_call_id=tool_use_id,
        action_id=tool_use_id,
        observation=obs,
    )


def _build_typed_observation(
    tool_name: str, content: str, is_error: bool,
) -> Any:
    """Construct the Observation subclass that matches the original tool."""
    if tool_name in ('Read', 'View', 'Write', 'Edit'):
        return _build_file_editor_observation(tool_name, content, is_error)
    if tool_name == 'Glob':
        return _build_glob_observation(content, is_error)
    if tool_name == 'Grep':
        return _build_grep_observation(content, is_error)
    if tool_name == 'TodoWrite':
        return _build_task_tracker_observation(content, is_error)
    # Bash, Terminal, ExecuteBash, plus any unknown tool falls back here.
    return _build_terminal_observation(content, is_error)


def _build_terminal_observation(content: str, is_error: bool = False) -> Any:
    """TerminalObservation for Bash/Terminal results.

    Frontend reads `observation.content` (list[TextContent]), not `output`,
    so we MUST populate the `content` list.
    """
    try:
        from openhands.sdk.llm.message import TextContent
        from openhands.tools.terminal.definition import (
            CmdOutputMetadata,
            TerminalObservation,
        )
        return TerminalObservation.model_construct(
            content=[TextContent(type='text', text=content)],
            command='',
            exit_code=1 if is_error else 0,
            metadata=CmdOutputMetadata(),
            is_error=is_error,
        )
    except Exception as e:
        _logger.warning(f'Failed to build TerminalObservation: {e}', exc_info=True)
        return None


def _build_file_editor_observation(
    tool_name: str, content: str, is_error: bool,
) -> Any:
    """FileEditorObservation for Read/Write/Edit results."""
    try:
        from openhands.sdk.llm.message import TextContent
        from openhands.tools.file_editor.definition import FileEditorObservation
    except Exception as e:
        _logger.warning(f'Failed to import FileEditorObservation: {e}')
        return _build_terminal_observation(content, is_error)

    command_map = {
        'Read': 'view',
        'View': 'view',
        'Write': 'create',
        'Edit': 'str_replace',
    }
    command = command_map.get(tool_name, 'view')

    try:
        return FileEditorObservation.model_construct(
            content=[TextContent(type='text', text=content)],
            command=command,
            path=None,
            prev_exist=True,
            old_content=None,
            new_content=None,
            is_error=is_error,
        )
    except Exception as e:
        _logger.warning(f'Failed to build FileEditorObservation: {e}', exc_info=True)
        return _build_terminal_observation(content, is_error)


def _build_glob_observation(content: str, is_error: bool) -> Any:
    """GlobObservation for Glob results.

    Claude Glob returns text like:
      /path/a.py
      /path/b.py
      ...
    We split on newlines into the `files` list. The frontend renderer in
    `get-observation-content.ts` reads observation.files plus content.
    """
    try:
        from openhands.sdk.llm.message import TextContent
        from openhands.tools.glob.definition import GlobObservation
    except Exception as e:
        _logger.warning(f'Failed to import GlobObservation: {e}')
        return _build_terminal_observation(content, is_error)

    files: list[str] = []
    truncated = False
    if not is_error:
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            # Some Claude Glob outputs end with a "(truncated)" hint
            if 'truncated' in line.lower():
                truncated = True
                continue
            files.append(line)

    try:
        return GlobObservation.model_construct(
            content=[TextContent(type='text', text=content)],
            files=files,
            pattern='',
            search_path='',
            truncated=truncated,
            is_error=is_error,
        )
    except Exception as e:
        _logger.warning(f'Failed to build GlobObservation: {e}', exc_info=True)
        return _build_terminal_observation(content, is_error)


def _build_grep_observation(content: str, is_error: bool) -> Any:
    """GrepObservation for Grep results."""
    try:
        from openhands.sdk.llm.message import TextContent
        from openhands.tools.grep.definition import GrepObservation
    except Exception as e:
        _logger.warning(f'Failed to import GrepObservation: {e}')
        return _build_terminal_observation(content, is_error)

    matches: list[str] = []
    truncated = False
    if not is_error:
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if 'truncated' in line.lower():
                truncated = True
                continue
            matches.append(line)

    try:
        return GrepObservation.model_construct(
            content=[TextContent(type='text', text=content)],
            matches=matches,
            pattern='',
            search_path='',
            include_pattern=None,
            truncated=truncated,
            is_error=is_error,
        )
    except Exception as e:
        _logger.warning(f'Failed to build GrepObservation: {e}', exc_info=True)
        return _build_terminal_observation(content, is_error)


def _build_task_tracker_observation(content: str, is_error: bool) -> Any:
    """TaskTrackerObservation for TodoWrite results.

    TodoWrite confirms updates with a freeform string, so we just store the
    content; task_list is empty (the *action* carries the actual list).
    """
    try:
        from openhands.sdk.llm.message import TextContent
        from openhands.tools.task_tracker.definition import TaskTrackerObservation
    except Exception as e:
        _logger.warning(f'Failed to import TaskTrackerObservation: {e}')
        return _build_terminal_observation(content, is_error)

    try:
        return TaskTrackerObservation.model_construct(
            content=[TextContent(type='text', text=content)],
            command='plan',
            task_list=[],
            is_error=is_error,
        )
    except Exception as e:
        _logger.warning(
            f'Failed to build TaskTrackerObservation: {e}', exc_info=True,
        )
        return _build_terminal_observation(content, is_error)


# ---------------------------------------------------------------------------
# UserMessage (carries tool results)
# ---------------------------------------------------------------------------

def _convert_user_message_as_tool_result(
    message: Any, stats: dict[str, Any] | None,
) -> list[Event]:
    """Convert a Claude UserMessage (which carries tool execution results) to
    ObservationEvents."""
    try:
        from claude_agent_sdk import ToolResultBlock
    except ImportError:
        ToolResultBlock = None  # type: ignore

    events: list[Event] = []
    content = getattr(message, 'content', None)

    if isinstance(content, list):
        for block in content:
            if ToolResultBlock is not None and isinstance(block, ToolResultBlock):
                evt = _tool_result_to_observation_event(block, stats)
                if evt is not None:
                    events.append(evt)
                continue
            block_type = getattr(block, 'type', None) or (
                block.get('type') if isinstance(block, dict) else None
            )
            if block_type == 'tool_result':
                evt = _dict_tool_result_to_observation_event(block, stats)
                if evt is not None:
                    events.append(evt)
    elif isinstance(content, str) and content.strip():
        # Plain string tool result with no block wrapper.
        import uuid as _uuid
        tool_call_id = (
            getattr(message, 'parent_tool_use_id', '')
            or f'claude-{_uuid.uuid4().hex[:12]}'
        )
        evt = _build_observation_event(
            stats=stats,
            tool_use_id=tool_call_id,
            content_str=content,
            is_error=False,
        )
        if evt is not None:
            events.append(evt)

    _logger.info(
        f'[claude-event] UserMessage → {len(events)} tool-result events'
    )
    return events


# ---------------------------------------------------------------------------
# ResultMessage
# ---------------------------------------------------------------------------

def _convert_result_message(message: Any) -> list[Event]:
    """Convert ResultMessage to either an error event or a success summary."""
    subtype = getattr(message, 'subtype', '?')
    is_error = getattr(message, 'is_error', False)
    num_turns = getattr(message, 'num_turns', 0)
    stop_reason = getattr(message, 'stop_reason', None)
    duration_ms = getattr(message, 'duration_ms', 0)
    cost = getattr(message, 'total_cost_usd', 0) or 0.0
    permission_denials = getattr(message, 'permission_denials', None) or []
    errors = getattr(message, 'errors', None) or []

    # Failure path — emit AgentErrorEvent with diagnostics.
    if is_error or (cost == 0.0 and num_turns == 0):
        _logger.warning(
            f'Claude task finished WITHOUT success: '
            f'subtype={subtype}, is_error={is_error}, num_turns={num_turns}, '
            f'stop_reason={stop_reason}, duration_ms={duration_ms}, cost=${cost:.4f}'
        )
        try:
            from openhands.sdk.event.llm_convertible.observation import (
                AgentErrorEvent,
            )
            return [AgentErrorEvent(
                tool_name='claude_agent',
                tool_call_id='',
                error=(
                    f'Claude task ended with no usable output '
                    f'(subtype={subtype}, is_error={is_error}, turns={num_turns}). '
                    f'Likely causes: API key invalid, network blocked, '
                    f'or the request was silently rejected.'
                ),
            )]
        except Exception:
            return []

    # Success path — emit a system message summary. Show tokens (what the
    # user wants to see) instead of USD cost (which is meaningless when
    # running against internal gateways like qianfan that don't bill in USD).
    usage = getattr(message, 'usage', None) or {}
    input_tokens = 0
    output_tokens = 0
    if isinstance(usage, dict):
        input_tokens = int(usage.get('input_tokens') or 0)
        output_tokens = int(usage.get('output_tokens') or 0)
    total_tokens = input_tokens + output_tokens

    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f'{n / 1_000_000:.1f}M'
        if n >= 1_000:
            return f'{n / 1_000:.1f}k'
        return str(n)

    _logger.info(
        f'Claude task finished: subtype={subtype}, turns={num_turns}, '
        f'duration={duration_ms}ms, tokens={total_tokens}, cost=${cost:.4f}'
    )
    duration_s = (duration_ms or 0) / 1000.0
    summary_line = (
        f'✓ Done in {duration_s:.1f}s · {num_turns} turns · '
        f'{_fmt_tokens(total_tokens)} tokens '
        f'(in {_fmt_tokens(input_tokens)} / out {_fmt_tokens(output_tokens)})'
    )
    if stop_reason:
        summary_line += f' · stop={stop_reason}'

    extra_bits: list[str] = []
    if permission_denials:
        extra_bits.append(f'{len(permission_denials)} tool denials')
    if errors:
        extra_bits.append(f'{len(errors)} non-fatal errors')
    text = summary_line
    if extra_bits:
        text += '\n⚠️ ' + ', '.join(extra_bits)

    msg_evt = _build_system_message_event(text)
    return [msg_evt] if msg_evt is not None else []


# ---------------------------------------------------------------------------
# Internal helper: build a system-side MessageEvent
# ---------------------------------------------------------------------------

def _build_system_message_event(text: str) -> Event | None:
    """Build a MessageEvent that the frontend will render as a chat bubble.

    We use role='user' with source='environment' because the OpenHands v1
    frontend's user-assistant renderer treats environment-source messages
    as system info; this avoids needing a dedicated SystemMessage event type.
    """
    if not text:
        return None
    try:
        from openhands.sdk import Message, TextContent
        return MessageEvent.model_construct(
            source='environment',
            llm_message=Message(
                role='user',
                content=[TextContent(type='text', text=text)],
            ),
            llm_response_id=None,
        )
    except Exception as e:
        _logger.warning(f'Failed to build system MessageEvent: {e}', exc_info=True)
        return None
