"""Auto-seed built-in agents on first startup."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text as sql_text

from custom.agent_mgmt.models import AgentSkillLink, StoredAgent

_logger = logging.getLogger(__name__)


async def _link_skills_by_name(
    db: AsyncSession, agent_id: object, skill_names: list[str]
) -> None:
    """Reconcile an agent's skill list: link exactly `skill_names`.

    - Removes any existing link whose skill name is NOT in `skill_names`
      (so when a seed definition is trimmed down — e.g. render agent
      moving from 8 split skills to a single unified workflow — stale
      links from earlier seeds are cleaned up on next startup).
    - Inserts any link that's declared but missing.
    - Preserves links already present (no-op per existing skill).

    Uses raw SQL to avoid UUID type mismatches between tables.
    """
    # Normalize agent_id to hex string (no hyphens)
    aid = str(agent_id).replace('-', '')

    # Step 1: resolve the desired skill names to IDs, drop unknown.
    desired_ids: dict[str, str] = {}
    for name in skill_names:
        row = (
            await db.execute(
                sql_text('SELECT id FROM managed_skill WHERE name = :name'),
                {'name': name},
            )
        ).fetchone()
        if not row:
            _logger.debug(f'Skill not found for linking: {name}')
            continue
        desired_ids[name] = str(row[0]).replace('-', '')

    desired_sid_set = set(desired_ids.values())

    # Step 2: delete any existing agent_skill rows for this agent whose
    # skill isn't in the desired set.
    existing_rows = (
        await db.execute(
            sql_text(
                'SELECT s.id, s.skill_id, m.name FROM agent_skill s '
                'JOIN managed_skill m ON m.id = s.skill_id '
                'WHERE s.agent_id = :aid'
            ),
            {'aid': aid},
        )
    ).fetchall()
    existing_by_sid: dict[str, str] = {}
    for row_id, sid, name in existing_rows:
        sid_hex = str(sid).replace('-', '')
        existing_by_sid[sid_hex] = str(row_id)
        if sid_hex not in desired_sid_set:
            await db.execute(
                sql_text('DELETE FROM agent_skill WHERE id = :id'),
                {'id': str(row_id)},
            )
            _logger.info(f'Unlinked stale skill {name} from agent {aid[:12]}...')

    # Step 3: insert any desired skill that isn't already linked.
    for i, (name, sid) in enumerate(desired_ids.items()):
        if sid in existing_by_sid:
            continue
        link_id = uuid4().hex
        await db.execute(
            sql_text(
                'INSERT INTO agent_skill (id, agent_id, skill_id, sort_order) '
                'VALUES (:id, :aid, :sid, :sort)'
            ),
            {'id': link_id, 'aid': aid, 'sid': sid, 'sort': i},
        )
        _logger.info(f'Linked skill {name} to agent {aid[:12]}...')
    await db.commit()

PERF_AGENT_NAME = '性能分析 Agent'

# All perf-analysis skills that should be linked to the Perf Agent.
# `perf-analysis-workflow` is the workflow rule — it carries the `phases`
# frontmatter that drives the task-detail progress UI via
# bridge.get_workflow_phases() + router.py's auto-populate overlay.
# The rest are the analysis/utility skills the workflow invokes.
PERF_AGENT_SKILL_NAMES = [
    'perf-analysis-workflow',
    'trace-processor-init',
    'find-foreground-process',
    'find-launch-range',
    'analyze-main-thread-state',
    'main-thread-big-core-ratio',
    'analyze-cpu-frequency',
    'analyze-compile-level',
    'analyze-jit-thread',
    'analyze-main-thread-priority',
    'analyze-system-load',
    'analyze-detailed-load',
    'analyze-io-details',
    'analyze-non-io',
    'analyze-memory',
    'analyze-rendering-depth',
    'capture-trace-screenshot',
    'generate-report',
    'trace-processor-cleanup',
]

PERF_AGENT_DESCRIPTION = (
    '自动化 9 阶段 Perfetto trace 性能分析工作流。'
    '上传 Android trace 文件，选择分析方向，自动执行完整分析并生成 HTML 报告。'
)

PERF_AGENT_USAGE = """\
## 使用方式

1. 在 Agent 详情页点击「开始分析」
2. 输入 trace 文件路径（如 `/workspace/trace.perfetto-trace`）
3. 选择分析方向（完整分析 / CPU / 调度 / IO / 内存 / 渲染 等）
4. 点击「Analyze」开始分析

## 分析流程（9 阶段）

1. 初始化 Trace Processor
2. 查找前台进程
3. 确定启动时间范围
4. 主线程状态分析
5. 条件分支分析（Running/Runnable/Sleeping/IO/Non-IO）
6. 内存分析
7. 渲染分析
8. 清理 Trace Processor
9. 生成 HTML 报告

## 输出

