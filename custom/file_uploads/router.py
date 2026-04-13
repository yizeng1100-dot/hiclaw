"""Generic file upload endpoint for dynamic form file inputs.

Writes uploaded files into a staging area under ``sandbox-data/.uploads/``
so conversation sandboxes can read them at
``/workspace/conversations/.uploads/<upload_id>/<filename>``.

This is platform infrastructure: any agent whose skill frontmatter declares
an ``input_form`` field of ``type: file`` gets real uploads for free — no
per-agent backend code needed.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from openhands.server.shared import config

router = APIRouter(prefix='/uploads', tags=['File Uploads'])


_SAFE_FILENAME_RE = re.compile(r'[^A-Za-z0-9._-]+')
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _safe_filename(name: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub('_', Path(name).name)
    return cleaned or 'upload.bin'


def _sandbox_data_root() -> Path:
    """sandbox-data lives inside ``file_store_path`` (default ``~/.openhands``)."""
    base = Path(os.path.expanduser(config.file_store_path)).resolve()
    return base / 'sandbox-data'


@router.post('')
async def upload_file(file: Annotated[UploadFile, File(...)]) -> dict:
    """Accept a single file and stage it into a sandbox-visible path.

    Returns the path as seen *from inside* a conversation sandbox, which
    has ``sandbox-data/`` bind-mounted at ``/workspace/conversations/``.
    """
    upload_id = uuid.uuid4().hex
    safe_name = _safe_filename(file.filename or 'upload.bin')

    staging_dir = _sandbox_data_root() / '.uploads' / upload_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    target = staging_dir / safe_name

    total = 0
    try:
        with open(target, 'wb') as out:
            while True:
                chunk = await file.read(1 << 20)  # 1 MB
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f'File too large (>{_MAX_UPLOAD_BYTES // (1024 * 1024)} MB)'
                        ),
                    )
                out.write(chunk)
    except Exception:
        # Clean up partial upload so staging dir stays tidy.
        if target.exists():
            target.unlink(missing_ok=True)
        try:
            staging_dir.rmdir()
        except OSError:
            pass
        raise

    sandbox_path = f'/workspace/conversations/.uploads/{upload_id}/{safe_name}'

    return {
        'upload_id': upload_id,
        'filename': safe_name,
        'size_bytes': total,
        'sandbox_path': sandbox_path,
    }
