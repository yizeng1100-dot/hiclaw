"""The actual ``fire_schedule(id)`` coroutine the scheduler invokes.

Replicates the frontend generic-agent launch path on the server side:

    agent = AgentService.get_agent(id)     # pull skill-driven submit_message template
    message = interpolate(submit_message, schedule.form_values)
    task_id = TaskService.create_task(agent_id=...)
    conv = POST /api/v1/app-conversations with initial_message=message
    TaskService.start_task(task_id, conv.id)

Everything is wrapped in a try/finally so the fire history row is ALWAYS
finalized to either ``success`` or ``failed`` — the scheduler never
sees an in-flight "running" row left behind after a crash.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from custom.agent_mgmt.db import get_agent_db
from custom.agent_mgmt.service import AgentService
from custom.agent_mgmt.task_service import TaskService
from custom.scheduled_tasks.notifier import NotifyFire, get_notifier
from custom.scheduled_tasks.service import ScheduledTaskService

_logger = logging.getLogger(__name__)

_TEMPLATE_VAR = re.compile(r'\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}')
_LEFTOVER = re.compile(r'\{\{[^}]+\}\}')

# Loopback into our own backend. lifespan guarantees uvicorn is on 12000.
_LOCAL_API = 'http://127.0.0.1:12000'


def _interpolate(template: str, values: dict[str, Any]) -> str:
    """Replace ``{{key}}`` with ``values[key]`` and strip the rest.

    Mirrors the client-side DynamicFormPanel substitution so a schedule
    fires with exactly the same prompt a manual launch would produce.
    """
    if not template:
        return template

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return str(values[key])
        return match.group(0)  # leave it for the leftover sweep

    message = _TEMPLATE_VAR.sub(repl, template)
    message = _LEFTOVER.sub('', message)
    return message.strip()


async def _resolve_submit_message(
    db, agent_id: str, form_values: dict[str, Any]
) -> str:
    """Load the agent's skill-merged config_json and do template substitution.

    The bridge overlay that merges ``input_form`` / ``submit_message``
    from the skill frontmatter lives in the HTTP handler, not in the
    service layer, so we go through HTTP loopback to reuse it.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f'{_LOCAL_API}/api/v1/agents/{agent_id}')
        resp.raise_for_status()
        data = resp.json()

    cfg_raw = data.get('config_json') or '{}'
    try:
        cfg = json.loads(cfg_raw) if isinstance(cfg_raw, str) else cfg_raw
    except Exception:
        cfg = {}

    input_form = cfg.get('input_form') or {}
    template = input_form.get('submit_message') or ''
    if not template:
        # Agent without a submit_message template — fall back to the
        # agent's system_prompt, same as handleSelectAgent does for
        # bare agents (interactive-chat-box.tsx:75-77).
        sys_prompt = data.get('system_prompt') or ''
        if sys_prompt:
            return f'[Agent: {data.get("name", "")}]\n\n{sys_prompt}'
        return f'Execute Agent: {data.get("name", "")}'

    return _interpolate(template, form_values)


async def _create_v1_conversation(message: str) -> tuple[str, str]:
    """POST /api/v1/app-conversations to launch a v1 conv with an initial user message.

    Returns (start_task_id, task_prefix_conversation_id). The start_task
    is what the task-start endpoint expects as ``conversation_id``, i.e.
    ``task-<startId>``.

    Only sets the fields we actually need — passing explicit ``null``
    for enum-typed fields (like ``agent_type``) fails pydantic
    validation. All other fields default to sensible values on the
    server side.
    """
    body = {
        'agent_type': 'default',
        'initial_message': {
            'role': 'user',
            'content': [{'type': 'text', 'text': message}],
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f'{_LOCAL_API}/api/v1/app-conversations',
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    start_task_id = data.get('id') or data.get('task_id')
    if not start_task_id:
        raise RuntimeError(f'app-conversations response missing id: {data}')
    return str(start_task_id), f'task-{start_task_id}'


async def fire_schedule(schedule_id: str) -> None:
    """Entrypoint called by APScheduler at each tick.

    Owns the full lifecycle of one fire: insert fire row, run launch,
    mark success/failed, notify. NEVER raises — a schedule fire should
    never crash the scheduler process.
    """
    _logger.info('scheduled-task fire start: schedule_id=%s', schedule_id)

    # Each fire uses its own DB session so misfire bursts don't share
    # cursor state.
    db = await get_agent_db()
    svc = ScheduledTaskService(db)

    fire_id: str | None = None
    notify_payload: NotifyFire | None = None
    try:
        schedule = await svc.get_schedule(schedule_id)
        if schedule is None:
            _logger.warning('fire skipped: schedule %s not found', schedule_id)
            return
        if not schedule.enabled:
            _logger.info('fire skipped: schedule %s disabled', schedule_id)
            return

        fire_id = await svc.create_fire(schedule_id)

        # Step 1: submit_message template + form_values -> final prompt
        message = await _resolve_submit_message(
            db, schedule.agent_id, schedule.form_values
        )

        # Step 2: create task row linked to the agent
        task_id = await TaskService(db).create_task(
            agent_id=schedule.agent_id,
            name=f'{schedule.name} - scheduled fire',
            created_by=schedule.created_by,
        )

        # Step 3: create v1 conversation with initial_message; returns
        # the start-task id + the task-prefixed conversation string.
        _, conv_id_for_link = await _create_v1_conversation(message)

        # Step 4: link task <-> conversation (same path as TaskService.start_task)
        await TaskService(db).start_task(task_id, conv_id_for_link)

        await svc.finish_fire(
            fire_id,
            status='success',
            task_id=task_id,
            conversation_id=conv_id_for_link,
        )
        notify_payload = NotifyFire(
            schedule_id=schedule.id,
            schedule_name=schedule.name,
            status='success',
            task_id=task_id,
            conversation_id=conv_id_for_link,
            error=None,
            fire_id=fire_id,
        )
        _logger.info(
            'scheduled-task fire ok: schedule=%s task=%s conv=%s',
            schedule_id,
            task_id,
            conv_id_for_link,
        )
    except Exception as e:
        _logger.exception('scheduled-task fire failed: %s', schedule_id)
        if fire_id is not None:
            try:
                await svc.finish_fire(
                    fire_id,
                    status='failed',
                    error_message=str(e)[:2000],
                )
            except Exception:
                _logger.exception('failed to mark fire row as failed')
        notify_payload = NotifyFire(
            schedule_id=schedule_id,
            schedule_name=(schedule.name if 'schedule' in locals() and schedule else '?'),
            status='failed',
            task_id=None,
            conversation_id=None,
            error=str(e)[:500],
            fire_id=fire_id or '',
        )
    finally:
        try:
            await db.close()
        except Exception:
            pass
        if notify_payload is not None:
            try:
                await get_notifier().notify(notify_payload)
            except Exception:
                _logger.exception('notifier raised, swallowing')
