"""
>>> CUSTOM: HiClaw — Skills Git management API.

Operates directly on the skills bare repo (configured via HICLAW_DIR env var).
Uses a temporary working copy for read/write operations.
<<<
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/hiclaw/skills', tags=['hiclaw-skills'])

from openhands.server.routes.hiclaw_config import SKILLS_REPO_PATH as REPO_PATH


def _run_git(cwd: str, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ['git'] + list(args),
        cwd=cwd, capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed: {result.stderr[:200]}')
    return result.stdout


def _get_work_tree() -> str:
    """Get or create a persistent working copy of the skills repo."""
    work_dir = '/tmp/hiclaw-skills-workdir'
    if os.path.isdir(os.path.join(work_dir, '.git')):
        # Pull latest
        try:
            _run_git(work_dir, 'pull', '--ff-only')
        except Exception:
            # Reset if pull fails
            _run_git(work_dir, 'reset', '--hard', 'origin/master')
        return work_dir
    # Fresh clone
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    subprocess.run(
        ['git', 'clone', REPO_PATH, work_dir],
        capture_output=True, text=True, timeout=10, check=True,
    )
    subprocess.run(
        ['git', 'config', 'user.email', 'hiclaw@system'],
        cwd=work_dir, capture_output=True, timeout=5,
    )
    subprocess.run(
        ['git', 'config', 'user.name', 'HiClaw'],
        cwd=work_dir, capture_output=True, timeout=5,
    )
    return work_dir


# ─── Models ──────────────────────────────

class SkillInfo(BaseModel):
    path: str  # e.g., "global/code-review.md"
    name: str
    description: str = ""
    category: str = ""  # "global", "users/zhang", "teams/kernel"
    content: str = ""
    triggers: list[str] = []


class SkillCreateRequest(BaseModel):
    path: str  # e.g., "global/my-skill.md"
    content: str


class SkillUpdateRequest(BaseModel):
    content: str
    message: str = ""


# ─── API ──────────────────────────────

@router.get('', response_model=list[SkillInfo])
async def list_skills(search: str = "", category: str = ""):
    """List all skills in the repo. Optionally filter by search term or category."""
    work_dir = _get_work_tree()
    skills = []

    for md_path in sorted(Path(work_dir).rglob('*.md')):
        rel_path = str(md_path.relative_to(work_dir))
        if rel_path.startswith('.'):
            continue

        # Parse frontmatter
        content = md_path.read_text(encoding='utf-8', errors='replace')
        name, description, triggers = _parse_frontmatter(content)

        # Category from directory
        parts = rel_path.split('/')
        cat = parts[0] if len(parts) > 1 else 'root'
        if len(parts) > 2:
            cat = '/'.join(parts[:2])  # e.g., "users/zhang"

        # Filters
        if category and not cat.startswith(category):
            continue
        if search and search.lower() not in (name + description + content).lower():
            continue

        skills.append(SkillInfo(
            path=rel_path,
            name=name or md_path.stem,
            description=description,
            category=cat,
            triggers=triggers,
        ))

    return skills


@router.get('/{path:path}', response_model=SkillInfo)
async def get_skill(path: str):
    """Get a single skill by path."""
    work_dir = _get_work_tree()
    full_path = os.path.join(work_dir, path)

    if not os.path.isfile(full_path) or not path.endswith('.md'):
        raise HTTPException(status_code=404, detail=f'Skill not found: {path}')

    content = Path(full_path).read_text(encoding='utf-8', errors='replace')
    name, description, triggers = _parse_frontmatter(content)
    parts = path.split('/')
    cat = parts[0] if len(parts) > 1 else 'root'

    return SkillInfo(
        path=path,
        name=name or Path(path).stem,
        description=description,
        category=cat,
        content=content,
        triggers=triggers,
    )


@router.post('')
async def create_skill(req: SkillCreateRequest):
    """Create a new skill file and commit."""
    work_dir = _get_work_tree()
    full_path = os.path.join(work_dir, req.path)

    if os.path.exists(full_path):
        raise HTTPException(status_code=409, detail=f'Skill already exists: {req.path}')

    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    Path(full_path).write_text(req.content, encoding='utf-8')

    _run_git(work_dir, 'add', req.path)
    _run_git(work_dir, 'commit', '-m', f'Add skill: {req.path}')
    _run_git(work_dir, 'push', 'origin', 'master')

    return {"status": "created", "path": req.path}


@router.put('/{path:path}')
async def update_skill(path: str, req: SkillUpdateRequest):
    """Update a skill file and commit."""
    work_dir = _get_work_tree()
    full_path = os.path.join(work_dir, path)

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f'Skill not found: {path}')

    Path(full_path).write_text(req.content, encoding='utf-8')

    _run_git(work_dir, 'add', path)
    message = req.message or f'Update skill: {path}'
    _run_git(work_dir, 'commit', '-m', message)
    _run_git(work_dir, 'push', 'origin', 'master')

    return {"status": "updated", "path": path}


@router.delete('/{path:path}')
async def delete_skill(path: str):
    """Delete a skill file and commit."""
    work_dir = _get_work_tree()
    full_path = os.path.join(work_dir, path)

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f'Skill not found: {path}')

    os.remove(full_path)
    _run_git(work_dir, 'add', path)
    _run_git(work_dir, 'commit', '-m', f'Delete skill: {path}')
    _run_git(work_dir, 'push', 'origin', 'master')

    return {"status": "deleted", "path": path}


@router.get('-history/{path:path}')
async def skill_history(path: str, limit: int = 20):
    """Get git log for a specific skill file."""
    work_dir = _get_work_tree()
    full_path = os.path.join(work_dir, path)

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f'Skill not found: {path}')

    log_output = _run_git(
        work_dir, 'log', f'--max-count={limit}',
        '--format=%H|%an|%ae|%ai|%s', '--', path,
    )

    commits = []
    for line in log_output.strip().split('\n'):
        if not line:
            continue
        parts = line.split('|', 4)
        if len(parts) == 5:
            commits.append({
                'hash': parts[0],
                'author': parts[1],
                'email': parts[2],
                'date': parts[3],
                'message': parts[4],
            })

    return commits


@router.get('-categories')
async def list_categories():
    """List all skill categories (directories)."""
    work_dir = _get_work_tree()
    categories = set()
    for md_path in Path(work_dir).rglob('*.md'):
        rel = str(md_path.relative_to(work_dir))
        if rel.startswith('.'):
            continue
        parts = rel.split('/')
        if len(parts) > 1:
            categories.add(parts[0])
            if len(parts) > 2:
                categories.add('/'.join(parts[:2]))
    return sorted(categories)


# ─── Helpers ──────────────────────────────

def _parse_frontmatter(content: str) -> tuple[str, str, list[str]]:
    """Parse YAML frontmatter from markdown. Returns (name, description, triggers)."""
    name = ""
    description = ""
    triggers: list[str] = []

    if not content.startswith('---'):
        return name, description, triggers

    parts = content.split('---', 2)
    if len(parts) < 3:
        return name, description, triggers

    frontmatter = parts[1]
    for line in frontmatter.strip().split('\n'):
        line = line.strip()
        if line.startswith('name:'):
            name = line.split(':', 1)[1].strip().strip('"\'')
        elif line.startswith('description:'):
            description = line.split(':', 1)[1].strip().strip('"\'')
        elif line.startswith('- "') or line.startswith("- '") or line.startswith('- '):
            # Trigger keyword
            kw = line.lstrip('- ').strip().strip('"\'')
            if kw:
                triggers.append(kw)

    return name, description, triggers
