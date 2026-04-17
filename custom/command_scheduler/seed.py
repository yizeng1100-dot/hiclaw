"""Seed demo command schedules on first startup.

Creates a few example scheduled tasks so the command-scheduler UI
is not empty on a fresh deployment. Safe to re-run — idempotent by
name check.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from custom.command_scheduler.models import StoredCommandSchedule

_logger = logging.getLogger(__name__)

DEMO_SCHEDULES = [
    {
        'name': '【演示】每日系统巡检',
        'env_tag': 'test',
        'shell_kind': 'linux',
        'kind': 'daily',
        'cron_expr': '0 9 * * *',
        'command': (
            'echo "=== 系统巡检 $(date) ===" '
            '&& free -h '
            '&& df -h / '
            '&& uptime '
            '&& echo "巡检完成"'
        ),
        'working_dir': '/home/wq',
        'max_duration_sec': 60,
        'holiday_policy': 'normal',
    },
    {
        'name': '【演示】性能监控（每15分钟）',
        'env_tag': 'test',
        'shell_kind': 'linux',
        'kind': 'daily',
        'cron_expr': '*/15 * * * *',
        'command': (
            'top -bn1 | head -5 '
            '&& echo "--- GPU ---" '
            '&& nvidia-smi --query-gpu=utilization.gpu,memory.used '
            '--format=csv,noheader 2>/dev/null || echo "No GPU"'
        ),
        'working_dir': '/home/wq',
        'max_duration_sec': 30,
        'holiday_policy': 'normal',
    },
    {
        'name': '【演示】每周性能报告汇总',
        'env_tag': 'formal',
        'shell_kind': 'linux',
        'kind': 'weekly',
        'cron_expr': '0 18 * * 1',
        'command': (
            'echo "=== 本周性能报告汇总 ===" '
            '&& ls -lt ~/render_output_*/render_report.html 2>/dev/null | head -5 '
            '&& echo "汇总完成"'
        ),
        'working_dir': '/home/wq',
        'max_duration_sec': 120,
        'holiday_policy': 'skip',
    },
]


async def seed_demo_schedules(db: AsyncSession) -> None:
    """Create demo command schedules if they don't already exist."""
    try:
        for spec in DEMO_SCHEDULES:
            result = await db.execute(
                select(StoredCommandSchedule).where(
                    StoredCommandSchedule.name == spec['name']
                )
            )
            existing = result.scalars().first()
            if existing is not None:
                continue

            schedule = StoredCommandSchedule(
                id=uuid4(),
                name=spec['name'],
                env_tag=spec['env_tag'],
                shell_kind=spec['shell_kind'],
                kind=spec['kind'],
                cron_expr=spec['cron_expr'],
                command=spec['command'],
                working_dir=spec.get('working_dir'),
                max_duration_sec=spec.get('max_duration_sec', 300),
                holiday_policy=spec.get('holiday_policy', 'normal'),
                enabled=True,
            )
            db.add(schedule)
            await db.commit()
            _logger.info(f'Seeded demo schedule: {spec["name"]}')

    except Exception as e:
        _logger.warning(f'Failed to seed demo schedules: {e}', exc_info=True)
        await db.rollback()
