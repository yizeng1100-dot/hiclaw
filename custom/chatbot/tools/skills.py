"""Tools for browsing and reading skill .md files.

Scans ``custom/skill_examples/<category>/**.md`` at call time so the
bot always sees the latest state on disk — no caching past a single
tool call.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import frontmatter

from custom.chatbot.tools.base import Tool, register

_logger = logging.getLogger(__name__)

_SKILL_ROOT = Path(__file__).resolve().parent.parent.parent / 'skill_examples'
_READ_MAX_BYTES = 50 * 1024  # cap single skill read at 50 KB for context safety


async def _list_skills(args: dict[str, Any]) -> Any:
    category_filter = args.get('category')
    out: list[dict[str, Any]] = []
    if not _SKILL_ROOT.is_dir():
        return []
    for category_dir in sorted(_SKILL_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        if category_filter and category_filter != category:
            continue
        for md_file in sorted(category_dir.rglob('*.md')):
            try:
                post = frontmatter.load(str(md_file))
                meta = post.metadata or {}
                name = meta.get('name') or md_file.stem
                out.append(
                    {
                        'name': name,
                        'description': meta.get('description'),
                        'type': meta.get('type'),
                        'category': category,
                        'path': str(md_file.relative_to(_SKILL_ROOT)),
                    }
                )
            except Exception as e:
                _logger.debug(f'failed to parse {md_file}: {e}')
    return out


async def _read_skill(args: dict[str, Any]) -> Any:
    name = args.get('name')
    if not name:
        return {'error': 'name required'}
    if not _SKILL_ROOT.is_dir():
        return {'error': 'skill_examples dir not found'}
    for md_file in _SKILL_ROOT.rglob('*.md'):
        try:
            post = frontmatter.load(str(md_file))
            meta = post.metadata or {}
            if (meta.get('name') or md_file.stem) != name:
                continue
            raw = md_file.read_text(encoding='utf-8')
            if len(raw.encode('utf-8')) > _READ_MAX_BYTES:
                truncated = raw[: _READ_MAX_BYTES // 2]
                return {
                    'name': name,
                    'path': str(md_file.relative_to(_SKILL_ROOT)),
                    'content': truncated,
                    'truncated': True,
                    'note': (
                        'skill file too large; returned first '
                        f'{_READ_MAX_BYTES // 2} bytes'
                    ),
                }
            return {
                'name': name,
                'path': str(md_file.relative_to(_SKILL_ROOT)),
                'content': raw,
                'truncated': False,
            }
        except Exception as e:
            _logger.debug(f'failed reading {md_file}: {e}')
    return {'error': f'skill {name!r} not found'}


register(
    Tool(
        name='list_skills',
        description=(
            '列出所有 skill .md 文件（HiClaw 的 agent workflow 定义 + 各个分析步骤的知识）。'
            '可按 category（子目录名）过滤，例如 render_skills / perf_skills / log_analysis。'
            '返回每个 skill 的 name / description / type / category / 相对路径。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'category': {
                    'type': 'string',
                    'description': '只返回这个子目录下的 skill（如 render_skills）',
                },
            },
            'required': [],
        },
        run=_list_skills,
    )
)


register(
    Tool(
        name='read_skill',
        description=(
            '读取一个 skill .md 文件的完整内容（frontmatter + markdown 正文）。'
            '用来回答 "XX 这个 skill 里写了什么" 或 "workflow 里指定了哪几个 phase"。'
            'name 必须是 list_skills 返回的 name，不是文件路径。最大 50 KB，'
            '超过会截断。'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'name': {
                    'type': 'string',
                    'description': '来自 list_skills 的 name 字段',
                },
            },
            'required': ['name'],
        },
        run=_read_skill,
    )
)
