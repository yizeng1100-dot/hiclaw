# Platform Chatbot Implementation Plan

> **Branch:** `feat/chat-bot` (off `dev` @ 2918fd891)
> **Goal:** A web-native chat page on `/chat` where users can have a multi-turn conversation with an LLM that knows about HiClaw platform state (agents / skills / tasks / scheduled tasks) and can trigger read-only queries and simple write actions through function calling.
> **Architecture:** LLM proxy inside the backend (reuses the existing OpenHands LLM settings), OpenAI-style function calling loop, compact tool set focused on platform introspection + agent launching, SSE streaming to the frontend. No sandbox, no agent loop — this is pure chat + platform-aware tools.
> **Out of scope (MVP):** multi-session history list, arbitrary bash, arbitrary file reads outside conversation working dirs, vector retrieval over docs.

---

## Why this is distinct from existing agents

- **Existing agents** run in a sandbox and have CodeActAgent tools (bash, file edit, browser). They're heavy — each launch spins up a sandbox container.
- **This chatbot** runs *inside the backend process*, answers general questions about the platform, and uses narrow tools like `list_agents()` / `trigger_task()`. No sandbox → millisecond responses for pure Q&A, seconds for tool calls.

Use cases it's good at:
- "帮我列一下所有失败的 render 任务"
- "渲染性能分析 Agent 的 workflow 有哪几个 phase？"
- "帮我跑一次 `render-performance-workflow`，trace 文件我等下上传"
- "`render-report-generator.md` 里写了什么？"

Use cases it's NOT for:
- "写段 python 帮我处理这个 csv"（用 CodeActAgent / 通用 agent）
- "打开 render_report.html 看看里面长什么样"（打开浏览器自己看）

---

## File structure

### Backend — new package `custom/chatbot/`

```
custom/chatbot/
├── __init__.py              # marker
├── router.py                # /api/v1/chat/completions (non-stream) + /stream (SSE)
├── llm_client.py            # litellm wrapper that reads OpenHands settings
├── system_prompt.py         # HiClaw platform knowledge + tool usage guide
├── executor.py              # multi-turn loop: call LLM → run tool calls → loop
└── tools/
    ├── __init__.py          # Tool registry + dispatch
    ├── base.py              # Tool protocol, schema helpers
    ├── agents.py            # list_agents / get_agent
    ├── tasks.py             # list_tasks / get_task
    ├── schedules.py         # list_scheduled_tasks / get_scheduled_task
    ├── skills.py            # list_skills / read_skill
    └── launch.py            # trigger_agent (create task + conv)
```

### Backend — modified

- `openhands/server/app.py` — mount the chatbot router under `/api/v1`.

### Frontend — new `components/features/custom/chatbot/` dir

```
frontend/src/components/features/custom/chatbot/
├── chat-page.tsx            # main layout: message list + input + controls
├── message-list.tsx         # scrollable history + auto-scroll-to-bottom
├── message-bubble.tsx       # user (blue) vs bot (gray) bubble + markdown render
├── tool-call-chip.tsx       # inline "工具调用: list_tasks({status:'failed'})" badge
├── chat-input.tsx           # textarea + send button + enter-to-send
├── use-chat.ts              # hook: message list, send, streaming state, localStorage
└── markdown-renderer.tsx    # react-markdown + code highlighting
```

### Frontend — new route files

```
frontend/src/api/custom-skill-service/chatbot-service.api.ts
frontend/src/routes/chat.tsx
```

### Frontend — modified

- `frontend/src/routes.ts` — add `/chat` route
- `frontend/src/components/features/sidebar/sidebar.tsx` (or whichever nav component has 任务中心/Agent 中心 entries) — add "Chat" entry

---

## Tool set (MVP)

