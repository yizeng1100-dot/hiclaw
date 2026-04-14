"""``trigger_agent`` — the only write tool in the chatbot MVP.

Mirrors ``custom.scheduled_tasks.fire._create_v1_conversation`` and
the frontend's ``handleSelectAgent`` generic branch so a chatbot-
triggered run is indistinguishable from a manual click: same task_id
creation path, same v1 app-conversation creation, same task<->conv
linking.

Guardrails live in the tool description + system prompt: the LLM is
instructed to ALWAYS confirm with the user before calling this. There
is no server-side confirmation gate in the MVP because an agent run
is easily undone from the task center (cancel button).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from custom.agent_mgmt.db import get_agent_db
from custom.agent_mgmt.task_service import TaskService
from custom.chatbot.tools.base import Tool, register

_logger = logging.getLogger(__name__)

_LOCAL_API = 'http://127.0.0.1:12000'

_TEMPLATE_VAR = re.compile(r'\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}')
_LEFTOVER = re.compile(r'\{\{[^}]+\}\}')


def _interpolate(template: str, values: dict[str, Any]) -> str:
    """Same {{key}} substitution DynamicFormPanel + fire.py use."""
    if not template:
        return template

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return str(values[key])
        return match.group(0)

    message = _TEMPLATE_VAR.sub(repl, template)
    message = _LEFTOVER.sub('', message)
    return message.strip()


async def _resolve_submit_message(
    agent_id: str, form_values: dict[str, Any]
) -> tuple[str, str]:
    """Load the agent config and return (message, agent_name).

    Falls back to the system_prompt / name variant when the agent has
    no input_form declared (matches handleSelectAgent's branch).
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
    if template:
        return _interpolate(template, form_values), data.get('name', '')

    sys_prompt = data.get('system_prompt') or ''
    if sys_prompt:
        return f'[Agent: {data.get("name", "")}]\n\n{sys_prompt}', data.get(
            'name', ''
        )
    return f'Execute Agent: {data.get("name", "")}', data.get('name', '')


async def _create_v1_conversation(message: str) -> tuple[str, str]:
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
        raise RuntimeError(f'app-conversations missing id: {data}')
    return str(start_task_id), f'task-{start_task_id}'


async def _trigger_agent(args: dict[str, Any]) -> Any:
    agent_id = args.get('agent_id')
    if not agent_id:
        return {'error': 'agent_id required'}
    form_values = args.get('form_values') or {}
    if not isinstance(form_values, dict):
        return {'error': 'form_values must be a dict'}

    try:
        message, agent_name = await _resolve_submit_message(agent_id, form_values)
    except Exception as e:
        return {'error': f'failed to load agent: {e}'}

    db = await get_agent_db()
    try:
        svc = TaskService(db)
        task_id = await svc.create_task(
            agent_id=agent_id,
            name=f'{agent_name} - chatbot triggered',
            created_by='chatbot',
        )
        try:
            _, conv_for_link = await _create_v1_conversation(message)
        except Exception as e:
            return {'error': f'failed to create conversation: {e}'}
        await svc.start_task(task_id, conv_for_link)
    finally:
        await db.close()

    return {
        'task_id': task_id,
        'conversation_id': conv_for_link,
        'agent_name': agent_name,
        'note': (
            'agent 已启动。用户可以在任务中心（/tasks/'
            f'{task_id}）查看执行进度。'
        ),
    }


register(
    Tool(
        name='trigger_agent',
        description=(
            '启动一次 agent 分析。创建一个 agent_task + 一个新的 v1 conversation'
            '，并把 submit_message 模板 + form_values 作为初始消息发给 agent。'
            '重要：这是一个【写操作】，会真的启动分析、占用 LLM 和 sandbox 资源。'
            '调用前必须先和用户确认：确认要用哪个 agent_id + form_values 的每个字段具体值。'
            '如果用户没明确说明 form_values，先用 get_agent 拿到 input_form 字段定义，'
            '列出每个必填字段让用户填，再调本工具。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'agent_id': {
                    'type': 'string',
                    'description': '要启动的 agent id（来自 list_agents / get_agent）',
                },
                'form_values': {
                    'type': 'object',
                    'description': (
                        '传给 agent 的输入参数字典。键名对应 input_form.fields[].key，'
                        '值按 field 类型：file 字段值是 sandbox 路径字符串、'
                        'select 字段值是 option 的 value、number 字段值是整数等。'
                    ),
                },
            },
            'required': ['agent_id'],
        },
        run=_trigger_agent,
    )
)
