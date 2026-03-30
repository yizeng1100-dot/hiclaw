"""
>>> CUSTOM: HiClaw — Load skills from Git repo into agent system prompt.

Reads SKILL.md files from the bare repo at /opt/hiclaw/skills-repo.git
and formats them for injection into the agent's system_message_suffix.
<<<
"""

import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from openhands.server.routes.hiclaw_config import SKILLS_REPO_PATH as REPO_PATH


@dataclass
class HiClawSkill:
    name: str
    description: str
    skill_type: str  # skill | workflow | knowledge
    triggers: list[str]
    content: str  # full SKILL.md content
    path: str  # e.g., "kernel-crash-analysis/SKILL.md"


def load_hiclaw_skills() -> list[HiClawSkill]:
    """Load all SKILL.md files from the HiClaw skills Git repo."""
    skills = []
    try:
        # List all SKILL.md files
        result = subprocess.run(
            ['git', '-C', REPO_PATH, 'ls-tree', '-r', '--name-only', 'HEAD'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            logger.warning(f'Failed to list skills repo: {result.stderr[:100]}')
            return []

        for line in result.stdout.strip().split('\n'):
            if not line.endswith('/SKILL.md'):
                continue
            # Skip templates
            if line.startswith('_'):
                continue

            # Read content
            content_result = subprocess.run(
                ['git', '-C', REPO_PATH, 'show', f'HEAD:{line}'],
                capture_output=True, text=True, timeout=5,
            )
            if content_result.returncode != 0:
                continue

            content = content_result.stdout
            name, description, skill_type, triggers = _parse_frontmatter(content)

            skills.append(HiClawSkill(
                name=name or line.split('/')[0],
                description=description,
                skill_type=skill_type,
                triggers=triggers,
                content=content,
                path=line,
            ))

        logger.info(f'Loaded {len(skills)} HiClaw skills: {[s.name for s in skills]}')
    except Exception as e:
        logger.warning(f'Failed to load HiClaw skills: {e}')

    return skills


def format_skills_for_prompt(skills: list[HiClawSkill], workspace: str = '') -> str:
    """Format skills into a system prompt suffix."""
    if not skills:
        return ''

    skills_dir = f'{workspace}/.hiclaw/skills'

    parts = [
        '<hiclaw_skills>',
        f'HiClaw skills are stored at: {skills_dir}/',
        'Each skill is a folder with a SKILL.md file and optional scripts/ directory.',
        '',
        'You CAN and SHOULD edit these skill files when the user asks you to:',
        f'- To read a skill: cat {skills_dir}/{{skill-name}}/SKILL.md',
        f'- To edit a skill: edit {skills_dir}/{{skill-name}}/SKILL.md',
        f'- To create a new skill: mkdir {skills_dir}/{{name}} && write SKILL.md',
        f'- To add a script: write to {skills_dir}/{{name}}/scripts/{{script}}',
        '',
        'When the user message matches a skill\'s trigger keywords, '
        'follow that skill\'s instructions.',
        '',
    ]

    for skill in skills:
        parts.append(f'<skill name="{skill.name}" type="{skill.skill_type}">')
        parts.append(f'Description: {skill.description}')
        if skill.triggers:
            parts.append(f'Triggers: {", ".join(skill.triggers)}')
        # Include full content (without frontmatter)
        body = _strip_frontmatter(skill.content)
        parts.append(body.strip())
        parts.append('</skill>')
        parts.append('')

    parts.append('</hiclaw_skills>')
    return '\n'.join(parts)


def _parse_frontmatter(content: str) -> tuple[str, str, str, list[str]]:
    """Parse YAML frontmatter. Returns (name, description, type, triggers)."""
    name = ''
    description = ''
    skill_type = 'skill'
    triggers: list[str] = []

    if not content.startswith('---'):
        return name, description, skill_type, triggers

    parts = content.split('---', 2)
    if len(parts) < 3:
        return name, description, skill_type, triggers

    fm = parts[1]
    in_keywords = False
    for line in fm.strip().split('\n'):
        stripped = line.strip()
        if stripped.startswith('name:'):
            name = stripped.split(':', 1)[1].strip().strip('"\'')
        elif stripped.startswith('description:'):
            description = stripped.split(':', 1)[1].strip().strip('"\'')
        elif stripped.startswith('type:'):
            skill_type = stripped.split(':', 1)[1].strip().strip('"\'')
        elif 'keywords:' in stripped:
            # Inline list: keywords: ["a", "b"]
            import re
            kws = re.findall(r'"([^"]+)"', stripped)
            triggers.extend(kws)
            in_keywords = True
        elif in_keywords and stripped.startswith('- '):
            kw = stripped.lstrip('- ').strip().strip('"\'')
            if kw:
                triggers.append(kw)
        elif not stripped.startswith('-'):
            in_keywords = False

    return name, description, skill_type, triggers


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from markdown."""
    if not content.startswith('---'):
        return content
    parts = content.split('---', 2)
    return parts[2] if len(parts) >= 3 else content
