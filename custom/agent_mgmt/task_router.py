"""Task management API router."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from custom.agent_mgmt.db import get_agent_db
from custom.agent_mgmt.models import TaskCreate, TaskUpdate
from custom.agent_mgmt.service import AgentService
from custom.agent_mgmt.task_service import TaskService

router = APIRouter(prefix='/tasks', tags=['Tasks'])

TERMINAL_EXECUTION_STATUS_TO_TASK_STATUS = {
    'finished': 'completed',
    'stopped': 'completed',
    'error': 'failed',
    'rejected': 'failed',
}


async def _resolve_app_conversation_id(conversation_id: str) -> str | None:
    if not conversation_id:
        return None
    if not conversation_id.startswith('task-'):
        return conversation_id
    start_task_id = conversation_id[5:]
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f'http://127.0.0.1:12000/api/v1/app-conversations/start-tasks?ids={start_task_id}'
        )
        resp.raise_for_status()
        tasks_data = resp.json()
    if not tasks_data or not tasks_data[0]:
        return None
    return tasks_data[0].get('app_conversation_id')


async def _get_execution_status(app_conversation_id: str) -> str | None:
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f'http://127.0.0.1:12000/api/v1/app-conversations?ids={app_conversation_id}'
        )
        resp.raise_for_status()
        convs = resp.json()
    if not convs or not convs[0]:
        return None
    status = convs[0].get('execution_status')
    return status.lower() if isinstance(status, str) else None


async def _sync_task_status_from_execution(task_svc: TaskService, task_info):
    if task_info.status != 'running' or not task_info.conversation_id:
        return task_info
    try:
        app_conversation_id = await _resolve_app_conversation_id(
            task_info.conversation_id
        )
        if not app_conversation_id:
            return task_info
        execution_status = await _get_execution_status(app_conversation_id)
        new_status = TERMINAL_EXECUTION_STATUS_TO_TASK_STATUS.get(
            execution_status or ''
        )
        if not new_status:
            return task_info
        kwargs: dict = {'status': new_status}
        if new_status in ('completed', 'failed'):
            kwargs['completed_at'] = datetime.now(timezone.utc)
        await task_svc.update_task(task_info.id, **kwargs)
        updated = await task_svc.get_task(task_info.id)
        return updated if updated else task_info
    except Exception:
        return task_info


@router.get('')
async def list_tasks(
    created_by: str | None = Query(None),
    status: str | None = Query(None),
    agent_id: str | None = Query(None),
    conversation_id: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        tasks = await svc.list_tasks(
            created_by=created_by,
            status=status,
            agent_id=agent_id,
            conversation_id=conversation_id,
            search=search,
            limit=limit,
            offset=offset,
        )
        tasks = [await _sync_task_status_from_execution(svc, t) for t in tasks]
        total = await svc.count_tasks(
            created_by=created_by, status=status, agent_id=agent_id
        )
        return {'tasks': [t.model_dump() for t in tasks], 'total': total}
    finally:
        await db.close()


@router.post('')
async def create_task(data: TaskCreate):
    """Create a task and return task_id + conversation_id for frontend redirect."""
    db = await get_agent_db()
    try:
        agent_svc = AgentService(db)
        task_svc = TaskService(db)

        # Verify agent exists
        agent = await agent_svc.get_agent(data.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail='Agent not found')

        # Create task record
        task_id = await task_svc.create_task(
            agent_id=data.agent_id,
            name=data.name,
        )

        # Increment agent usage
        await agent_svc.increment_usage(data.agent_id)

        # NOTE: Conversation creation will be done by the frontend
        # by navigating to the home page and starting a new conversation
        # with the agent's system_prompt pre-filled.
        # The conversation_id is set later via PATCH /tasks/{id}

        return {
            'task_id': task_id,
            'agent': {
                'name': agent.name,
                'system_prompt': agent.system_prompt,
                'skill_ids': agent.skill_ids,
                'default_llm_model': agent.default_llm_model,
            },
        }
    finally:
        await db.close()


@router.get('/by-conversation/{conversation_id}')
async def get_task_by_conversation(conversation_id: str):
    """Reverse-lookup a task by the real app_conversation_id.

    Tasks persist ``conversation_id`` as ``task-<startTaskId>`` and not
    the URL-visible hex app_conversation_id, so the frontend cannot just
    filter ``/tasks?conversation_id=...`` to find the owning task from
    the chat page's conv id. This endpoint joins through the start-task
    table to resolve it.
    """
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        task = await svc.get_task_by_app_conversation(conversation_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        return task.model_dump()
    finally:
        await db.close()


@router.get('/{task_id}')
async def get_task(task_id: str):
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        task = await svc.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        task = await _sync_task_status_from_execution(svc, task)
        if task is None:
            raise HTTPException(status_code=404, detail='Task not found')
        return task.model_dump()
    finally:
        await db.close()


@router.patch('/{task_id}')
async def update_task(task_id: str, data: TaskUpdate):
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        kwargs: dict[str, Any] = {}
        if data.name is not None:
            kwargs['name'] = data.name
        if data.status is not None:
            kwargs['status'] = data.status
            if data.status == 'completed':
                kwargs['completed_at'] = datetime.now(timezone.utc)
        if not kwargs:
            return {'status': 'no_change'}
        ok = await svc.update_task(task_id, **kwargs)
        if not ok:
            raise HTTPException(status_code=404, detail='Task not found')
        return {'status': 'updated'}
    finally:
        await db.close()


class TaskStartRequest(BaseModel):
    conversation_id: str


@router.post('/{task_id}/start')
async def start_task(task_id: str, data: TaskStartRequest):
    """Link a task to a conversation and set status to running."""
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        ok = await svc.start_task(task_id, data.conversation_id)
        if not ok:
            raise HTTPException(status_code=404, detail='Task not found')
        return {'status': 'started'}
    finally:
        await db.close()


@router.post('/{task_id}/cancel')
async def cancel_task(task_id: str):
    db = await get_agent_db()
    try:
        svc = TaskService(db)
        # Get task to find conversation_id
        task = await svc.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')

        # Try to stop the running agent in sandbox
        conv_id = task.conversation_id
        if conv_id:
            import logging

            import httpx

            logger = logging.getLogger(__name__)
            try:
                if conv_id.startswith('task-'):
                    start_task_id = conv_id[5:]
                    async with httpx.AsyncClient(timeout=10) as client:
                        # Get start task info to find agent_server_url and app_conversation_id
                        resp = await client.get(
                            f'http://localhost:12000/api/v1/app-conversations/start-tasks?ids={start_task_id}'
                        )
                        if resp.status_code == 200:
                            tasks_data = resp.json()
                            if tasks_data and len(tasks_data) > 0 and tasks_data[0]:
                                st = tasks_data[0]
                                server_url = st.get('agent_server_url')
                                app_conv_id = st.get('app_conversation_id')
                                if server_url and app_conv_id:
                                    stop_resp = await client.post(
                                        f'{server_url}/api/conversations/{app_conv_id}/stop'
                                    )
                                    logger.info(
                                        f'Stop conversation {app_conv_id} via {server_url}: {stop_resp.status_code}'
                                    )
                else:
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.post(
                            f'http://localhost:12000/api/conversations/{conv_id}/stop'
                        )
                        logger.info(f'Stop conversation {conv_id}: {resp.status_code}')
            except Exception as e:
                logger.warning(f'Failed to stop conversation for task {task_id}: {e}')

        from datetime import datetime, timezone

        ok = await svc.update_task(
            task_id,
            status='cancelled',
            completed_at=datetime.now(timezone.utc),
        )
        if not ok:
            raise HTTPException(status_code=404, detail='Task not found')
        return {'status': 'cancelled'}
    finally:
        await db.close()
