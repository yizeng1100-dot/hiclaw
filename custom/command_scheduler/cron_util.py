"""Convert friendly schedule kinds into APScheduler triggers.

Shapes supported (P1):
  kind="one_time", run_at=datetime  →  DateTrigger
  kind="daily",    cron_expr="M H * * *"
  kind="weekly",   cron_expr="M H * * D,D,D"
  kind="monthly",  cron_expr="M H D * *"
  kind="yearly",   cron_expr="M H D MO *"   (month first then day)

For daily/weekly/monthly/yearly we store the full crontab string in
``cron_expr`` and parse it with ``CronTrigger.from_crontab``, which
gives users the full cron flexibility even though the UI picker only
exposes the friendly fields.
"""

from __future__ import annotations

from datetime import datetime

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from custom.command_scheduler.models import ScheduleKind


class InvalidScheduleError(ValueError):
    pass


def build_trigger(
    kind: ScheduleKind, cron_expr: str | None, run_at: datetime | None
):
    if kind == 'one_time':
        if run_at is None:
            raise InvalidScheduleError('one_time requires run_at')
        return DateTrigger(run_date=run_at, timezone='Asia/Shanghai')
    if cron_expr is None:
        raise InvalidScheduleError(f'{kind} requires cron_expr')
    try:
        return CronTrigger.from_crontab(cron_expr, timezone='Asia/Shanghai')
    except Exception as e:
        raise InvalidScheduleError(
            f'bad cron expression {cron_expr!r}: {e}'
        ) from e


def describe(
    kind: ScheduleKind, cron_expr: str | None, run_at: datetime | None
) -> str:
    """Return a Chinese human-friendly description for the UI."""
    if kind == 'one_time':
        if run_at is None:
            return '一次性'
        return f'一次性 · {run_at.strftime("%Y-%m-%d %H:%M")}'
    if cron_expr is None:
        return str(kind)
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    m, h, dom, mon, dow = parts
    hm = f'{h.zfill(2)}:{m.zfill(2)}'
    if kind == 'daily':
        return f'每天 {hm}'
    if kind == 'weekly':
        return f'每周 {dow} · {hm}'
    if kind == 'monthly':
        return f'每月 {dom} 号 · {hm}'
    if kind == 'yearly':
        return f'每年 {mon} 月 {dom} 日 · {hm}'
    return cron_expr
