"""Agent management API router."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from custom.agent_mgmt.db import get_agent_db
from custom.agent_mgmt.models import AgentCreate, AgentUpdate
from custom.agent_mgmt.service import AgentService

router = APIRouter(prefix='/agents', tags=['Agents'])


# ─── Git Import Models ──────────────────────────────────────────


class GitImportRequest(BaseModel):
    git_url: str
    branch: str = 'main'
    subdir: str | None = None
    token: str | None = None
    agent_name: str | None = None
    agent_description: str | None = None
    agent_category: str | None = None


# ─── Git Import Endpoints ───────────────────────────────────────


@router.post('/import-from-git')
async def import_from_git(data: GitImportRequest):
    """Clone a git repo containing workflow + skill files, register them, and create an Agent."""
    from custom.agent_mgmt.git_import_service import import_from_git as do_import

    result = await do_import(
        git_url=data.git_url,
        branch=data.branch,
        subdir=data.subdir,
        token=data.token,
        agent_name=data.agent_name,
        agent_description=data.agent_description,
        agent_category=data.agent_category,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return {
        'status': 'imported',
        'agent_id': result.agent_id,
        'agent_name': result.agent_name,
        'skill_count': result.skill_count,
        'workflow_name': result.workflow_name,
        'local_dir': result.local_dir,
    }


@router.post('/import-from-files')
async def import_from_files(
    files: list[UploadFile] = File(...),
    agent_name: str | None = Query(None),
    agent_description: str | None = Query(None),
    agent_category: str | None = Query(None),
):
    """Upload .md skill/workflow files to create an Agent (local file import)."""
    from custom.agent_mgmt.git_import_service import import_from_files as do_import

    # Read uploaded files into dict[filename, content]
    file_contents: dict[str, str] = {}
    for f in files:
        if not f.filename or not f.filename.endswith('.md'):
            continue
        raw = await f.read()
        file_contents[f.filename] = raw.decode('utf-8')

    if not file_contents:
        raise HTTPException(status_code=400, detail='No .md files found in upload')

    result = await do_import(
        file_contents=file_contents,
        agent_name=agent_name,
        agent_description=agent_description,
        agent_category=agent_category,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return {
        'status': 'imported',
        'agent_id': result.agent_id,
        'agent_name': result.agent_name,
        'skill_count': result.skill_count,
        'workflow_name': result.workflow_name,
    }


@router.post('/{agent_id}/sync')
async def sync_agent(agent_id: str):
    """Re-pull the git repo and update skills for an existing agent."""
    from custom.agent_mgmt.git_import_service import sync_agent_from_git

    result = await sync_agent_from_git(agent_id)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return {
        'status': 'synced',
        'skill_count': result.skill_count,
        'workflow_name': result.workflow_name,
    }


@router.get('')
async def list_agents(
    search: str | None = Query(None),
    category: str | None = Query(None),
    tag: str | None = Query(None),
    is_enabled: bool | None = Query(None),
    created_by: str | None = Query(None),
    sort_by: str = Query('created_at'),
    sort_order: str = Query('desc'),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        agents = await svc.list_agents(
            search=search, category=category, tag=tag, is_enabled=is_enabled,
            created_by=created_by, sort_by=sort_by, sort_order=sort_order,
            limit=limit, offset=offset,
        )
        total = await svc.count_agents(search=search, category=category, is_enabled=is_enabled)
        return {'agents': [a.model_dump() for a in agents], 'total': total}
    finally:
        await db.close()


@router.post('')
async def create_agent(data: AgentCreate):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        agent_id = await svc.create_agent(data)
        return {'id': agent_id}
    finally:
        await db.close()


@router.get('/categories')
async def list_categories():
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        return await svc.list_categories()
    finally:
        await db.close()


@router.get('/creators')
async def list_creators():
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        return await svc.list_creators()
    finally:
        await db.close()


@router.get('/favorites')
async def list_favorites(user_id: str = Query('default')):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        agents = await svc.list_favorites(user_id)
        return {'agents': [a.model_dump() for a in agents]}
    finally:
        await db.close()


@router.get('/{agent_id}')
async def get_agent(agent_id: str, user_id: str = Query('default')):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        agent = await svc.get_agent(agent_id, user_id=user_id)
        if not agent:
            raise HTTPException(status_code=404, detail='Agent not found')
        result = agent.model_dump()

        # Auto-populate workflow_phases from linked workflow skill's frontmatter
        if agent.skills and not _has_config_phases(result.get('config_json')):
            from custom.skill_mgmt.bridge import get_workflow_phases
            for skill in agent.skills:
                phases = get_workflow_phases(skill.name)
                if phases:
                    # Merge phases into config_json so frontend gets them automatically
                    import json
                    config = json.loads(result.get('config_json') or '{}')
                    config['workflow_phases'] = phases
                    result['config_json'] = json.dumps(config)
                    break  # Use first workflow skill's phases

        return result
    finally:
        await db.close()


def _has_config_phases(config_json: str | None) -> bool:
    """Check if config_json already has workflow_phases defined."""
    if not config_json:
        return False
    try:
        import json
        config = json.loads(config_json)
        return bool(config.get('workflow_phases'))
    except Exception:
        return False


@router.patch('/{agent_id}')
async def update_agent(agent_id: str, data: AgentUpdate):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        ok = await svc.update_agent(agent_id, data)
        if not ok:
            raise HTTPException(status_code=404, detail='Agent not found')
        return {'status': 'updated'}
    finally:
        await db.close()


@router.delete('/{agent_id}')
async def delete_agent(agent_id: str):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        ok = await svc.delete_agent(agent_id)
        if not ok:
            raise HTTPException(status_code=404, detail='Agent not found')
        return {'status': 'deleted'}
    finally:
        await db.close()


@router.put('/{agent_id}/skills')
async def set_agent_skills(agent_id: str, skill_ids: list[str]):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        await svc.set_agent_skills(agent_id, skill_ids)
        return {'status': 'updated'}
    finally:
        await db.close()


@router.post('/{agent_id}/favorite')
async def toggle_favorite(agent_id: str, user_id: str = Query('default')):
    db = await get_agent_db()
    try:
        svc = AgentService(db)
        is_favorited = await svc.toggle_favorite(agent_id, user_id)
        return {'is_favorited': is_favorited}
    finally:
        await db.close()