All tools are async Python functions with a Pydantic input schema. The executor exposes them to the LLM via OpenAI function calling format.

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `list_agents` | `search?`, `category?`, `limit=20` | list of `{id, name, description, category}` | Calls `AgentService.list_agents` directly |
| `get_agent` | `agent_id` | full agent config_json including workflow_phases / input_form / reports | So the bot can answer "这个 agent 有哪些 phase" / "这个 agent 要什么输入参数" |
| `list_tasks` | `status?`, `agent_id?`, `limit=20` | list of `{id, name, agent_name, status, started_at, completed_at}` | `TaskService.list_tasks` |
| `get_task` | `task_id` | task detail + related conversation_id | |
| `list_scheduled_tasks` | — | list of schedule info | `ScheduledTaskService.list_schedules` |
| `get_scheduled_task` | `schedule_id` | schedule detail + fire history (last 5) | |
| `list_skills` | `category?` (dir name) | list of `{name, description, category}` | Scan `custom/skill_examples/*/*.md` frontmatter |
| `read_skill` | `name` | full md content (frontmatter + body) | |
| `trigger_agent` | `agent_id`, `form_values?: dict` | `{task_id, conversation_id}` | Same path as manual launch — creates task, creates v1 app-conversation with templated initial_message. Tool description explicitly says "user must confirm before calling this" so the bot asks first. |

**Future (not MVP):**
- `read_file(path)` — arbitrary file read under `custom/` for debugging a skill
- `search_docs(query)` — grep over `custom/docs/` + skill .md files
- `list_fires(schedule_id)` — more history
- `cancel_task(task_id)` — pairs with trigger_agent

---

## System prompt shape

```
You are HiClaw Chat — a chatbot that knows the HiClaw analysis platform
and helps users discover agents, inspect tasks, and launch runs.

Platform concepts you should know:
- Agent: a pre-configured analysis pipeline exposed in the 'Agent 中心' page.
  Current built-in agents include 性能分析 Agent (perf), 渲染性能分析 Agent
  (render), 内核对比分析 Agent (kernel-diff).
- Skill: a reusable .md file with frontmatter under custom/skill_examples/.
  Workflow skills declare `phases`, `input_form`, and `reports`.
- Task (in 任务中心): one execution of an agent, linked to a conversation.
- Scheduled task (in 定时任务): a recurring schedule that fires an agent run.
- Conversation: the chat-with-agent UI where a task's execution is shown.

Tools you can call (via function calling): list_agents, get_agent,
list_tasks, get_task, list_scheduled_tasks, get_scheduled_task,
list_skills, read_skill, trigger_agent.

Guidelines:
- If the user asks a factual question about platform state (e.g. "which
  tasks failed yesterday"), call the matching tool and summarize — do
  NOT make up IDs or timestamps.
- Before calling trigger_agent, ALWAYS confirm with the user which
  agent and what form_values to use. Never trigger a task without
  explicit confirmation.
- For read_skill, pass the exact skill name from list_skills, not a
  guess.
- Answer in Chinese unless the user writes in English.
- Keep answers concise; use bullet points + fenced code blocks when
  showing JSON or file contents.
```

---

## Task breakdown (17 tasks)

### Task 1: Backend package scaffold

**Files:** Create `custom/chatbot/__init__.py`

- [ ] 1.1 Create package marker + one-line docstring referencing this plan.
- [ ] 1.2 Commit checkpoint.

### Task 2: LLM client wrapper

**Files:** Create `custom/chatbot/llm_client.py`

- [ ] 2.1 Write `async def chat_completion(messages, tools=None, stream=False)` that:
  - Reads OpenHands settings for LLM model + API key + base_url.
  - Calls `litellm.acompletion` with the given messages and tools array.
  - Returns the completion response as-is for the caller to unpack.
- [ ] 2.2 Fallback: if settings not loadable, use env vars `OPENAI_API_KEY` / `LLM_MODEL`. Raise a clean `ChatbotError` if neither works.
- [ ] 2.3 Smoke test: `python -c "await chat_completion([{role:'user',content:'hi'}])"` returns a response.

### Task 3: Tool base + registry

**Files:** Create `custom/chatbot/tools/__init__.py` + `custom/chatbot/tools/base.py`

- [ ] 3.1 `class Tool`: `name`, `description`, `parameters` (JSON schema dict), `async def run(args: dict) -> Any`.
- [ ] 3.2 Module-level `TOOL_REGISTRY: dict[str, Tool] = {}` + `@register(tool)` decorator.
- [ ] 3.3 `def openai_tools_spec() -> list[dict]` — converts the registry into OpenAI function-calling format.
- [ ] 3.4 `async def run_tool(name: str, args: dict) -> dict` — dispatches to the registered tool, wraps exceptions into `{"error": "..."}`.

