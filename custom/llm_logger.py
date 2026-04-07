"""LLM Request/Response Logger — records raw HTTP details for all LLM calls.

Logs every LLM API call to:
  1. Console (summary)
  2. File (full detail) at ~/.openhands/llm_logs/

Enable by importing this module (auto-registered via comagic_hook or manually).

Similar to what Gemini CLI shows when you use --debug.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import litellm

LOG_DIR = os.path.join(
    os.environ.get("OH_PERSISTENCE_DIR", str(Path.home() / ".openhands")),
    "llm_logs",
)

# Create log directory
os.makedirs(LOG_DIR, exist_ok=True)

_enabled = os.environ.get("LLM_LOG_REQUESTS", "true").lower() in ("true", "1", "yes")
_call_count = 0


def _log_to_file(data: dict):
    """Write full request/response to a JSON file."""
    global _call_count
    _call_count += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{_call_count:04d}.json"
    filepath = os.path.join(LOG_DIR, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        print(f"[LLM_LOG] Failed to write log: {e}")


class LLMRequestLogger(litellm.integrations.custom_logger.CustomLogger):
    """litellm callback that logs raw request/response details."""

    def log_pre_api_call(self, model, messages, kwargs):
        if not _enabled:
            return
        # Extract what we can before the call
        headers = kwargs.get("additional_headers") or kwargs.get("headers") or {}
        extra_headers = kwargs.get("extra_headers", {})
        all_headers = {**headers, **extra_headers}

        data = {
            "type": "request",
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "base_url": kwargs.get("api_base") or kwargs.get("base_url", ""),
            "messages_count": len(messages) if isinstance(messages, list) else 1,
            "messages": messages,
            "headers": {k: v for k, v in all_headers.items() if k.lower() != "authorization"},
            "has_auth": "authorization" in {k.lower() for k in all_headers},
            "extra_body": kwargs.get("extra_body", {}),
            "stream": kwargs.get("stream", False),
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
        }

        print(f"\n[LLM_LOG] >>> REQUEST #{_call_count + 1}")
        print(f"  Model: {model}")
        print(f"  URL: {data['base_url']}/chat/completions")
        print(f"  Headers: {list(all_headers.keys())}")
        print(f"  Messages: {data['messages_count']} messages")
        if data["extra_body"]:
            print(f"  Extra body: {data['extra_body']}")

        _log_to_file(data)

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        if not _enabled:
            return
        duration = (end_time - start_time).total_seconds()

        # Extract response details
        response_data = {}
        try:
            if hasattr(response_obj, "model_dump"):
                response_data = response_obj.model_dump()
            elif hasattr(response_obj, "to_dict"):
                response_data = response_obj.to_dict()
            elif isinstance(response_obj, dict):
                response_data = response_obj
        except Exception:
            response_data = {"raw": str(response_obj)[:1000]}

        usage = response_data.get("usage", {})

        data = {
            "type": "response",
            "timestamp": datetime.now().isoformat(),
            "model": kwargs.get("model", "?"),
            "duration_seconds": round(duration, 2),
            "status": "success",
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "response": response_data,
        }

        print(f"[LLM_LOG] <<< RESPONSE (success)")
        print(f"  Duration: {duration:.2f}s")
        print(f"  Tokens: {usage.get('prompt_tokens', '?')} in / {usage.get('completion_tokens', '?')} out")

        _log_to_file(data)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        if not _enabled:
            return
        duration = (end_time - start_time).total_seconds()

        data = {
            "type": "response",
            "timestamp": datetime.now().isoformat(),
            "model": kwargs.get("model", "?"),
            "duration_seconds": round(duration, 2),
            "status": "error",
            "error": str(response_obj)[:2000],
        }

        print(f"[LLM_LOG] <<< RESPONSE (error)")
        print(f"  Duration: {duration:.2f}s")
        print(f"  Error: {str(response_obj)[:200]}")

        _log_to_file(data)


# Auto-register when imported
_logger_instance = LLMRequestLogger()
litellm.callbacks.append(_logger_instance)
print(f"[LLM_LOG] Logger enabled. Logs at: {LOG_DIR}")
print(f"[LLM_LOG] Set LLM_LOG_REQUESTS=false to disable")
