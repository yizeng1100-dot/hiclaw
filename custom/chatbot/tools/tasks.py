"""Tools for querying the 任务中心 agent_task table."""

from __future__ import annotations

from typing import Any

from custom.agent_mgmt.db import get_agent_db
from custom.agent_mgmt.task_service import TaskService
from custom.chatbot.tools.base import Tool, register


async def _list_tasks(args: dict[str, Any]) -> Any:
    status = args.get('status')
    agent_id = args.get('agent_id')
    search = args.get('search')
    limit = int(args.get('limit', 20))
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        tasks = await svc.list_tasks(
            status=status, agent_id=agent_id, search=search, limit=limit
        )
    finally:
        await db.close()
    return [
        {
            'id': t.id,
            'name': t.name,
            'agent_name': t.agent_name,
            'status': t.status,
            'started_at': t.started_at,
            'completed_at': t.completed_at,
            'conversation_id': t.conversation_id,
        }
        for t in tasks
    ]


async def _get_task(args: dict[str, Any]) -> Any:
    task_id = args.get('task_id')
    if not task_id:
        return {'error': 'task_id required'}
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        task = await svc.get_task(task_id)
    finally:
        await db.close()
    if task is None:
        return {'error': 'task not found'}
    return task.model_dump()


register(
    Tool(
        name='list_tasks',
        description=(
            '列出 HiClaw 任务中心的 agent 任务。可按 status (pending/running/'
            'completed/failed/cancelled) 或 agent_id 过滤。每次一个 agent 触发'
            '（手动或定时）都会产生一条任务记录。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'description': 'pending / running / completed / failed / cancelled',
                },
                'agent_id': {
                    'type': 'string',
                    'description': '仅返回这个 agent 的任务',
                },
                'search': {
                    'type': 'string',
                    'description': '按任务名称模糊搜索',
                },
                'limit': {
                    'type': 'integer',
                    'description': '返回上限，默认 20',
                },
            },
            'required': [],
        },
        run=_list_tasks,
    )
)


register(
    Tool(
        name='get_task',
        description=(
            '获取一个任务的完整详情，包括状态、开始/结束时间、关联的 conversation_id、'
            '错误信息（如果失败）。task_id 必须来自 list_tasks。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'task_id': {'type': 'string', 'description': '任务 id'},
            },
            'required': ['task_id'],
        },
        run=_get_task,
    )
)
