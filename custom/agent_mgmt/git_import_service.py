"""Git-based skill import service.

Clones a git repository containing workflow + skill files,
parses them, registers skills to DB, and creates an Agent.
"""

from __future__ import annotations

import json
import logging
import pathlib
import shutil
import subprocess
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)

# Where imported repos are stored
_SKILL_ROOT = pathlib.Path(__file__).parent.parent / 'skill_examples'


@dataclass
class ParsedSkill:
    """A skill parsed from a .md file."""
    name: str
    description: str
    content: str
    skill_type: str  # 'repo' or 'knowledge'
    triggers: list[str] = field(default_factory=list)
    phases: list[dict] | None = None
    version: str | None = None


@dataclass
class ImportResult:
    """Result of a git import operation."""
    success: bool
    agent_id: str | None = None
    agent_name: str | None = None
    skill_count: int = 0
    workflow_name: str | None = None
    local_dir: str | None = None
    error: str | None = None


def _sanitize_repo_name(git_url: str) -> str:
    """Extract a safe directory name from a git URL."""
    # https://gitlab.example.com/team/log-skills.git -> log-skills
    name = git_url.rstrip('/').rsplit('/', 1)[-1]
    if name.endswith('.git'):
        name = name[:-4]
    # Replace unsafe characters
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)


