"""Convert friendly schedule params into APScheduler triggers + human strings.

The frontend sends ``{kind, params}`` (see ``models.SchedulePayload``) —
this module is the single place that knows how to map each kind to an
APScheduler trigger instance AND to a human-readable description string
for display in the list page.

Supported kinds:

- ``every_n_minutes`` — IntervalTrigger(minutes=params["minutes"])
- ``hourly``          — CronTrigger(minute=params.get("minute", 0))
- ``daily``           — CronTrigger(hour=params["hour"], minute=...)
- ``weekly``          — CronTrigger(day_of_week=..., hour=..., minute=...)
- ``custom_cron``     — CronTrigger.from_crontab(params["cron"])
"""

from __future__ import annotations

from typing import Any

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


_DOW_CN = {
    '0': '周一',
    '1': '周二',
    '2': '周三',
    '3': '周四',
    '4': '周五',
    '5': '周六',
    '6': '周日',
    'mon': '周一',
    'tue': '周二',
    'wed': '周三',
    'thu': '周四',
    'fri': '周五',
    'sat': '周六',
    'sun': '周日',
}


class InvalidScheduleError(ValueError):
    """Raised when {kind, params} cannot be converted into a trigger."""


def schedule_params_to_trigger(kind: str, params: dict[str, Any]) -> BaseTrigger:
    """Build an APScheduler trigger from a friendly schedule payload.

    Raises ``InvalidScheduleError`` on unknown kind or missing required
    params (router should catch and turn it into 400).
    """
    if kind == 'every_n_minutes':
        minutes = int(params.get('minutes', 0))
        if minutes <= 0:
            raise InvalidScheduleError('every_n_minutes requires minutes > 0')
        return IntervalTrigger(minutes=minutes)

    if kind == 'hourly':
        minute = int(params.get('minute', 0))
        return CronTrigger(minute=minute)

    if kind == 'daily':
        if 'hour' not in params:
            raise InvalidScheduleError('daily requires hour')
        hour = int(params['hour'])
        minute = int(params.get('minute', 0))
        return CronTrigger(hour=hour, minute=minute)

    if kind == 'weekly':
        if 'hour' not in params or 'day_of_week' not in params:
            raise InvalidScheduleError('weekly requires day_of_week and hour')
        return CronTrigger(
            day_of_week=str(params['day_of_week']),
            hour=int(params['hour']),
            minute=int(params.get('minute', 0)),
        )

    if kind == 'custom_cron':
        cron = params.get('cron')
        if not cron:
            raise InvalidScheduleError('custom_cron requires cron')
        try:
            return CronTrigger.from_crontab(str(cron))
        except ValueError as e:
            raise InvalidScheduleError(f'invalid cron expression: {e}') from e

    raise InvalidScheduleError(f'unknown schedule kind: {kind}')


def describe_schedule(kind: str, params: dict[str, Any]) -> str:
    """Short Chinese human string describing a schedule.

    Used on the task center list and in the schedule picker preview.
    Falls back to a raw ``kind[params]`` form on unknown kinds so the
    UI never breaks on a newly-added schedule type.
    """
    try:
        if kind == 'every_n_minutes':
            return f'每 {int(params.get("minutes", 0))} 分钟'
        if kind == 'hourly':
            return f'每小时 xx:{int(params.get("minute", 0)):02d}'
        if kind == 'daily':
            return (
                f'每天 {int(params["hour"]):02d}:{int(params.get("minute", 0)):02d}'
            )
        if kind == 'weekly':
            days_raw = str(params.get('day_of_week', ''))
            days = [
                _DOW_CN.get(d.strip().lower(), d.strip())
                for d in days_raw.split(',')
                if d.strip()
            ]
            days_str = '、'.join(days) if days else '每周'
            return (
                f'{days_str} {int(params["hour"]):02d}:{int(params.get("minute", 0)):02d}'
            )
        if kind == 'custom_cron':
            return f'cron: {params.get("cron", "")}'
    except Exception:
        pass
    return f'{kind}[{params}]'
