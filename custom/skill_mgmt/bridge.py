"""Bridge between custom skill management and OpenHands native skill system.

Loads skills from our database and converts them to native Skill objects
that can be injected into the agent context alongside built-in skills.
"""

from __future__ import annotations

import logging
import pathlib

from openhands.sdk.context.skills import Skill
from openhands.sdk.context.skills.trigger import KeywordTrigger, TaskTrigger

_logger = logging.getLogger(__name__)

# Root directory for all file-based skill domains
_SKILL_ROOT = pathlib.Path(__file__).parent.parent / 'skill_examples'


def _iter_skill_dirs() -> list[pathlib.Path]:
    """Return all subdirectories under skill_examples/."""
    if not _SKILL_ROOT.exists():
        return []
    return sorted(d for d in _SKILL_ROOT.iterdir() if d.is_dir())


async def load_custom_skills() -> list[Skill]:
    """Load active skills from the custom skill database.

    Only returns skills WITHOUT triggers (repo-type, always in prompt).
    Skills with triggers are knowledge-type and should be loaded via
    SDK's keyword trigger mechanism, not injected into agent_context.
    """
    try:
        from custom.skill_mgmt.db import get_skill_db
        from custom.skill_mgmt.service import SkillService

        db = await get_skill_db()
        svc = SkillService(db)
        managed_skills = await svc.list_skills(is_active=True, limit=200)

        repo_skills: list[Skill] = []
        skipped_count = 0
        for ms in managed_skills:
            detail = await svc.get_skill(ms.id)
            if not detail:
                continue

            # Skip knowledge skills (with triggers) — they should be on-demand
            if detail.triggers:
                skipped_count += 1
                continue

            # Build the skill content: .md content + embedded scripts
            content = detail.content
            if detail.scripts:
                content += '\n\n---\n\n## 关联脚本\n\n'
                content += '以下脚本文件是此 Skill 的组成部分。执行任务时，请先将脚本保存到工作目录再运行。\n\n'
                for script in detail.scripts:
                    lang = script.language or ''
                    content += f'### 文件: `{script.filename}`\n'
                    if script.description:
                        content += f'{script.description}\n\n'
                    content += f'```{lang}\n{script.content}\n```\n\n'

            repo_skills.append(
                Skill(
                    name=detail.name,
                    content=content,
                    trigger=None,
                    source='custom-db',
                    description=detail.description,
                    is_agentskills_format=False,
                )
            )

        _logger.info(
            f'Loaded {len(repo_skills)} repo skills from DB (always in prompt), '
            f'skipped {skipped_count} knowledge skills (on-demand)'
        )
        return repo_skills

    except ImportError:
        _logger.debug('Custom skill module not available, skipping')
        return []
    except Exception as e:
        _logger.warning(f'Failed to load custom skills: {e}', exc_info=True)
        return []


def load_file_skills() -> list[Skill]:
    """Load skill .md files from all subdirectories under custom/skill_examples/.

    Only repo-type skills (no triggers) are injected into agent_context.skills
    and always present in system prompt. Knowledge-type skills (with triggers)
    are loaded separately so the SDK's keyword trigger mechanism can activate
    them on demand, keeping the initial prompt small.
    """
    import frontmatter

    repo_skills: list[Skill] = []
    knowledge_skills: list[Skill] = []

    for skill_dir in _iter_skill_dirs():
        for md_file in sorted(skill_dir.glob('*.md')):
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata or {}
                name = meta.get('name', md_file.stem)
                triggers = meta.get('triggers', [])
                skill_type = meta.get('type', 'knowledge')
                content = post.content

                trigger: TaskTrigger | KeywordTrigger | None = None
                if triggers:
                    if any(t.startswith('/') for t in triggers):
                        trigger = TaskTrigger(triggers=triggers)
                    else:
                        trigger = KeywordTrigger(keywords=triggers)

                skill = Skill(
                    name=name,
                    content=content,
                    trigger=trigger,
                    source='file-skill',
                    is_agentskills_format=False,
                )

                if skill_type == 'repo' or not triggers:
                    repo_skills.append(skill)
                else:
                    knowledge_skills.append(skill)
            except Exception as e:
                _logger.warning(f'Failed to load skill file {md_file}: {e}')

    _logger.info(
        f'Loaded {len(repo_skills)} repo skills (always in prompt): {[s.name for s in repo_skills]}, '
        f'{len(knowledge_skills)} knowledge skills (on-demand): {[s.name for s in knowledge_skills]}'
    )
    # Only return repo skills for injection into agent_context.skills
    # Knowledge skills need to be loaded via SDK's trigger mechanism
    return repo_skills