def clone_repo(git_url: str, branch: str = 'main', subdir: str | None = None,
               token: str | None = None) -> pathlib.Path:
    """Clone a git repository into skill_examples/.

    Args:
        git_url: Git clone URL
        branch: Branch name (default: main)
        subdir: Optional subdirectory within the repo to use
        token: Optional auth token (inserted into HTTPS URL)

    Returns:
        Path to the cloned skill directory
    """
    repo_name = _sanitize_repo_name(git_url)
    target_dir = _SKILL_ROOT / repo_name

    # If already exists, remove and re-clone
    if target_dir.exists():
        shutil.rmtree(target_dir)

    # Insert token into HTTPS URL if provided
    clone_url = git_url
    if token and clone_url.startswith('https://'):
        # https://gitlab.com/... -> https://oauth2:TOKEN@gitlab.com/...
        clone_url = clone_url.replace('https://', f'https://oauth2:{token}@')

    _logger.info(f'Cloning {git_url} branch={branch} into {target_dir}')

    try:
        cmd = ['git', 'clone', '--depth', '1', '--branch', branch, clone_url, str(target_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f'git clone failed: {result.stderr.strip()}')
    except subprocess.TimeoutExpired:
        raise RuntimeError('git clone timed out (120s)')

    # If subdir specified, move contents up
    if subdir:
        sub_path = target_dir / subdir.strip('/')
        if not sub_path.exists():
            raise RuntimeError(f'Subdirectory {subdir} not found in repo')
        # Move subdir contents to a temp location, remove rest, move back
        tmp = target_dir.parent / f'.tmp_{repo_name}'
        shutil.copytree(sub_path, tmp)
        shutil.rmtree(target_dir)
        shutil.move(str(tmp), str(target_dir))

    # Clean up .git directory to save space
    git_dir = target_dir / '.git'
    if git_dir.exists():
        shutil.rmtree(git_dir)

    _logger.info(f'Cloned successfully to {target_dir}')
    return target_dir


def parse_skills_from_dir(skill_dir: pathlib.Path) -> list[ParsedSkill]:
    """Parse all .md skill files from a directory.

    Returns list of ParsedSkill objects.
    """
    import frontmatter

    skills: list[ParsedSkill] = []
    for md_file in sorted(skill_dir.glob('*.md')):
        try:
            post = frontmatter.load(str(md_file))
            meta = post.metadata or {}

            name = meta.get('name', md_file.stem)
            skill_type = meta.get('type', 'knowledge')
            triggers = meta.get('triggers', [])
            phases = meta.get('phases')
            version = meta.get('version')

            # Extract first paragraph as description
            content = post.content
            desc_lines = []
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    desc_lines.append(line)
                    break
            description = desc_lines[0] if desc_lines else name

            skills.append(ParsedSkill(
                name=name,
                description=description,
                content=content,
                skill_type=skill_type,
                triggers=triggers,
                phases=phases,
                version=version,
            ))
        except Exception as e:
            _logger.warning(f'Failed to parse {md_file}: {e}')

    return skills


async def import_from_git(
    git_url: str,
    branch: str = 'main',
    subdir: str | None = None,
    token: str | None = None,
    agent_name: str | None = None,
    agent_description: str | None = None,
    agent_category: str | None = None,
) -> ImportResult:
    """Full import flow: clone repo → parse skills → register to DB → create Agent.

    Args:
        git_url: Git repository URL
        branch: Branch to clone
        subdir: Optional subdirectory within repo
        token: Optional auth token for private repos
        agent_name: Name for the created agent (auto-detected if not provided)
        agent_description: Description for the agent
        agent_category: Category for the agent

    Returns:
        ImportResult with agent_id and metadata
    """
    try:
        # Step 1: Clone
        skill_dir = clone_repo(git_url, branch, subdir, token)

        # Step 2: Parse
        skills = parse_skills_from_dir(skill_dir)
        if not skills:
            return ImportResult(success=False, error='No .md skill files found in repository')

        # Find workflow skill (type=repo with phases)
        workflow = None
        knowledge_skills = []
        for s in skills:
            if s.phases:
                workflow = s
            elif s.skill_type == 'knowledge':
                knowledge_skills.append(s)

        # Step 3: Register skills to DB
        from custom.agent_mgmt.db import get_agent_db
        from custom.skill_mgmt.db import get_skill_db
        from custom.skill_mgmt.service import SkillService
        from custom.skill_mgmt.models import SkillCreate, SkillUpdate
        from custom.agent_mgmt.service import AgentService
        from custom.agent_mgmt.models import AgentCreate

        skill_db = await get_skill_db()
        skill_svc = SkillService(skill_db)

        registered_skill_ids: list[str] = []
        for s in skills:
            try:
                # Check if skill already exists by name
                existing_list = await skill_svc.list_skills(limit=1, search=s.name)
                existing = next((sk for sk in existing_list if sk.name == s.name), None)
                if existing:
                    # Update existing skill
                    await skill_svc.update_skill(
                        existing.id,
                        SkillUpdate(description=s.description),
                    )
                    registered_skill_ids.append(existing.id)
                    _logger.info(f'Updated existing skill: {s.name}')
                else:
                    # Create new skill
                    detail = await skill_svc.create_skill(SkillCreate(
                        name=s.name,
                        content=s.content,
                        description=s.description,
                        triggers=s.triggers,
                        category=agent_category or 'imported',
                        skill_type=s.skill_type,
                    ))
                    registered_skill_ids.append(detail.id)
                    _logger.info(f'Registered new skill: {s.name}')
            except Exception as e:
                _logger.warning(f'Failed to register skill {s.name}: {e}')

        await skill_db.close()

        # Step 4: Create Agent
        if not agent_name:
            if workflow:
                # Derive from workflow name: log-analysis-workflow -> 日志分析 Agent
                agent_name = workflow.name.replace('-workflow', '').replace('-', ' ').title() + ' Agent'
            else:
                agent_name = _sanitize_repo_name(git_url).replace('-', ' ').title() + ' Agent'

        # Build config_json with git source info for future syncing
        config: dict = {
            'git_source': {
                'url': git_url,
                'branch': branch,
                'subdir': subdir,
                'imported_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
            }
        }
        if workflow and workflow.phases:
            # Normalize phases for frontend
            config['workflow_phases'] = [
                {'key': p.get('key', ''), 'label': p.get('label', ''), 'desc': p.get('desc', ''),
                 'file': p.get('output')}
                for p in workflow.phases
            ]

        # Build system_prompt from workflow content
        system_prompt = workflow.content if workflow else None

        agent_db = await get_agent_db()
        agent_svc = AgentService(agent_db)

        agent_data = AgentCreate(
            name=agent_name,
            description=agent_description or (workflow.description if workflow else f'Imported from {git_url}'),
            system_prompt=system_prompt,
            category=agent_category,
            config_json=json.dumps(config),
            skill_ids=registered_skill_ids,
        )
        agent_id = await agent_svc.create_agent(agent_data)
        await agent_db.close()

        _logger.info(f'Created agent "{agent_name}" (id={agent_id}) with {len(registered_skill_ids)} skills')

        return ImportResult(
            success=True,
            agent_id=agent_id,
            agent_name=agent_name,
            skill_count=len(registered_skill_ids),
            workflow_name=workflow.name if workflow else None,
            local_dir=str(skill_dir),
        )

    except Exception as e:
        _logger.error(f'Git import failed: {e}', exc_info=True)
        return ImportResult(success=False, error=str(e))


async def sync_agent_from_git(agent_id: str) -> ImportResult:
    """Re-pull the git repo and update skills for an existing agent.

    Reads git_source from agent's config_json, re-clones, and updates skills.
    Does NOT create a new agent — only updates skills and config.
    """
    from custom.agent_mgmt.db import get_agent_db
    from custom.agent_mgmt.service import AgentService
    from custom.agent_mgmt.models import AgentUpdate
    from custom.skill_mgmt.db import get_skill_db
    from custom.skill_mgmt.service import SkillService
    from custom.skill_mgmt.models import SkillCreate, SkillUpdate

    agent_db = await get_agent_db()
    agent_svc = AgentService(agent_db)
    agent = await agent_svc.get_agent(agent_id)

    if not agent:
        await agent_db.close()
        return ImportResult(success=False, error='Agent not found')

    config = json.loads(agent.config_json or '{}')
    git_source = config.get('git_source')
    if not git_source:
        await agent_db.close()
        return ImportResult(success=False, error='Agent has no git_source in config')

    try:
        # Step 1: Re-clone
        skill_dir = clone_repo(
            git_source['url'],
            git_source.get('branch', 'main'),
            git_source.get('subdir'),
        )

        # Step 2: Parse
        skills = parse_skills_from_dir(skill_dir)
        if not skills:
            await agent_db.close()
            return ImportResult(success=False, error='No .md skill files found after sync')

        workflow = next((s for s in skills if s.phases), None)

        # Step 3: Update skills in DB
        skill_db = await get_skill_db()
        skill_svc = SkillService(skill_db)
        registered_skill_ids: list[str] = []

        for s in skills:
            try:
                existing_list = await skill_svc.list_skills(limit=1, search=s.name)
                existing = next((sk for sk in existing_list if sk.name == s.name), None)
                if existing:
                    await skill_svc.update_skill(existing.id, SkillUpdate(description=s.description))
                    registered_skill_ids.append(existing.id)
                else:
                    detail = await skill_svc.create_skill(SkillCreate(
                        name=s.name, content=s.content, description=s.description,
                        triggers=s.triggers, category=agent.category or 'imported',
                        skill_type=s.skill_type,
                    ))
                    registered_skill_ids.append(detail.id)
            except Exception as e:
                _logger.warning(f'Failed to sync skill {s.name}: {e}')

        await skill_db.close()

        # Step 4: Update agent's skills and config
        await agent_svc.set_agent_skills(agent_id, registered_skill_ids)

        # Update config with refreshed phases and sync timestamp
        if workflow and workflow.phases:
            config['workflow_phases'] = [
                {'key': p.get('key', ''), 'label': p.get('label', ''), 'desc': p.get('desc', ''),
                 'file': p.get('output')}
                for p in workflow.phases
            ]
        config['git_source']['synced_at'] = __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat()

        await agent_svc.update_agent(agent_id, AgentUpdate(config_json=json.dumps(config)))
        await agent_db.close()

        _logger.info(f'Synced agent "{agent.name}" with {len(registered_skill_ids)} skills')
        return ImportResult(
            success=True, agent_id=agent_id, agent_name=agent.name,
            skill_count=len(registered_skill_ids),
            workflow_name=workflow.name if workflow else None,
            local_dir=str(skill_dir),
        )

    except Exception as e:
        await agent_db.close()
        _logger.error(f'Sync failed: {e}', exc_info=True)
        return ImportResult(success=False, error=str(e))
    )
