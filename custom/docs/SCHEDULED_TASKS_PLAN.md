# Scheduled Tasks Implementation Plan

> **Branch:** `feat/scheduled-tasks` (off `dev` @ b5029dda0)
> **Goal:** Add recurring scheduled agent runs to the task center — users pick an agent, fill the agent's dynamic form once, choose a friendly schedule (hourly / daily / weekly / every N minutes / custom cron), and the platform fires the same agent run as a manual launch at each tick.
> **Architecture:** APScheduler in-process inside the uvicorn backend. Schedules persist in SQLite (`scheduled_task` + `scheduled_task_fire` tables). On lifespan startup the scheduler loads enabled schedules from DB. Fires reuse the existing `handleSelectAgent` generic path (create task → create conv → initial_message template-substituted from the schedule's preset form values).
> **Tech stack:** Python 3.12 / FastAPI / SQLAlchemy async / SQLite / APScheduler 3.x (sync `BackgroundScheduler`) / React 18 / DynamicFormPanel (existing).

---

## Non-functional requirements

Decided 2026-04-13:

- **Friendly UX, not raw cron.** Pickers for "每 N 分钟 / 每小时 / 每天 / 每周 / 自定义 cron"; raw cron is an advanced escape hatch.
- **Misfire makeup ON.** APScheduler `misfire_grace_time = 3600` (1 h). If backend restarts and a fire was missed, catch up on startup as long as scheduled time was within the grace window.
- **Queue, not concurrent.** `max_instances = 1` + `coalesce = True`. If a previous run for the same schedule is still executing, the next fire queues behind it; multiple missed fires collapse into one.
- **No permission gates.** Any user can CRUD their own schedules (no RBAC in MVP — internal tool).
- **Fire history + log always written.** Every fire writes a `scheduled_task_fire` row with start/end time, status, created task_id, error message.
- **Notification hook designed, not runtime-tested.** Pluggable `notify(schedule, fire_result)` interface with a no-op default implementation and a webhook stub. User will wire a real channel later.

---

## File structure

### Backend (new)

```
custom/scheduled_tasks/
├── __init__.py            # empty package marker
├── models.py              # StoredScheduledTask, StoredScheduledTaskFire SQLAlchemy models + Pydantic schemas
├── service.py             # ScheduledTaskService — CRUD + scheduler register/unregister helpers
├── scheduler.py           # module-level APScheduler instance + lifecycle (start/stop/register/unregister)
├── fire.py                # the coroutine that runs at each fire: build initial_message, create task + conv, write fire history
├── cron_util.py           # friendly schedule params -> APScheduler CronTrigger converter
├── notifier.py            # Notifier protocol + NoopNotifier + WebhookNotifier
└── router.py              # FastAPI router for /api/v1/scheduled-tasks CRUD + /fire-now + /fires
```

### Backend (modified)

- `custom/agent_mgmt/db.py` — register the 2 new tables in `_ensure_tables`.
- `openhands/server/app.py` — import and mount the scheduled-tasks router; call `scheduler.start()` / `scheduler.shutdown()` in the lifespan.
- `requirements-hiclaw.txt` or equivalent — add `APScheduler>=3.10,<4`.

### Frontend (new)

```
frontend/src/
├── api/custom-skill-service/scheduled-task-service.api.ts    # axios CRUD + fireNow + listFires
├── components/features/custom/scheduled-tasks/
│   ├── scheduled-task-list-page.tsx    # main list at /scheduled-tasks (table with enable toggle, next fire, edit, delete)
│   ├── scheduled-task-form.tsx         # modal: pick agent -> render DynamicFormPanel for preset -> schedule picker -> save
│   ├── schedule-picker.tsx             # friendly picker (radio group: hourly/daily/weekly/every-N-min/custom-cron)
│   └── scheduled-task-detail-page.tsx  # one schedule's fire history table with status + linked tasks
└── routes.ts                           # add route /scheduled-tasks and /scheduled-tasks/:id
```

### Frontend (modified)

- `frontend/src/components/features/custom/task-center/task-center-page.tsx` — add a "定时任务" tab/button that navigates to `/scheduled-tasks`.
- `frontend/src/routes.ts` — wire the 2 new routes (already listed above, restated for clarity).

---

## Task breakdown

Task numbering is execution order. Each task includes **files / interfaces / verification**. Steps are bite-sized so any single failure rolls back cleanly.

### Task 1: Dependency + table bootstrap

**Files:**
- Create `custom/scheduled_tasks/__init__.py`
- Create `custom/scheduled_tasks/models.py`
- Modify `custom/agent_mgmt/db.py` — register the new tables
- Add `APScheduler` to whatever dependency manifest this repo uses

- [ ] 1.1 Add `APScheduler>=3.10,<4` to the dependency list (check whether this repo uses `pyproject.toml` + poetry or `requirements.txt`, add accordingly).
- [ ] 1.2 Create `custom/scheduled_tasks/__init__.py` empty.
- [ ] 1.3 Create `custom/scheduled_tasks/models.py`:
  - SQLAlchemy models:
    - `StoredScheduledTask` — id (uuid4 hex), agent_id (FK str), name, schedule_kind (enum str: `every_n_minutes` / `hourly` / `daily` / `weekly` / `custom_cron`), schedule_params (JSON TEXT), form_values (JSON TEXT), enabled (bool), created_by (str), created_at / updated_at / last_fire_at / next_fire_at / last_status.
    - `StoredScheduledTaskFire` — id (uuid hex), scheduled_task_id (FK), started_at, completed_at, status (`running` / `success` / `failed` / `skipped_concurrent`), task_id (the `agent_task.id` created by this fire — nullable), conversation_id (nullable), error_message (nullable text).
  - Pydantic models for router I/O: `ScheduledTaskCreate`, `ScheduledTaskUpdate`, `ScheduledTaskInfo`, `ScheduledTaskFireInfo`.
- [ ] 1.4 Modify `custom/agent_mgmt/db.py` `_ensure_tables()` to include the 2 new tables in the `Base.metadata.create_all` call.
- [ ] 1.5 Smoke-test: `python -c "from custom.scheduled_tasks.models import StoredScheduledTask, StoredScheduledTaskFire"` — import should succeed.
- [ ] 1.6 Commit: `feat(scheduled-tasks): tables + models + APScheduler dep`.

### Task 2: Cron-util (friendly params → CronTrigger)

**Files:** Create `custom/scheduled_tasks/cron_util.py`

- [ ] 2.1 Write `schedule_params_to_trigger(kind: str, params: dict) -> BaseTrigger`:
  - `every_n_minutes` → `IntervalTrigger(minutes=params["minutes"])`
  - `hourly` → `CronTrigger(minute=params.get("minute", 0))`
  - `daily` → `CronTrigger(hour=params["hour"], minute=params.get("minute", 0))`
  - `weekly` → `CronTrigger(day_of_week=params["day_of_week"], hour=params["hour"], minute=params.get("minute", 0))` — `day_of_week` is 0-6 (mon-sun) or comma list like `"mon,wed,fri"`
  - `custom_cron` → `CronTrigger.from_crontab(params["cron"])`
- [ ] 2.2 Write `describe_schedule(kind, params) -> str` — a short human string like "每天 09:00", "每 15 分钟", "每周一三五 18:30" for display on the task center list.
- [ ] 2.3 Smoke test in python: all 5 branches produce a trigger without exception.
- [ ] 2.4 Commit: `feat(scheduled-tasks): friendly schedule params → APScheduler trigger`.

### Task 3: Notifier protocol

**Files:** Create `custom/scheduled_tasks/notifier.py`

- [ ] 3.1 Define `Notifier` protocol: `async def notify(self, schedule: StoredScheduledTask, fire: StoredScheduledTaskFire) -> None`.
- [ ] 3.2 Implement `NoopNotifier` — logs to stdout, does nothing else.
- [ ] 3.3 Implement `WebhookNotifier` — reads `SCHEDULED_TASKS_WEBHOOK_URL` from env; if set, POST a JSON `{schedule_id, schedule_name, status, error, fire_id, task_id, timestamp}` via `httpx.AsyncClient`; on any error log a warning and swallow (notifications are best-effort).
- [ ] 3.4 Module-level singleton: `get_notifier()` returns `WebhookNotifier()` if `SCHEDULED_TASKS_WEBHOOK_URL` is set, else `NoopNotifier()`.
- [ ] 3.5 Commit: `feat(scheduled-tasks): notifier hook + webhook stub`.

### Task 4: Service layer (CRUD without scheduler coupling)

**Files:** Create `custom/scheduled_tasks/service.py`

- [ ] 4.1 `class ScheduledTaskService`:
  - `list_schedules(enabled: bool | None = None) -> list[ScheduledTaskInfo]`
  - `get_schedule(schedule_id: str) -> ScheduledTaskInfo | None`
  - `create_schedule(data: ScheduledTaskCreate) -> str` (returns id)
  - `update_schedule(schedule_id: str, data: ScheduledTaskUpdate) -> bool`
  - `delete_schedule(schedule_id: str) -> bool`
  - `list_fires(schedule_id: str, limit: int = 50) -> list[ScheduledTaskFireInfo]`
  - `create_fire(schedule_id: str) -> StoredScheduledTaskFire` (status=running)
  - `update_fire(fire_id: str, **kwargs) -> None`
- [ ] 4.2 Commit: `feat(scheduled-tasks): CRUD service layer`.

### Task 5: Fire function (the actual agent invocation)

**Files:** Create `custom/scheduled_tasks/fire.py`

- [ ] 5.1 Write `async def fire_schedule(schedule_id: str) -> None`:
  1. Load schedule via service. Abort if disabled or not found (log + return).
  2. Create fire row with status=`running`.
  3. Load the agent: `GET /api/v1/agents/{id}` locally (via HTTP to 127.0.0.1:12000 since we're inside the same process — alternative: call `AgentService.get_agent` directly; preferred).
  4. Resolve the `submit_message` template: use the same logic as DynamicFormPanel client-side — `{{key}}` replacement over the stored `form_values`, then strip leftover `{{...}}`.
  5. Create an agent_task: `TaskService.create_task(agent_id=...)`.
  6. Create a conversation via `POST /api/v1/app-conversations/start-tasks` with `initial_message` = resolved template (internal HTTP to 12000 or direct service call — whichever is cleaner in this repo).
  7. Link the task to the conversation: `TaskService.start_task(task_id, conv_id)`.
  8. Update fire row: `success`, task_id, conversation_id, completed_at.
  9. Notify: `notifier = get_notifier(); await notifier.notify(schedule, fire)`.
  10. On any exception: update fire row with `failed` + error message, notify, re-raise for APScheduler to log.
- [ ] 5.2 Commit: `feat(scheduled-tasks): fire function wiring agent launch`.

### Task 6: Scheduler lifecycle

**Files:** Create `custom/scheduled_tasks/scheduler.py`

- [ ] 6.1 Module-level singleton:
  ```python
  _scheduler: BackgroundScheduler | None = None

  def get_scheduler() -> BackgroundScheduler:
      global _scheduler
      if _scheduler is None:
          _scheduler = BackgroundScheduler(
              job_defaults={
                  "coalesce": True,
                  "max_instances": 1,
                  "misfire_grace_time": 3600,
              },
              timezone="Asia/Shanghai",
          )
      return _scheduler
  ```
- [ ] 6.2 `def start()`:
  - `get_scheduler().start()`
  - Load all enabled schedules from DB via `ScheduledTaskService.list_schedules(enabled=True)`
  - For each, register the job (see step 6.3)
- [ ] 6.3 `def register_schedule(schedule: ScheduledTaskInfo)`:
  - Convert params to trigger via `cron_util.schedule_params_to_trigger`
  - `scheduler.add_job(fire_schedule_sync, trigger=..., args=[schedule.id], id=schedule.id, replace_existing=True)`
  - Where `fire_schedule_sync` = sync wrapper that runs `asyncio.run(fire_schedule(id))` (APScheduler `BackgroundScheduler` expects sync callables).
- [ ] 6.4 `def unregister_schedule(schedule_id: str)`: `scheduler.remove_job(schedule_id, jobstore='default')` (catch `JobLookupError`).
- [ ] 6.5 `def reschedule(schedule_id: str)` — unregister then re-register (used on update).
- [ ] 6.6 `def shutdown()` — `scheduler.shutdown(wait=False)` if running.
- [ ] 6.7 Modify `openhands/server/app.py` lifespan:
  - In try block: `from custom.scheduled_tasks.scheduler import start as _start_sched, shutdown as _stop_sched; _start_sched()`
  - In teardown: `_stop_sched()`
- [ ] 6.8 Commit: `feat(scheduled-tasks): APScheduler lifecycle + job register/unregister`.

### Task 7: Router

**Files:** Create `custom/scheduled_tasks/router.py`; modify `openhands/server/app.py`

- [ ] 7.1 Endpoints:
  - `GET /api/v1/scheduled-tasks` — list, optional `?enabled=true/false`
  - `GET /api/v1/scheduled-tasks/{id}` — detail (with `next_fire_at` computed from scheduler)
  - `POST /api/v1/scheduled-tasks` — create; side-effect: register with scheduler if enabled
  - `PATCH /api/v1/scheduled-tasks/{id}` — update; side-effect: reschedule if schedule-related field changed, or unregister if `enabled=false`
  - `DELETE /api/v1/scheduled-tasks/{id}` — delete; side-effect: unregister
  - `POST /api/v1/scheduled-tasks/{id}/fire-now` — manually trigger one fire right now, bypassing schedule
  - `GET /api/v1/scheduled-tasks/{id}/fires` — fire history with `?limit=50`
- [ ] 7.2 Mount in `app.py` next to the existing `_task_router` mount.
- [ ] 7.3 Curl smoke test each endpoint (list empty, create one, fire-now, list fires, delete).
- [ ] 7.4 Commit: `feat(scheduled-tasks): REST router + mount`.

### Task 8: Frontend API service

**Files:** Create `frontend/src/api/custom-skill-service/scheduled-task-service.api.ts`

- [ ] 8.1 Types `ScheduledTaskInfo`, `ScheduledTaskFireInfo`, `ScheduledTaskCreate`, `ScheduledTaskUpdate`.
- [ ] 8.2 `ScheduledTaskService` class with `listSchedules`, `getSchedule`, `createSchedule`, `updateSchedule`, `deleteSchedule`, `fireNow`, `listFires`.
- [ ] 8.3 Commit: `feat(scheduled-tasks): frontend API service`.

### Task 9: Friendly schedule picker

**Files:** Create `frontend/src/components/features/custom/scheduled-tasks/schedule-picker.tsx`

- [ ] 9.1 Component `<SchedulePicker value={{kind, params}} onChange={...}>`:
  - Radio buttons: `每 N 分钟 / 每小时 / 每天 / 每周 / 自定义 cron`
  - Conditional inputs per kind:
    - every_n_minutes: number input (1-1440)
    - hourly: minute input (0-59)
    - daily: hour + minute inputs
    - weekly: checkbox row (周一/二/三/四/五/六/日) + hour + minute
    - custom_cron: text input + hint "5 字段格式，如 `0 9 * * *`"
  - Preview line below: "每天 09:00" (call a small `describe()` helper mirroring the backend cron_util)
- [ ] 9.2 Commit: `feat(scheduled-tasks): friendly schedule picker component`.

### Task 10: Schedule form (create/edit modal)

**Files:** Create `frontend/src/components/features/custom/scheduled-tasks/scheduled-task-form.tsx`

- [ ] 10.1 Props: `initialValue?: ScheduledTaskInfo`, `onSaved: () => void`, `onCancel: () => void`.
- [ ] 10.2 State: agent_id, name, schedule (kind/params), form_values, enabled.
- [ ] 10.3 On agent select:
  - Fetch `AgentService.getAgent(id)` → parse `config.input_form`
  - Render a **preset editor** — reuse `DynamicFormPanel` with a custom `onSubmit` that simply collects values without navigating (or add an `inline: true` prop to DynamicFormPanel to surface values via `onChange` instead of `onSubmit`). If adding a prop is risky, copy DynamicFormPanel's rendering into a local `PresetFormEditor` that exposes values.
- [ ] 10.4 Include `<SchedulePicker>` from Task 9.
- [ ] 10.5 Submit button calls `ScheduledTaskService.createSchedule({...})` or `updateSchedule(id, ...)`, then `onSaved()`.
- [ ] 10.6 Commit: `feat(scheduled-tasks): create/edit form with preset + picker`.

### Task 11: List page

**Files:** Create `frontend/src/components/features/custom/scheduled-tasks/scheduled-task-list-page.tsx`

- [ ] 11.1 Table columns: name, agent, schedule (human string), 上次执行, 下次执行, enabled toggle, [编辑] [删除] [立即执行] [查看历史] buttons.
- [ ] 11.2 "新建定时任务" button opens `<ScheduledTaskForm>` in modal.
- [ ] 11.3 Enable toggle calls `updateSchedule({enabled: !current})`.
- [ ] 11.4 Delete confirms then `deleteSchedule()`.
- [ ] 11.5 Commit: `feat(scheduled-tasks): list page`.

### Task 12: Detail page (fire history)

**Files:** Create `frontend/src/components/features/custom/scheduled-tasks/scheduled-task-detail-page.tsx`

- [ ] 12.1 Schedule info card at top (reuse the list row shape).
- [ ] 12.2 Fire history table: started_at, completed_at, status badge, duration, 关联任务 link → `/tasks/{task_id}`, 错误 (if failed).
- [ ] 12.3 "立即执行一次" button at top.
- [ ] 12.4 Commit: `feat(scheduled-tasks): detail + fire history page`.

### Task 13: Route + task center integration

**Files:** modify `frontend/src/routes.ts` + `task-center-page.tsx`

- [ ] 13.1 Add routes `/scheduled-tasks` → `ScheduledTaskListPage`, `/scheduled-tasks/:id` → `ScheduledTaskDetailPage`.
- [ ] 13.2 In task center top bar add a tab/link "定时任务" that navigates to `/scheduled-tasks`. Keep the original "任务" tab default.
- [ ] 13.3 Commit: `feat(scheduled-tasks): route + task center tab`.

### Task 14: End-to-end test

- [ ] 14.1 Restart backend on dev — verify scheduler starts, no existing schedules loaded, log says "Scheduler started with 0 jobs".
- [ ] 14.2 Open 任务中心 → 定时任务 tab → 新建.
- [ ] 14.3 Pick 渲染性能分析 Agent → render form shows the 4 input_form fields → upload trace, pick focus, top_n, extra.
- [ ] 14.4 Schedule: 每 2 分钟 (pick `every_n_minutes` = 2).
- [ ] 14.5 Save.
- [ ] 14.6 Verify: list shows 1 row, next_fire_at within 2 minutes.
- [ ] 14.7 Wait 2 minutes. Verify: a new `agent_task` row is created, linked conversation exists, fire row has status=success.
- [ ] 14.8 Check fire history page shows the fire + clickable task link.
- [ ] 14.9 Disable the schedule, verify next fire doesn't happen.
- [ ] 14.10 Delete the schedule, verify job gone from scheduler internal state.

---

## Open design questions already resolved

| Question | Decision |
|---|---|
| Cron UX | Friendly picker (radio + conditional inputs), custom cron as advanced fallback |
| Misfire makeup | ON, grace window 1h |
| Concurrency | Queue (max_instances=1 + coalesce) |
| Permissions | None in MVP |
| Logging | Every fire writes `scheduled_task_fire` row |
| Notifications | Designed (webhook stub), not runtime-tested |
| Timezone | `Asia/Shanghai` hardcoded for MVP |
| Default fire flow | Reuse TaskService.create_task + app-conversations start-task path — identical to manual launch |

## Notes for the executor

- **Task 5 (fire function)** is the highest-risk step — it replicates the client-side `handleSelectAgent` generic flow on the server. Double-check the `start-task` payload shape by reading `interactive-chat-box.tsx:84-104`.
- **Task 6.3 `fire_schedule_sync`** must handle `asyncio.run` — be careful if the backend already has a running loop. Safer option: use `AsyncIOScheduler` instead of `BackgroundScheduler`, which accepts async callables directly. If the uvicorn loop is accessible from inside the scheduler thread, stick with `BackgroundScheduler`. Decide at Task 6 time.
- **Task 10.3** may need a small refactor of `DynamicFormPanel` to add an `onChange` variant (vs the current `onSubmit`-only). Keep the change backward-compatible.