### Task 4: Agent + task + schedule tools

**Files:** Create `custom/chatbot/tools/agents.py`, `tasks.py`, `schedules.py`

- [ ] 4.1 `agents.py`: `list_agents(search, category, limit)` calls `AgentService.list_agents`, returns compact dicts. `get_agent(agent_id)` uses the same HTTP-loopback path as `fire.py` to pick up the skill frontmatter overlay.
- [ ] 4.2 `tasks.py`: `list_tasks(status, agent_id, limit)` + `get_task(task_id)` via `TaskService`.
- [ ] 4.3 `schedules.py`: `list_scheduled_tasks()` + `get_scheduled_task(schedule_id)` via `ScheduledTaskService` (includes last 5 fires).
- [ ] 4.4 Register all 6 tools in `tools/__init__.py` import side-effect.

### Task 5: Skill tools

**Files:** Create `custom/chatbot/tools/skills.py`

- [ ] 5.1 `list_skills(category)`: scan `custom/skill_examples/*/*.md`, parse frontmatter (reuse `frontmatter` package already in deps), return `[{name, description, category, path}]`.
- [ ] 5.2 `read_skill(name)`: find matching .md by frontmatter name, return full content. Hard cap at 50 KB per read so the bot can't blow up the context with a massive file.

### Task 6: Trigger tool

**Files:** Create `custom/chatbot/tools/launch.py`

- [ ] 6.1 `trigger_agent(agent_id, form_values)`: mirror `fire.py`'s create-task + create-v1-conversation + start-task path exactly. Returns `{task_id, conversation_id}`.
- [ ] 6.2 Add "requires user confirmation" note in the tool description so the LLM asks before calling. (Guardrail lives in the system prompt + tool description; no server-side confirmation gate in MVP.)

### Task 7: System prompt

**Files:** Create `custom/chatbot/system_prompt.py`

- [ ] 7.1 Export `SYSTEM_PROMPT: str` with the content in the "System prompt shape" section above.
- [ ] 7.2 Add a dynamic hook: `def get_system_prompt() -> str` that appends the current timestamp so the model knows what day it is.

### Task 8: Executor multi-turn loop

**Files:** Create `custom/chatbot/executor.py`

- [ ] 8.1 `async def run_chat(messages: list[dict]) -> list[dict]`:
  - Prepend system prompt to messages.
  - Call `llm_client.chat_completion(messages, tools=openai_tools_spec())`.
  - If response has `tool_calls`, run each via `run_tool`, append tool result messages, loop.
  - Max 8 turns to bound unbounded loops.
  - Returns the full updated messages list (caller serializes to response).
- [ ] 8.2 Error handling: tool exceptions → inject `{"role": "tool", "content": "{error: ...}"}` so the LLM can adapt.

### Task 9: REST router

**Files:** Create `custom/chatbot/router.py`; modify `openhands/server/app.py`

- [ ] 9.1 `POST /api/v1/chat/completions` — non-streaming. Takes `{messages: [...]}`, calls executor, returns `{messages: [...full history including tool calls and tool results...]}`.
- [ ] 9.2 `POST /api/v1/chat/stream` — SSE streaming **deferred to a later cut** (see Task 17).
- [ ] 9.3 Mount `_chatbot_router` in `app.py` with prefix `/api/v1`.

### Task 10: Frontend API service

**Files:** Create `frontend/src/api/custom-skill-service/chatbot-service.api.ts`

- [ ] 10.1 Types: `ChatMessage` (role + content + optional tool_calls + optional tool_call_id), `ChatRequest`, `ChatResponse`.
- [ ] 10.2 `ChatbotService.chat(messages)` — POST to `/api/v1/chat/completions`.

### Task 11: markdown-renderer

**Files:** Create `frontend/src/components/features/custom/chatbot/markdown-renderer.tsx`

- [ ] 11.1 Install `react-markdown` + `rehype-highlight` (if not already in deps; check first).
- [ ] 11.2 Component: `<MarkdownRenderer content={str}>` that renders fenced code blocks with highlighting and wraps paragraphs with chatbot-friendly styles.

### Task 12: message-bubble + tool-call-chip