- `/workspace/perf_analysis_output/full_report.html` — 完整报告
- `/workspace/perf_analysis_output/issue_report.html` — 问题摘要
"""


KERNEL_DIFF_AGENT_NAME = '内核对比分析 Agent'

KERNEL_DIFF_AGENT_DESCRIPTION = (
    'Android Common Kernel 月度版本对比分析。'
    '输入两个月度标签，自动克隆内核仓库、提取提交、分析 KO 模块影响，生成 Markdown 报告。'
)

KERNEL_DIFF_AGENT_USAGE = """\
## 使用方式

1. 在 Agent 详情页点击「开始分析」
2. 输入旧版本标签（如 `android-6.12-2025-08`）
3. 输入新版本标签（如 `android-6.12-2025-12`）
4. 点击「Analyze」开始分析

## 分析流程

1. 克隆/更新 Android Common Kernel 仓库
2. 提取两个标签之间的所有提交
3. 分析每个提交对 KO 模块的影响（Kconfig/Makefile/EXPORT_SYMBOL 等）
4. 按子系统分组，标记风险等级（高/中/低/无）
5. 生成 Markdown 分析报告

## 输出

- `kernel_analysis_report.md` — 完整对比分析报告
"""


def _load_workflow_content() -> str:
    """Load perf-analysis-workflow.md as system_prompt."""
    workflow_path = (
        Path(__file__).parent.parent
        / 'skill_examples'
        / 'perf_skills'
        / 'perf-analysis-workflow.md'
    )
    if workflow_path.exists():
        return workflow_path.read_text(encoding='utf-8')
    _logger.warning(f'Workflow skill not found: {workflow_path}')
    return ''


def _load_kernel_diff_content() -> str:
    """Load android-kernel-diff-analysis.md as system_prompt."""
    skill_path = (
        Path(__file__).parent.parent
        / 'skill_examples'
        / 'android-kernel-diff-analysis.md'
    )
    if skill_path.exists():
        return skill_path.read_text(encoding='utf-8')
    _logger.warning(f'Kernel diff skill not found: {skill_path}')
    return ''


async def seed_perf_agent(db: AsyncSession) -> None:
    """Create the built-in Performance Analysis Agent if it doesn't exist."""
    try:
        result = await db.execute(
            select(StoredAgent).where(StoredAgent.name == PERF_AGENT_NAME)
        )
        existing = result.scalars().first()
        if existing is not None:
            # Ensure config_json and usage_instructions are set
            changed = False
            if not existing.config_json:
                existing.config_json = json.dumps({'agent_type': 'perf-analysis'})
                changed = True
            if not existing.usage_instructions:
                existing.usage_instructions = PERF_AGENT_USAGE
                changed = True
            if not existing.system_prompt:
                existing.system_prompt = _load_workflow_content()
                changed = True
            if changed:
                await db.commit()
                _logger.info(f'Updated existing agent: {PERF_AGENT_NAME}')
            # Ensure perf skills are linked even on existing agents (idempotent).
            # This is what makes task-detail's phase progress bar work: without
            # a linked workflow skill, router.py's config_json.workflow_phases
            # overlay (via bridge.get_workflow_phases) never fires.
            await _link_skills_by_name(db, existing.id, PERF_AGENT_SKILL_NAMES)
            return

        agent_id = uuid4()
        agent = StoredAgent(
            id=agent_id,
            name=PERF_AGENT_NAME,
            description=PERF_AGENT_DESCRIPTION,
            system_prompt=_load_workflow_content(),
            category='performance',
            tags=json.dumps(['perfetto', 'trace', 'android', 'performance', '性能分析']),
            config_json=json.dumps({'agent_type': 'perf-analysis'}),
            usage_instructions=PERF_AGENT_USAGE,
            is_enabled=True,
            created_by='system',
        )
        db.add(agent)
        await db.commit()
        _logger.info(f'Seeded built-in agent: {PERF_AGENT_NAME}')

        # Link all perf skills so the workflow rule + analysis skills are
        # available to the agent and the progress UI has phases to render.
        await _link_skills_by_name(db, agent_id, PERF_AGENT_SKILL_NAMES)

    except Exception as e:
        _logger.warning(f'Failed to seed perf agent: {e}', exc_info=True)
        await db.rollback()


RENDER_AGENT_NAME = '渲染性能分析 Agent'

# Render agent skill set — the main workflow rule + one knowledge skill
# per phase script. Matches the 4-phase pipeline:
#   setup_env -> analyze_jank -> capture_screenshots -> render_report_generator
# Each knowledge skill md documents its phase script's CLI, inputs, and
# outputs so the LLM has precise per-phase guidance beyond the workflow
# rule's high-level table. The OLD 10-phase knowledge skills (init-
# render-jank-metric, analyze-jank-types, analyze-app-jank, analyze-
# sf-jank, capture-trace-screenshot, the old generate-report) were
# retired in commit d764e6eea — they documented scripts that no longer
# exist.
RENDER_AGENT_SKILL_NAMES = [
    'render-performance-workflow',
    'setup-env',
    'analyze-jank',
    'capture-screenshots',
    'render-report-generator',
]

RENDER_AGENT_DESCRIPTION = (
    'Android 应用绘制渲染性能分析。'
    '上传 Perfetto trace 文件，自动分析 Jank 类型分布、App/SF 层卡顿根因，生成 HTML 报告。'
)

