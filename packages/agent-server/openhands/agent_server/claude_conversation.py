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

        # Create minimal ConversationState
        self._state = ConversationState.create(
            conversation_id=conversation_id,
            workspace=workspace,
            persistence_dir=Path(persistence_dir) / conversation_id.hex,
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
        """Emit event through all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                _logger.warning(f'Callback error: {e}')

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
        from claude_agent_sdk import (
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
        )

        # Build system prompt with skills
        full_prompt = self._system_prompt
        if self._skills_content:
            full_prompt += '\n\n' + self._skills_content

        options = ClaudeAgentOptions(
            system_prompt=full_prompt,
            cwd=self._workspace.working_dir,
            permission_mode='bypassPermissions',
            max_turns=self._max_iterations,
        )

        # Set API key
        import os
        os.environ['ANTHROPIC_API_KEY'] = self._api_key

        client = ClaudeSDKClient(options=options)
        self._client = client

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
                events = claude_message_to_events(message)
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
            _logger.error(f'Claude SDK error: {e}', exc_info=True)
            raise
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            self._client = None

        # If we didn't get a ResultMessage, mark as finished
        if self._state.execution_status == ConversationExecutionStatus.RUNNING:
            self._state.execution_status = ConversationExecutionStatus.FINISHED
