"""Command output log I/O.

Two sinks per fire:
- DB tail: last ~200 lines, capped at 32 KB, stored on the fire row
- File: full output at ~/.openhands/command_scheduler/logs/{sched}/{fire}.log
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

_logger = logging.getLogger(__name__)

LOG_ROOT = Path.home() / '.openhands' / 'command_scheduler' / 'logs'
MAX_TAIL_LINES = 200
MAX_TAIL_BYTES = 32 * 1024


def ensure_log_root() -> Path:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    return LOG_ROOT


def log_file_for(schedule_id: str, fire_id: str) -> Path:
    d = LOG_ROOT / schedule_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{fire_id}.log'


def write_full_log(
    schedule_id: str,
    fire_id: str,
    stdout: str,
    stderr: str,
    started_at: datetime,
    completed_at: datetime | None,
    exit_code: int | None,
) -> Path:
    ensure_log_root()
    p = log_file_for(schedule_id, fire_id)
    start_s = started_at.isoformat()
    end_s = completed_at.isoformat() if completed_at else '(not completed)'
    with p.open('w', encoding='utf-8') as f:
        f.write(
            f'=== STARTED {start_s} ===\n'
            f'[stdout]\n{stdout}\n'
            f'[stderr]\n{stderr}\n'
        )
        f.write(f'=== COMPLETED {end_s} exit={exit_code} ===\n')
    return p


def tail_bytes_and_lines(text: str) -> str:
    if not text:
        return ''
    if len(text.encode('utf-8')) > MAX_TAIL_BYTES:
        text = text[-MAX_TAIL_BYTES:]
    lines = text.splitlines()
    if len(lines) > MAX_TAIL_LINES:
        lines = lines[-MAX_TAIL_LINES:]
    return '\n'.join(lines)


def cleanup_old_logs(retention_days: int = 30) -> int:
    """Delete log files older than retention_days. Returns deleted count."""
    ensure_log_root()
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0
    for p in LOG_ROOT.rglob('*.log'):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                p.unlink()
                deleted += 1
        except FileNotFoundError:
            continue
        except Exception as e:
            _logger.warning('log cleanup failed for %s: %s', p, e)
    return deleted
