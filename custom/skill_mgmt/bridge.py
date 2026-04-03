"""Bridge between custom skill management and OpenHands native skill system.

Loads skills from our database and converts them to native Skill objects
that can be injected into the agent context alongside built-in skills.
"""

from __future__ import annotations

import json
import logging

from openhands.sdk.context.skills import Skill
from openhands.sdk.context.skills.trigger import KeywordTrigger, TaskTrigger

_logger = logging.getLogger(__name__)


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
                content += "\n\n---\n\n## 关联脚本\n\n"
                content += "以下脚本文件是此 Skill 的组成部分。执行任务时，请先将脚本保存到工作目录再运行。\n\n"
                for script in detail.scripts:
                    lang = script.language or ""
                    content += f"### 文件: `{script.filename}`\n"
                    if script.description:
                        content += f"{script.description}\n\n"
                    content += f"```{lang}\n{script.content}\n```\n\n"

            repo_skills.append(Skill(
                name=detail.name,
                content=content,
                trigger=None,
                source='custom-db',
                description=detail.description,
                is_agentskills_format=False,
            ))

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
    """Load skill .md files from custom/skill_examples/perf_skills/ directory.

    Only repo-type skills (no triggers) are injected into agent_context.skills
    and always present in system prompt. Knowledge-type skills (with triggers)
    are loaded separately so the SDK's keyword trigger mechanism can activate
    them on demand, keeping the initial prompt small.
    """
    import pathlib
    import frontmatter

    repo_skills: list[Skill] = []
    knowledge_skills: list[Skill] = []
    skill_dirs = [
        pathlib.Path(__file__).parent.parent / 'skill_examples' / 'perf_skills',
    ]

    for skill_dir in skill_dirs:
        if not skill_dir.exists():
            continue
        for md_file in sorted(skill_dir.glob('*.md')):
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata or {}
                name = meta.get('name', md_file.stem)
                triggers = meta.get('triggers', [])
                skill_type = meta.get('type', 'knowledge')
                content = post.content

                trigger = None
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
