"""Claude Agent SDK conversation implementation.

Wraps ClaudeSDKClient to provide the same interface as LocalConversation,
so EventService can use it as a drop-in replacement when agent_engine=claude_sdk.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from openhands.agent_server.claude_event_bridge import claude_message_to_events
from openhands.sdk import Message, TextContent, get_logger
from openhands.sdk.conversation.state import (
    ConversationExecutionStatus,
    ConversationState,
)
from openhands.sdk.event.base import Event
from openhands.sdk.event.llm_convertible.message import MessageEvent
from openhands.sdk.workspace import LocalWorkspace

_logger = get_logger(__name__)


class ClaudeConversation:
    """Conversation implementation using Claude Agent SDK.

    This class provides the same interface used by EventService:
    - _state: ConversationState (for status tracking)
    - run(): blocking agent loop
    - send_message(): queue user message
    - pause(): interrupt agent
    - set_confirmation_policy(): (no-op for Claude)
    - state property
    - agent property (returns None — no OpenHands Agent)
    """

    def __init__(
        self,
        *,
        api_key: str,
        workspace: LocalWorkspace,
        system_prompt: str | None = None,
        persistence_dir: str,
        conversation_id: UUID,
        callbacks: list[Any],
        max_iterations: int = 500,
        skills_content: str = '',
        # >>> CUSTOM: HiClaw <<<
        llm_base_url: str = '',
        llm_model: str = '',
        # >>> END CUSTOM <<<
    ):
        self._api_key = api_key
        self._workspace = workspace
        self._system_prompt = system_prompt or ''
        self._skills_content = skills_content
        self._persistence_dir = persistence_dir
        self._conversation_id = conversation_id
        self._callbacks = callbacks
        self._max_iterations = max_iterations
        self._pending_messages: list[str] = []
        self._client: Any = None  # ClaudeSDKClient instance
        self._loop: asyncio.AbstractEventLoop | None = None
        # >>> CUSTOM: HiClaw <<<
        self._llm_base_url = llm_base_url
        self._llm_model = llm_model
        # Long-lived stats dict shared across all _async_run() invocations
        # in this conversation. Carries cumulative token/cost, the
        # tool_use_id → tool_name map, and one-shot flags like init_emitted
        # (so the "Claude session ready" header only prints once per
        # conversation, not once per user turn).
        self._stats: dict[str, Any] = {}
        if self._llm_model:
            self._stats['model'] = self._llm_model
        # >>> END CUSTOM <<<

        # Create minimal ConversationState
        # ConversationState.create() requires 'id' and 'agent' params.
        # For Claude mode we create a dummy agent since Claude CLI handles everything.
        from openhands.sdk import Agent, LLM
        dummy_agent = Agent(llm=LLM(model='claude-sonnet-4-20250514', api_key=api_key))
        self._state = ConversationState.create(
            id=conversation_id,
            agent=dummy_agent,
            workspace=workspace,
            persistence_dir=str(Path(persistence_dir) / conversation_id.hex),
            max_iterations=max_iterations,
        )

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def agent(self) -> None:
        """Claude mode has no OpenHands Agent."""
        return None

    def set_confirmation_policy(self, policy: Any) -> None:
        """No-op: Claude manages its own permission system."""
        pass

    def _on_event(self, event: Event) -> None:
        """Emit event through all registered callbacks AND persist to event log.

        LocalConversation has a built-in _default_callback that appends every
        event to self._state.events (i.e. the event log). Without this, events
        flow to the WebSocket but never get persisted, so replay after refresh
        doesn't show them and the frontend may drop them when reconciling.
        """
        # >>> CUSTOM: HiClaw — persist to event log, just like LocalConversation <<<
        try:
            # Set source if missing (Pydantic model_construct doesn't set defaults)
            if not getattr(event, 'source', None):
                try:
                    event.source = 'agent'
                except Exception:
                    pass
            self._state.events.append(event)
        except Exception as e:
            _logger.warning(f'Failed to append event to state: {e}', exc_info=True)
        # >>> END CUSTOM <<<

        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                _logger.warning(f'Callback error: {e}', exc_info=True)

    def send_message(self, message: Message) -> None:
        """Queue a user message to be sent to Claude."""
        # Extract text from message
        text_parts = []
        for content in message.content:
            if isinstance(content, TextContent):
                text_parts.append(content.text)
            elif hasattr(content, 'text'):
                text_parts.append(content.text)
        text = '\n'.join(text_parts)
        self._pending_messages.append(text)

        # >>> CUSTOM: HiClaw — emit user MessageEvent so frontend displays the sent message <<<
        try:
            user_event = MessageEvent.model_construct(
                source='user',
                llm_message=Message(
                    role='user',
                    content=[TextContent(type='text', text=text)],
                ),
                llm_response_id=None,
            )
            self._on_event(user_event)
        except Exception as e:
            _logger.warning(f'Failed to emit user message event: {e}', exc_info=True)
        # >>> END CUSTOM <<<

    def pause(self) -> None:
        """Pause the Claude agent."""
        self._state.execution_status = ConversationExecutionStatus.PAUSED
        # Interrupt will be handled in the async run loop

    def run(self) -> None:
        """Run the Claude agent loop (blocking, called from executor).

        This is called by EventService in a background thread via run_in_executor.
        We create a new event loop for the async Claude SDK operations.
        """
        try:
            self._state.execution_status = ConversationExecutionStatus.RUNNING
            asyncio.run(self._async_run())
        except Exception as e:
            _logger.error(f'Claude conversation run failed: {e}', exc_info=True)
            self._state.execution_status = ConversationExecutionStatus.ERROR
            # Emit error as event
            from openhands.sdk.event import AgentErrorEvent
            error_event = AgentErrorEvent(
                tool_name='claude_agent',
                tool_call_id='',
                error=str(e),
            )
            self._on_event(error_event)

    async def _async_run(self) -> None:
        """Async implementation of the Claude agent loop."""
        import os
        import tempfile

        from claude_agent_sdk import (
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
        )

        # Build system prompt with skills
        full_prompt = self._system_prompt

        # >>> CUSTOM: HiClaw — discover skills from workspace/.hiclaw/skills/ <<<
        # OpenHands mode loads skills via skill_loader; Claude CLI has no way
        # to discover these on its own, so we scan the workspace for SKILL.md
        # files and inject them into the system prompt here.
        discovered_skills = []
        workspace_dir = getattr(self._workspace, 'working_dir', '') or ''
        if workspace_dir:
            hiclaw_skill_root = Path(workspace_dir) / '.hiclaw' / 'skills'
            if hiclaw_skill_root.is_dir():
                for skill_md in sorted(hiclaw_skill_root.glob('*/SKILL.md')):
                    try:
                        content = skill_md.read_text(encoding='utf-8')
                        skill_name = skill_md.parent.name
                        # Skip internal/template dirs
                        if skill_name.startswith('_'):
                            continue
                        discovered_skills.append((skill_name, content, skill_md.parent))
                    except Exception as e:
                        _logger.warning(f'Failed to read {skill_md}: {e}')

        _logger.info(
            f'Claude mode: discovered {len(discovered_skills)} HiClaw skills '
            f'in {workspace_dir}/.hiclaw/skills/'
        )

        # Register HiClaw skills as a local Claude CLI plugin.
        # Claude CLI plugin format: <plugin_root>/.claude-plugin/plugin.json +
        # <plugin_root>/skills/<skill>/SKILL.md. Loaded via `--plugin-dir <path>`
        # (passed through ClaudeAgentOptions.plugins).
        hiclaw_plugin_path: str | None = None
        try:
            import json as _plugin_json
            import shutil as _shutil
            persist_dir = self._state.persistence_dir or tempfile.gettempdir()
            os.makedirs(persist_dir, exist_ok=True)
            plugin_root = Path(persist_dir) / 'hiclaw-plugin'
            if plugin_root.exists():
                _shutil.rmtree(plugin_root, ignore_errors=True)
            (plugin_root / '.claude-plugin').mkdir(parents=True, exist_ok=True)
            (plugin_root / 'skills').mkdir(parents=True, exist_ok=True)
            (plugin_root / '.claude-plugin' / 'plugin.json').write_text(
                _plugin_json.dumps({
                    'name': 'hiclaw',
                    'version': '1.0.0',
                    'description': 'HiClaw workspace custom skills',
                }, indent=2)
            )
            for skill_name, skill_content, _src_dir in discovered_skills:
                skill_dst = plugin_root / 'skills' / skill_name
                skill_dst.mkdir(parents=True, exist_ok=True)
                (skill_dst / 'SKILL.md').write_text(skill_content, encoding='utf-8')
                for sibling in _src_dir.iterdir():
                    if sibling.name == 'SKILL.md' or sibling.name.startswith('.'):
                        continue
                    try:
                        dst_path = skill_dst / sibling.name
                        if sibling.is_dir():
                            if dst_path.exists():
                                _shutil.rmtree(dst_path, ignore_errors=True)
                            _shutil.copytree(sibling, dst_path)
                        else:
                            _shutil.copy2(sibling, dst_path)
                    except Exception as e:
                        _logger.warning(f'Failed to copy {sibling}: {e}')
            if discovered_skills:
                hiclaw_plugin_path = str(plugin_root)
                _logger.info(
                    f'Registered {len(discovered_skills)} HiClaw skills as '
                    f'Claude plugin at {plugin_root}'
                )
        except Exception as e:
            _logger.warning(f'Failed to build HiClaw plugin: {e}', exc_info=True)

        if discovered_skills:
            skill_names_list = '\n'.join(
                f'- **{name}**' for name, _, _src in discovered_skills
            )
            skill_full_sections = ''.join(
                f'\n\n---\n### HiClaw Skill: {name}\n{content}'
                for name, content, _src in discovered_skills
            )
            hiclaw_block = (
                '\n\n<hiclaw_skills>\n'
                f'The user has {len(discovered_skills)} custom HiClaw skills '
                f'available in this workspace. When asked "what skills are '
                f'available" or "有哪些 skill", list EXACTLY these names:\n\n'
                f'{skill_names_list}\n\n'
                f'When the user invokes a skill (by name, trigger, or slash '
                f'command), follow the instructions in its content below.\n'
                f'</hiclaw_skills>'
                f'{skill_full_sections}'
            )
            full_prompt += hiclaw_block

        if self._skills_content:
            full_prompt += '\n\n' + self._skills_content
        # >>> END CUSTOM <<<

        # >>> CUSTOM: HiClaw <<<
        # If the system prompt is large (skills can be huge), pass it via a
        # file to avoid the Linux ARG_MAX limit (~128KB) on command line.
        # Threshold: 32KB — well under ARG_MAX but big enough to avoid churn
        # for small prompts. Use a prompt file whenever skills are loaded.
        system_prompt_arg: Any = full_prompt
        prompt_file_path: str | None = None
        if len(full_prompt.encode('utf-8')) > 32 * 1024:
            # Write to a temp file inside the conversation persistence dir
            # so it gets cleaned up with the conversation
            persist_dir = self._state.persistence_dir or tempfile.gettempdir()
            os.makedirs(persist_dir, exist_ok=True)
            fd, prompt_file_path = tempfile.mkstemp(
                suffix='.txt',
                prefix='claude_system_prompt_',
                dir=persist_dir,
            )
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(full_prompt)
            system_prompt_arg = {'type': 'file', 'path': prompt_file_path}
        # >>> END CUSTOM <<<

        # >>> CUSTOM: HiClaw — capture Claude CLI stderr so we can see real errors <<<
        # SDK only pipes stderr when a callback is set or debug mode is on;
        # otherwise "Check stderr output for details" is all we see.
        _claude_stderr_lines: list[str] = []

        def _on_claude_stderr(line: str) -> None:
            _claude_stderr_lines.append(line)
            _logger.error(f'[claude-cli stderr] {line.rstrip()}')

        _plugins_arg: list[dict[str, str]] = []
        if hiclaw_plugin_path:
            _plugins_arg.append({'type': 'local', 'path': hiclaw_plugin_path})

        options = ClaudeAgentOptions(
            system_prompt=system_prompt_arg,
            cwd=self._workspace.working_dir,
            permission_mode='bypassPermissions',
            max_turns=self._max_iterations,
            stderr=_on_claude_stderr,
            plugins=_plugins_arg,  # type: ignore[arg-type]
        )
        # >>> END CUSTOM <<<

        # >>> CUSTOM: HiClaw — validate API key <<<
        if not self._api_key:
            raise RuntimeError(
                'Claude mode requires an API key, but none was provided. '
                'Please configure an LLM in settings.'
            )
        # >>> END CUSTOM <<<

        # >>> CUSTOM: HiClaw — auto-write Claude CLI config files <<<
        # Write ~/.claude/settings.json with env vars pointing at the LLM gateway
        # (qianfan / LiteLLM proxy / Anthropic) so Claude CLI picks them up.
        # Also write ~/.claude.json with hasCompletedOnboarding to skip the wizard.
        import json as _json
        _home = Path.home()
        _claude_dir = _home / '.claude'
        _claude_dir.mkdir(parents=True, exist_ok=True)

        # Rewrite known gateway base_urls to their Anthropic-compatible variant.
        # The same provider can expose OpenAI-compatible and Anthropic-compatible
        # endpoints on different paths (e.g. qianfan: /v2/coding vs /anthropic/coding).
        # The UI stores the OpenAI variant, so we map it to the Anthropic one here.
        _effective_base_url = self._llm_base_url
        if _effective_base_url and 'qianfan.baidubce.com' in _effective_base_url:
            # qianfan: /v2/coding → /anthropic/coding
            _effective_base_url = 'https://qianfan.baidubce.com/anthropic/coding'
            _logger.info(
                f'Claude mode: rewrote qianfan base_url '
                f'{self._llm_base_url!r} → {_effective_base_url!r}'
            )

        _settings_json = {
            'env': {
                'ANTHROPIC_AUTH_TOKEN': self._api_key,
                'ANTHROPIC_API_KEY': self._api_key,
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                'API_TIMEOUT_MS': '600000',
            },
            'permissions': {'allow': [], 'deny': []},
        }
        if _effective_base_url:
            _settings_json['env']['ANTHROPIC_BASE_URL'] = _effective_base_url
        if self._llm_model:
            _settings_json['env'].update({
                'ANTHROPIC_MODEL': self._llm_model,
                'ANTHROPIC_SMALL_FAST_MODEL': self._llm_model,
                'ANTHROPIC_DEFAULT_HAIKU_MODEL': self._llm_model,
                'ANTHROPIC_DEFAULT_SONNET_MODEL': self._llm_model,
                'ANTHROPIC_DEFAULT_OPUS_MODEL': self._llm_model,
            })

        _settings_path = _claude_dir / 'settings.json'
        _settings_path.write_text(_json.dumps(_settings_json, indent=2))
        _logger.info(
            f'Wrote Claude settings: {_settings_path} '
            f'(base_url={_effective_base_url or "default"}, model={self._llm_model or "default"})'
        )

        # Skip onboarding wizard
        _onboarding_path = _home / '.claude.json'
        if not _onboarding_path.exists():
            _onboarding_path.write_text('{"hasCompletedOnboarding": true}')
            _logger.info(f'Wrote onboarding skip flag: {_onboarding_path}')

        # Propagate env vars to current process so the subprocess inherits them
        os.environ['ANTHROPIC_API_KEY'] = self._api_key
        os.environ['ANTHROPIC_AUTH_TOKEN'] = self._api_key
        if _effective_base_url:
            os.environ['ANTHROPIC_BASE_URL'] = _effective_base_url
        if self._llm_model:
            for _k in ('ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL',
                       'ANTHROPIC_DEFAULT_HAIKU_MODEL',
                       'ANTHROPIC_DEFAULT_SONNET_MODEL',
                       'ANTHROPIC_DEFAULT_OPUS_MODEL'):
                os.environ[_k] = self._llm_model
        os.environ.setdefault('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', '1')
        os.environ.setdefault('API_TIMEOUT_MS', '600000')
        # >>> END CUSTOM <<<

        # >>> CUSTOM: HiClaw — ensure cwd exists before starting Claude CLI <<<
        try:
            os.makedirs(self._workspace.working_dir, exist_ok=True)
        except OSError as e:
            _logger.warning(f'Failed to create working dir {self._workspace.working_dir}: {e}')
        # >>> END CUSTOM <<<

        # >>> CUSTOM: HiClaw — allow bypassPermissions when running as root <<<
        # Claude CLI refuses --dangerously-skip-permissions as root unless
        # IS_SANDBOX=1 or CLAUDE_CODE_BUBBLEWRAP is set. Remote agent-server
        # machines ARE ephemeral sandboxes, so set IS_SANDBOX=1.
        os.environ.setdefault('IS_SANDBOX', '1')
        # >>> END CUSTOM <<<

        client = ClaudeSDKClient(options=options)
        self._client = client

        # >>> CUSTOM: HiClaw — use the conversation-wide stats dict (built in
        # __init__) so cumulative token/cost AND one-shot flags like
        # init_emitted survive across user turns. <<<
        _stats = self._stats
        # >>> END CUSTOM <<<

        try:
            # Get the initial message (if any)
            initial_prompt = None
            if self._pending_messages:
                initial_prompt = self._pending_messages.pop(0)

            if initial_prompt:
                await client.connect(prompt=initial_prompt)
            else:
                await client.connect()

            # Process streaming responses
            async for message in client.receive_messages():
                # Check if paused
                if self._state.execution_status == ConversationExecutionStatus.PAUSED:
                    await client.interrupt()
                    break

                # Convert Claude message to OpenHands events
                events = claude_message_to_events(message, stats=_stats)
                for event in events:
                    self._on_event(event)

                # Check for completion
                if isinstance(message, ResultMessage):
                    self._state.execution_status = ConversationExecutionStatus.FINISHED
                    break

                # Process any queued follow-up messages
                while self._pending_messages:
                    msg = self._pending_messages.pop(0)
                    await client.query(msg)

        except Exception as e:
            # >>> CUSTOM: HiClaw — include captured stderr in the error <<<
            stderr_tail = '\n'.join(_claude_stderr_lines[-20:]) if _claude_stderr_lines else '(empty)'
            _logger.error(
                f'Claude SDK error: {e}\n--- claude-cli stderr (last 20 lines) ---\n{stderr_tail}',
                exc_info=True,
            )
            # >>> END CUSTOM <<<
            raise
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            self._client = None
            # >>> CUSTOM: HiClaw — cleanup temp system prompt file <<<
            if prompt_file_path:
                try:
                    os.unlink(prompt_file_path)
                except OSError:
                    pass
            # >>> END CUSTOM <<<

        # If we didn't get a ResultMessage, mark as finished
        if self._state.execution_status == ConversationExecutionStatus.RUNNING:
            self._state.execution_status = ConversationExecutionStatus.FINISHED