RENDER_AGENT_USAGE = """\
## 使用方式

1. 在 Agent 详情页点击「开始分析」
2. 上传或输入 trace 文件路径
3. 选择分析重点（完整分析 / App Jank / SF Jank / 帧率统计）
4. 点击「Analyze」开始分析

## 分析流程（4 阶段）

1. 环境初始化（安装 perfetto / playwright / chromium）
2. Jank 分析（一次 SQL 扫描：目标进程 + jank 帧 + 线程映射）
3. Perfetto UI 截图（Top N 问题，全局图 + 细节图）
4. 生成 HTML 渲染报告（内嵌截图 + Framework 根因分析）

## 输出

- `/workspace/render_output/render_report.html` — 渲染性能报告
"""


def _load_render_workflow_content() -> str:
    """Load render-performance-workflow.md as system_prompt."""
    workflow_path = (
        Path(__file__).parent.parent
        / 'skill_examples'
        / 'render_skills'
        / 'render-performance-workflow.md'
    )
    if workflow_path.exists():
        return workflow_path.read_text(encoding='utf-8')
    _logger.warning(f'Render workflow skill not found: {workflow_path}')
    return ''


async def seed_render_agent(db: AsyncSession) -> None:
    """Create the built-in Render Performance Analysis Agent if it doesn't exist."""
    try:
        result = await db.execute(
            select(StoredAgent).where(StoredAgent.name == RENDER_AGENT_NAME)
        )
        existing = result.scalars().first()
        if existing is not None:
            changed = False
            if not existing.config_json:
                existing.config_json = json.dumps({'agent_type': 'render-analysis'})
                changed = True
            if not existing.usage_instructions:
                existing.usage_instructions = RENDER_AGENT_USAGE
                changed = True
            if not existing.system_prompt:
                existing.system_prompt = _load_render_workflow_content()
                changed = True
            if changed:
                await db.commit()
                _logger.info(f'Updated existing agent: {RENDER_AGENT_NAME}')
            await _link_skills_by_name(db, existing.id, RENDER_AGENT_SKILL_NAMES)
            return

        agent_id = uuid4()
        agent = StoredAgent(
            id=agent_id,
            name=RENDER_AGENT_NAME,
            description=RENDER_AGENT_DESCRIPTION,
            system_prompt=_load_render_workflow_content(),
            category='performance',
            tags=json.dumps(['android', 'render', 'jank', 'surfaceflinger', '渲染分析']),
            config_json=json.dumps({'agent_type': 'render-analysis'}),
            usage_instructions=RENDER_AGENT_USAGE,
            is_enabled=True,
            created_by='system',
        )
        db.add(agent)
        await db.commit()
        _logger.info(f'Seeded built-in agent: {RENDER_AGENT_NAME}')

        await _link_skills_by_name(db, agent_id, RENDER_AGENT_SKILL_NAMES)

    except Exception as e:
        _logger.warning(f'Failed to seed render agent: {e}', exc_info=True)
        await db.rollback()


async def seed_kernel_diff_agent(db: AsyncSession) -> None:
    """Create the built-in Kernel Diff Analysis Agent if it doesn't exist."""
    try:
        result = await db.execute(
            select(StoredAgent).where(StoredAgent.name == KERNEL_DIFF_AGENT_NAME)
        )
        existing = result.scalars().first()
        if existing is not None:
            changed = False
            if not existing.config_json:
                existing.config_json = json.dumps({'agent_type': 'kernel-diff'})
                changed = True
            if not existing.usage_instructions:
                existing.usage_instructions = KERNEL_DIFF_AGENT_USAGE
                changed = True
            if not existing.system_prompt:
                existing.system_prompt = _load_kernel_diff_content()
                changed = True
            if changed:
                await db.commit()
                _logger.info(f'Updated existing agent: {KERNEL_DIFF_AGENT_NAME}')
            # Ensure skill is linked
            await _link_skills_by_name(db, existing.id, ['android-kernel-diff-analysis'])
            return

        agent_id = uuid4()
        agent = StoredAgent(
            id=agent_id,
            name=KERNEL_DIFF_AGENT_NAME,
            description=KERNEL_DIFF_AGENT_DESCRIPTION,
            system_prompt=_load_kernel_diff_content(),
            category='kernel-analysis',
            tags=json.dumps(['android', 'kernel', 'ko', 'driver', '内核对比']),
            config_json=json.dumps({'agent_type': 'kernel-diff'}),
            usage_instructions=KERNEL_DIFF_AGENT_USAGE,
            is_enabled=True,
            created_by='system',
        )
        db.add(agent)
        await db.commit()
        _logger.info(f'Seeded built-in agent: {KERNEL_DIFF_AGENT_NAME}')

        # Link gyz's kernel-diff skill
        await _link_skills_by_name(db, agent_id, ['android-kernel-diff-analysis'])

    except Exception as e:
        _logger.warning(f'Failed to seed kernel diff agent: {e}', exc_info=True)
        await db.rollback()
