"""Task management service - CRUD operations for tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4


def _to_uuid(val: str) -> UUID:
    try:
        return UUID(val)
    except ValueError:
        return UUID(val.replace('-', ''))

from sqlalchemy import delete, func, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from custom.agent_mgmt.models import StoredAgent, StoredTask, TaskInfo, TaskStatus


class TaskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_tasks(
        self,
        created_by: str | None = None,
        status: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskInfo]:
        stmt = select(StoredTask, StoredAgent.name.label('agent_name')).outerjoin(
            StoredAgent, StoredTask.agent_id == StoredAgent.id
        )

        if created_by:
            stmt = stmt.where(StoredTask.created_by == created_by)
        if status:
            stmt = stmt.where(StoredTask.status == status)
        if agent_id:
            stmt = stmt.where(StoredTask.agent_id == _to_uuid(agent_id))
        if conversation_id:
            stmt = stmt.where(StoredTask.conversation_id == conversation_id)
        if search:
            stmt = stmt.where(StoredTask.name.ilike(f'%{search}%'))

        stmt = stmt.order_by(StoredTask.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            TaskInfo(
                id=str(task.id),
                agent_id=str(task.agent_id) if task.agent_id else None,
                agent_name=agent_name,
                conversation_id=task.conversation_id,
                name=task.name,
                status=task.status,
                created_by=task.created_by,
                started_at=task.started_at,
                completed_at=task.completed_at,
                error_message=task.error_message,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task, agent_name in rows
        ]

    async def count_tasks(
        self,
        created_by: str | None = None,
        status: str | None = None,
        agent_id: str | None = None,
    ) -> int:
        stmt = select(func.count(StoredTask.id))
        if created_by:
            stmt = stmt.where(StoredTask.created_by == created_by)
        if status:
            stmt = stmt.where(StoredTask.status == status)
        if agent_id:
            stmt = stmt.where(StoredTask.agent_id == _to_uuid(agent_id))
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def get_task(self, task_id: str) -> TaskInfo | None:
        stmt = select(StoredTask, StoredAgent.name.label('agent_name')).outerjoin(
            StoredAgent, StoredTask.agent_id == StoredAgent.id
        ).where(StoredTask.id == _to_uuid(task_id))
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        if not row:
            return None

        task, agent_name = row
        return TaskInfo(
            id=str(task.id),
            agent_id=str(task.agent_id) if task.agent_id else None,
            agent_name=agent_name,
            conversation_id=task.conversation_id,
            name=task.name,
            status=task.status,
            created_by=task.created_by,
            started_at=task.started_at,
            completed_at=task.completed_at,
            error_message=task.error_message,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    async def get_task_by_app_conversation(
        self, app_conversation_id: str
    ) -> TaskInfo | None:
        """Reverse lookup a task by the *real* app_conversation_id.

        Tasks in this table store ``conversation_id`` in the form
        ``task-<startTaskId>`` (the v1 start-task id), never the real
        hex app_conversation_id. To find the owning task from a URL-
        visible conv id we first resolve ``app_conversation_id`` ->
        start_task_id via the ``AppConversationStartTask`` table in the
        same SQLite database, then look for a task whose
        conversation_id is ``task-<startId>``.
        """
        # Step 1: start-task join
        start_stmt = sql_text(
            'SELECT id FROM app_conversation_start_task '
            'WHERE app_conversation_id = :conv_id LIMIT 5'
        )
        res = await self.db.execute(start_stmt, {'conv_id': app_conversation_id})
        rows = res.fetchall()
        if not rows:
            return None

        candidate_ids = [f'task-{r[0].hex if hasattr(r[0], "hex") else str(r[0]).replace("-", "")}' for r in rows]

        # Step 2: task join
        stmt = select(StoredTask, StoredAgent.name.label('agent_name')).outerjoin(
            StoredAgent, StoredTask.agent_id == StoredAgent.id
        ).where(StoredTask.conversation_id.in_(candidate_ids)).order_by(
            StoredTask.created_at.desc()
        ).limit(1)
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        if not row:
            return None

        task, agent_name = row
        return TaskInfo(
            id=str(task.id),
            agent_id=str(task.agent_id) if task.agent_id else None,
            agent_name=agent_name,
            conversation_id=task.conversation_id,
            name=task.name,
            status=task.status,
            created_by=task.created_by,
            started_at=task.started_at,
            completed_at=task.completed_at,
            error_message=task.error_message,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    async def create_task(
        self,
        agent_id: str,
        name: str | None = None,
        created_by: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        task_id = uuid4()
        now = datetime.now(timezone.utc)

        # Get agent name for default task name
        if not name:
            stmt = select(StoredAgent.name).where(StoredAgent.id == _to_uuid(agent_id))
            result = await self.db.execute(stmt)
            agent_name = result.scalar_one_or_none()
            name = f'{agent_name} - {now.strftime("%m/%d %H:%M")}' if agent_name else f'Task {now.strftime("%m/%d %H:%M")}'

        task = StoredTask(
            id=task_id,
            agent_id=_to_uuid(agent_id),
            conversation_id=conversation_id,
            name=name,
            status=TaskStatus.PENDING.value,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(task)
        await self.db.commit()
        return str(task_id)

    async def update_task(self, task_id: str, **kwargs) -> bool:
        kwargs['updated_at'] = datetime.now(timezone.utc)
        stmt = update(StoredTask).where(StoredTask.id == _to_uuid(task_id)).values(**kwargs)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def start_task(self, task_id: str, conversation_id: str) -> bool:
        return await self.update_task(
            task_id,
            conversation_id=conversation_id,
            status=TaskStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )

    async def cancel_task(self, task_id: str) -> bool:
        return await self.update_task(task_id, status=TaskStatus.CANCELLED.value)