**Files:** Create bubble + chip components

- [ ] 12.1 `message-bubble.tsx`: user role = right-aligned blue bubble, assistant = left-aligned gray bubble with `<MarkdownRenderer>`, tool role = collapsed gray chip showing tool name + args (click to expand to full result).
- [ ] 12.2 `tool-call-chip.tsx`: expandable chip for `tool_calls` on assistant messages that show "正在调用 {name}({args})".

### Task 13: use-chat hook

**Files:** Create `frontend/src/components/features/custom/chatbot/use-chat.ts`

- [ ] 13.1 State: `messages` (persisted to localStorage under `hiclaw_chat_history`), `loading`, `error`.
- [ ] 13.2 `sendMessage(text)`: append user message to state, call `ChatbotService.chat(messages + new user msg)`, replace state with returned full message list.
- [ ] 13.3 `clear()`: wipe localStorage + state.

### Task 14: chat-page

**Files:** Create `chat-page.tsx` + `message-list.tsx` + `chat-input.tsx`

- [ ] 14.1 `chat-page.tsx`: sticky header with title "HiClaw Chat" + "新对话" button, scrollable `<MessageList>`, sticky bottom `<ChatInput>`. Uses `useChat()`.
- [ ] 14.2 `message-list.tsx`: maps `messages` → `<MessageBubble>`, auto-scrolls to bottom on new message, shows a "生成中..." loading bubble when `loading`.
- [ ] 14.3 `chat-input.tsx`: multi-line textarea + send button, Enter sends / Shift+Enter newlines, disabled while `loading`.

### Task 15: Route + sidebar wiring

**Files:** Create `routes/chat.tsx`, modify `routes.ts` + sidebar

- [ ] 15.1 Route wrapper `routes/chat.tsx`.
- [ ] 15.2 `routes.ts`: `route("chat", "routes/chat.tsx")`.
- [ ] 15.3 Find the left sidebar component (likely `sidebar.tsx` — need to grep) and add a Chat entry next to "Agent 中心" / "任务中心". Icon: speech bubble SVG inline.

### Task 16: End-to-end verification

- [ ] 16.1 Restart backend. Open /chat. Send "你好，你能做什么？" — expect a Chinese intro that mentions the 8 tools.
- [ ] 16.2 Send "列一下所有 agent" — expect a `list_agents` tool call, followed by a bulleted list with 3 agents.
- [ ] 16.3 Send "渲染性能分析 Agent 有哪些 phase？" — expect a `get_agent` call, followed by the 4 phases (环境初始化 / Jank 分析 / Perfetto 截图 / 生成报告).
- [ ] 16.4 Send "帮我跑一次渲染分析" — bot should ask for confirmation + form_values, NOT directly trigger.
- [ ] 16.5 Send explicit trigger confirmation — `trigger_agent` call + returned task_id + clickable link to `/tasks/{task_id}`.
- [ ] 16.6 Send "`render-performance-workflow.md` 写了什么？" — `read_skill` call + markdown rendering of content.

### Task 17: [DEFERRED] SSE streaming + DB history

Left out of MVP to keep scope reasonable:

- SSE endpoint `/api/v1/chat/stream` streams tokens as they're generated. Needs `EventSourceResponse` + `litellm.acompletion(stream=True)` + frontend `EventSource` handling.
- `chat_session` + `chat_message` tables so history survives across browser sessions + devices. Today: localStorage only.

---

## Open design decisions

- **History**: localStorage only in MVP. Device-scoped, no cross-device sync, no backup. Easy to upgrade to DB later (just swap `useChat`'s persistence backend).
- **Model**: reuse OpenHands' `settings.llm_model` — whatever is configured for the host. User doesn't pick per-message.
- **Max turns**: 8 (prevents infinite tool-call loops if the LLM misbehaves).
- **Tool descriptions**: verbose Chinese descriptions in the JSON schema so the LLM knows which tool to pick.
- **Confirmation for writes**: system prompt + tool description only, no server gate. Acceptable because the only write tool is `trigger_agent` and triggering an agent is an easily-undoable action (user can cancel the task in the task center).
- **Rendering**: react-markdown for text, tool calls as collapsible chips, no streaming (full response lands at once in MVP).
