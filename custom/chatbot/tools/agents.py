"""Tools for querying the Agent 中心."""

from __future__ import annotations

import json
from typing import Any

import httpx

from custom.agent_mgmt.db import get_agent_db
from custom.agent_mgmt.service import AgentService
from custom.chatbot.tools.base import Tool, register

_LOCAL_API = 'http://127.0.0.1:12000'


async def _list_agents(args: dict[str, Any]) -> Any:
    search = args.get('search')
    category = args.get('category')
    limit = int(args.get('limit', 20))
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        agents = await svc.list_agents(
            search=search, category=category, limit=limit
        )
    finally:
        await db.close()
    return [
        {
            'id': str(a.id).replace('-', ''),
            'name': a.name,
            'description': a.description,
            'category': a.category,
            'is_enabled': bool(a.is_enabled),
        }
        for a in agents
    ]


async def _get_agent(args: dict[str, Any]) -> Any:
    agent_id = args.get('agent_id')
    if not agent_id:
        return {'error': 'agent_id required'}
    # Loopback to /api/v1/agents/{id} so we pick up the skill-merged
    # workflow_phases / input_form / reports overlay the router adds
    # — the service layer alone does not do that merge.
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f'{_LOCAL_API}/api/v1/agents/{agent_id}')
        if resp.status_code == 404:
            return {'error': 'agent not found'}
        resp.raise_for_status()
        data = resp.json()

    cfg_raw = data.get('config_json') or '{}'
    try:
        cfg = json.loads(cfg_raw) if isinstance(cfg_raw, str) else cfg_raw
    except Exception:
        cfg = {}
    return {
        'id': data.get('id'),
        'name': data.get('name'),
        'description': data.get('description'),
        'category': data.get('category'),
        'tags': data.get('tags'),
        'is_enabled': data.get('is_enabled'),
        'workflow_phases': cfg.get('workflow_phases'),
        'input_form': cfg.get('input_form'),
        'reports': cfg.get('reports'),
        'usage_instructions': data.get('usage_instructions'),
    }


register(
    Tool(
        name='list_agents',
        description=(
            '列出 HiClaw Agent 中心的 agent。可用 search 按名称/描述过滤，'
            '用 category 按类别过滤。返回每个 agent 的 id / 名称 / 描述 / 类别 / 启用状态。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'search': {
                    'type': 'string',
                    'description': '按名称或描述模糊搜索',
                },
                'category': {
                    'type': 'string',
                    'description': '类别过滤（如 performance、kernel）',
                },
                'limit': {
                    'type': 'integer',
                    'description': '返回上限，默认 20',
                },
            },
            'required': [],
        },
        run=_list_agents,
    )
)


register(
    Tool(
        name='get_agent',
        description=(
            '获取一个 agent 的完整配置，包括 workflow_phases（执行阶段）、'
            'input_form（前端表单定义）、reports（可下载的报告产物）。'
            '如果用户问某个 agent 要什么输入参数、有哪些阶段、会产出什么报告，'
            '调用这个工具。agent_id 必须是 list_agents 返回的 id，不能猜。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'agent_id': {
                    'type': 'string',
                    'description': '来自 list_agents 的 id 字段',
                },
            },
            'required': ['agent_id'],
        },
        run=_get_agent,
    )
)