# Cache for parsed workflow phases from skill files
_workflow_phases_cache: dict[str, list[dict]] = {}


def get_workflow_phases(skill_name: str) -> list[dict] | None:
    """Get workflow phases defined in a skill's frontmatter.

    Returns a list of phase dicts like:
        [{"key": "init", "label": "初始化", "desc": "...", "output": "/path/to/file.json"}, ...]
    Or None if the skill has no phases defined.
    """
    if skill_name in _workflow_phases_cache:
        return _workflow_phases_cache[skill_name]

    import frontmatter

    for skill_dir in _iter_skill_dirs():
        for md_file in sorted(skill_dir.glob('*.md')):
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata or {}
                name = meta.get('name', md_file.stem)
                phases = meta.get('phases')
                if phases:
                    # Normalize: rename 'output' to 'file' for frontend compatibility.
                    # `optional: true` phases are kept around for display but the
                    # frontend treats them as non-blocking when computing
                    # error/done state for a failed task (e.g. screenshot phase
                    # may legitimately be skipped if chromium isn't installed).
                    normalized = []
                    for p in phases:
                        normalized.append(
                            {
                                'key': p.get('key', ''),
                                'label': p.get('label', ''),
                                'desc': p.get('desc', ''),
                                'file': p.get('output'),
                                'optional': bool(p.get('optional', False)),
                            }
                        )
                    _workflow_phases_cache[name] = normalized
            except Exception:
                pass

    return _workflow_phases_cache.get(skill_name)


# Cache for downloadable report artifacts declared in a skill's frontmatter
_reports_cache: dict[str, list[dict]] = {}


def get_reports(skill_name: str) -> list[dict] | None:
    """Get downloadable reports declared in a skill's frontmatter.

    Reports are decoupled from workflow phases so a single `generate_report`
    step can publish multiple html (or other) artifacts without bloating
    the progress bar. Each entry is normalized to
        {"label": str, "file": str}
    so the frontend can render one download button per entry.
    """
    if skill_name in _reports_cache:
        return _reports_cache[skill_name]

    import frontmatter

    for skill_dir in _iter_skill_dirs():
        for md_file in sorted(skill_dir.glob('*.md')):
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata or {}
                name = meta.get('name', md_file.stem)
                reports = meta.get('reports')
                if reports:
                    normalized = []
                    for r in reports:
                        file_path = r.get('file') or r.get('output') or r.get('path')
                        if not file_path:
                            continue
                        normalized.append(
                            {
                                'label': r.get('label') or str(file_path).rsplit('/', 1)[-1],
                                'file': file_path,
                            }
                        )
                    if normalized:
                        _reports_cache[name] = normalized
            except Exception:
                pass

    return _reports_cache.get(skill_name)


# Cache for parsed input_form + submit_message from skill files
_input_form_cache: dict[str, dict] = {}


def get_input_form(skill_name: str) -> dict | None:
    """Get input_form and submit_message defined in a skill's frontmatter.

    Returns a dict like:
        {
            "fields": [{"key": "trace_path", "type": "file", "label": "...", ...}, ...],
            "submit_message": "Execute skill: ... {{trace_path}} ..."
        }
    Or None if the skill has no input_form defined.
    """
    if skill_name in _input_form_cache:
        return _input_form_cache[skill_name]

    import frontmatter

    for skill_dir in _iter_skill_dirs():
        for md_file in sorted(skill_dir.glob('*.md')):
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata or {}
                name = meta.get('name', md_file.stem)
                input_form = meta.get('input_form')
                if input_form:
                    _input_form_cache[name] = {
                        'fields': input_form,
                        'submit_message': meta.get('submit_message', ''),
                    }
            except Exception:
                pass

    return _input_form_cache.get(skill_name)
