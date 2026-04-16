#!/usr/bin/env python3
"""HiClaw Windows Runner — pull-model executor for shell_kind=windows tasks.

This script runs on the target Windows machine. Every ``--interval``
seconds it polls HiClaw's ``/api/v1/command-scheduler/windows-runner/pending``
endpoint for tasks, executes them locally via ``cmd.exe``, and posts
the result back. All network traffic is outbound HTTP/HTTPS, so the
runner works behind any NAT / firewall as long as HiClaw is reachable
from the machine.

Install:
    python -m pip install requests
    # optional: pip install pywin32 if you want Windows service mode

Run manually:
    python hiclaw_windows_runner.py ^
      --hiclaw-url http://<hiclaw-host>:12000 ^
      --api-key <your-key> ^
      --runner-id work-pc-zhangsan ^
      --workdir D:\\hiclaw_scripts

Start on boot via Windows Task Scheduler:
    schtasks /create /sc onstart /rl highest /tn HiClawRunner ^
      /tr "python C:\\path\\to\\hiclaw_windows_runner.py --hiclaw-url ..."

See tools/windows_runner/README.md for the full setup guide.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    print(
        'ERROR: requests not installed. Run: pip install requests',
        file=sys.stderr,
    )
    sys.exit(1)


_logger = logging.getLogger('hiclaw_windows_runner')


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='HiClaw Windows task runner (pull model).'
    )
    p.add_argument(
        '--hiclaw-url',
        default=os.environ.get('HICLAW_URL', 'http://127.0.0.1:12000'),
        help='HiClaw backend URL (default: env HICLAW_URL or localhost)',
    )
    p.add_argument(
        '--api-key',
        default=os.environ.get('HICLAW_WINDOWS_RUNNER_KEY', ''),
        help=(
            'Runner API key matching server HICLAW_WINDOWS_RUNNER_KEY '
            '(default: env HICLAW_WINDOWS_RUNNER_KEY)'
        ),
    )
    p.add_argument(
        '--runner-id',
        default=os.environ.get('HICLAW_RUNNER_ID', socket.gethostname()),
        help='Unique runner identifier, defaults to hostname',
    )
    p.add_argument(
        '--interval',
        type=int,
        default=int(os.environ.get('HICLAW_RUNNER_INTERVAL', '10')),
        help='Poll interval in seconds (default 10)',
    )
    p.add_argument(
        '--workdir',
        default=os.environ.get('HICLAW_RUNNER_WORKDIR', r'D:\hiclaw_scripts'),
        help=r'Default working directory (default D:\hiclaw_scripts)',
    )
    p.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
    )
    return p.parse_args()


class RunnerClient:
    """Thin HTTP wrapper around the runner endpoints."""

    def __init__(self, base_url: str, api_key: str, runner_id: str):
        self.base = base_url.rstrip('/')
        self.runner_id = runner_id
        self.session = requests.Session()
        if api_key:
            self.session.headers['X-HiClaw-Runner-Key'] = api_key

    def _url(self, path: str) -> str:
        return f'{self.base}/api/v1/command-scheduler/windows-runner/{path}'

    def heartbeat(self) -> None:
        self.session.post(
            self._url('heartbeat'),
            json={'runner_id': self.runner_id, 'runner_version': '1.0.0'},
            timeout=10,
        ).raise_for_status()

    def list_pending(self) -> list[dict[str, Any]]:
        r = self.session.get(self._url('pending'), timeout=10)
        r.raise_for_status()
        return r.json()

    def start_fire(self, fire_id: str) -> bool:
        r = self.session.post(
            self._url(f'fires/{fire_id}/start'),
            timeout=10,
        )
        if r.status_code == 409:
            # Someone else claimed it — normal race, just skip.
            _logger.info(
                'fire %s already claimed by another runner', fire_id
            )
            return False
        r.raise_for_status()
        return True

    def complete_fire(
        self,
        fire_id: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        status: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            'exit_code': exit_code,
            'stdout': stdout,
            'stderr': stderr,
        }
        if status is not None:
            payload['status'] = status
        self.session.post(
            self._url(f'fires/{fire_id}/complete'),
            json=payload,
            timeout=30,
        ).raise_for_status()


def execute_command(
    command: str, working_dir: str, timeout_sec: int
) -> tuple[int, str, str, bool]:
    """Run ``command`` through cmd.exe. Returns (exit_code, stdout, stderr, timed_out)."""
    os.makedirs(working_dir, exist_ok=True)
    _logger.info(
        'executing command (cwd=%s, timeout=%ss)', working_dir, timeout_sec
    )
    _logger.debug('command: %s', command)
    try:
        result = subprocess.run(
            command,
            cwd=working_dir,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_sec,
        )
        return (
            result.returncode,
            result.stdout or '',
            result.stderr or '',
            False,
        )
    except subprocess.TimeoutExpired as e:
        return (
            -1,
            e.stdout or '',
            (e.stderr or '') + f'\n[runner] command timed out after {timeout_sec}s',
            True,
        )
    except Exception as e:
        return -1, '', f'[runner] failed to spawn: {e}', False


def handle_one(client: RunnerClient, task: dict[str, Any], workdir_default: str) -> None:
    fire_id = task['fire_id']
    name = task.get('schedule_name', '(unnamed)')
    command = task['command']
    working_dir = task.get('working_dir') or workdir_default
    timeout_sec = task.get('max_duration_sec') or 300

    _logger.info('picking up fire %s: %s', fire_id, name)

    # Claim it first; if another runner beat us, skip silently.
    if not client.start_fire(fire_id):
        return

    exit_code, stdout, stderr, timed_out = execute_command(
        command, working_dir, timeout_sec
    )

    status = 'timeout' if timed_out else None
    try:
        client.complete_fire(
            fire_id,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            status=status,
        )
        _logger.info(
            'fire %s done: exit=%s timed_out=%s', fire_id, exit_code, timed_out
        )
    except requests.RequestException as e:
        _logger.error('fire %s complete upload failed: %s', fire_id, e)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    client = RunnerClient(
        base_url=args.hiclaw_url,
        api_key=args.api_key,
        runner_id=args.runner_id,
    )

    _logger.info(
        'HiClaw Windows runner starting: id=%s url=%s interval=%ds workdir=%s',
        args.runner_id,
        args.hiclaw_url,
        args.interval,
        args.workdir,
    )
    os.makedirs(args.workdir, exist_ok=True)

    while True:
        # Heartbeat first so the UI can see us even when there's no work.
        try:
            client.heartbeat()
        except requests.RequestException as e:
            _logger.warning('heartbeat failed: %s', e)

        try:
            pending = client.list_pending()
        except requests.RequestException as e:
            _logger.warning('pending fetch failed: %s', e)
            pending = []

        if pending:
            _logger.info('picked up %d pending task(s)', len(pending))
            for task in pending:
                try:
                    handle_one(client, task, args.workdir)
                except Exception:  # pragma: no cover — keep runner alive
                    _logger.exception(
                        'unexpected error handling fire %s', task.get('fire_id')
                    )

        time.sleep(args.interval)


if __name__ == '__main__':
    sys.exit(main() or 0)
