"""litellm wrapper that reads OpenHands' configured LLM settings.

The chatbot does not get its own LLM config — it piggybacks on whatever
model / key / base_url the rest of the platform already uses, so a
HiClaw operator only has to configure an LLM once. If settings aren't
loadable (e.g. blank install) we fall back to env vars so dev boxes
can still smoke-test the chat endpoint.
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncIterator

from litellm import acompletion as _litellm_acompletion

_logger = logging.getLogger(__name__)


class ChatbotError(RuntimeError):
    """Raised when the chatbot can't reach an LLM (no config, no key, ...)."""


async def _load_platform_llm_config() -> dict[str, Any] | None:
    """Pull model + api_key + base_url from OpenHands' SettingsStore.

    Returns None on any failure — caller will fall back to env vars.
    """
    try:
        from openhands.server.shared import SettingsStoreImpl, config

        # The chatbot is a single-tenant feature in HiClaw's internal
        # deployment, so 'default' is fine for user_id.
        store = await SettingsStoreImpl.get_instance(config, 'default')
        settings = await store.load()
        if settings is None or not settings.llm_model:
            return None
        api_key = None
        if settings.llm_api_key is not None:
            api_key = settings.llm_api_key.get_secret_value()
        return {
            'model': settings.llm_model,
            'api_key': api_key,
            'base_url': settings.llm_base_url,
        }
    except Exception as e:
        _logger.debug(f'Could not load platform LLM settings: {e}')
        return None


def _env_llm_config() -> dict[str, Any] | None:
    """Env var fallback: OPENAI_API_KEY + LLM_MODEL (or LITELLM_MODEL)."""
    model = os.environ.get('LLM_MODEL') or os.environ.get('LITELLM_MODEL')
    api_key = os.environ.get('OPENAI_API_KEY') or os.environ.get('LLM_API_KEY')
    base_url = os.environ.get('LLM_BASE_URL') or os.environ.get('OPENAI_BASE_URL')
    if not model:
        return None
    return {'model': model, 'api_key': api_key, 'base_url': base_url}


async def _resolve_config() -> dict[str, Any]:
    """Best-effort config resolution: platform settings → env vars."""
    cfg = await _load_platform_llm_config()
    if cfg is None:
        cfg = _env_llm_config()
    if cfg is None or not cfg.get('model'):
        raise ChatbotError(
            'Chatbot needs an LLM configured. Either set the platform LLM '
            'settings on /settings or export LLM_MODEL + OPENAI_API_KEY.'
        )
    return cfg


async def chat_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
    stream: bool = False,
) -> Any:
    """Thin wrapper around ``litellm.acompletion``.

    Args:
        messages: OpenAI-chat-style messages (role + content + optional
            tool_calls / tool_call_id).
        tools: OpenAI function-calling tool spec list. When present,
            litellm will emit ``tool_calls`` in the assistant response.
        stream: when True returns an async iterator of deltas, when
            False returns a single completion response object.

    Raises:
        ChatbotError: if no LLM is configured.
    """
    cfg = await _resolve_config()
    kwargs: dict[str, Any] = {
        'model': cfg['model'],
        'messages': messages,
        'stream': stream,
    }
    if cfg.get('api_key'):
        kwargs['api_key'] = cfg['api_key']
    if cfg.get('base_url'):
        kwargs['base_url'] = cfg['base_url']
    if tools:
        kwargs['tools'] = tools
        kwargs['tool_choice'] = 'auto'

    return await _litellm_acompletion(**kwargs)


async def stream_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> AsyncIterator[Any]:
    """Convenience wrapper: always returns an async iterator of deltas."""
    resp = await chat_completion(messages, tools=tools, stream=True)
    async for chunk in resp:
        yield chunk
