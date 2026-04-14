"""Tools for querying scheduled tasks (定时任务)."""

from __future__ import annotations

from typing import Any

from custom.agent_mgmt.db import get_agent_db
from custom.chatbot.tools.base import Tool, register
from custom.scheduled_tasks.service import ScheduledTaskService


async def _list_scheduled(args: dict[str, Any]) -> Any:
    enabled = args.get('enabled')
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        schedules = await svc.list_schedules(enabled=enabled)
    finally:
        await db.close()
    return [
        {
            'id': s.id,
            'name': s.name,
            'agent_name': s.agent_name,
            'schedule_description': s.schedule_description,
            'enabled': s.enabled,
            'last_fire_at': s.last_fire_at,
            'next_fire_at': s.next_fire_at,
            'last_status': s.last_status,
        }
        for s in schedules
    ]


async def _get_scheduled(args: dict[str, Any]) -> Any:
    schedule_id = args.get('schedule_id')
    if not schedule_id:
        return {'error': 'schedule_id required'}
    db = await get_agent_db()
    try:
        svc = ScheduledTaskService(db)
        schedule = await svc.get_schedule(schedule_id)
        fires = await svc.list_fires(schedule_id, limit=5) if schedule else []
    finally:
        await db.close()
    if schedule is None:
        return {'error': 'scheduled task not found'}
    return {
        'schedule': schedule.model_dump(),
        'recent_fires': [f.model_dump() for f in fires],
    }


register(
    Tool(
        name='list_scheduled_tasks',
        description=(
            '列出 HiClaw 定时任务中心的所有定时任务。每个定时任务按配置好的时间'
            '（cron 或 interval 或 one_time）触发某个 agent 跑一次分析。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'enabled': {
                    'type': 'boolean',
                    'description': '只看启用/停用的任务',
                },
            },
            'required': [],
        },
        run=_list_scheduled,
    )
)


register(
    Tool(
        name='get_scheduled_task',
        description=(
            '获取一个定时任务的详情和最近 5 次执行历史（成功/失败/错误信息）。'
            'schedule_id 必须来自 list_scheduled_tasks。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'schedule_id': {'type': 'string', 'description': '定时任务 id'},
            },
            'required': ['schedule_id'],
        },
        run=_get_scheduled,
    )
)
