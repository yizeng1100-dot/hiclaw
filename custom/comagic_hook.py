"""CoMagic LLM Hook — inject dynamic headers for CoMagic API.

Activated only when base_url contains 'cm.bata.hi.com' or 'comagic'.
Does nothing for other LLM providers.

Token is read from /tmp/token.txt on each request (supports rotation).
X-Request-ID is generated fresh per request.
"""

import json
import os
import uuid
from pathlib import Path

# Auto-enable LLM request logger
try:
    import custom.llm_logger  # noqa: F401
except Exception:
    pass

COMAGIC_CONFIG = os.getenv("COMAGIC_CONFIG", str(Path.home() / ".comagic" / "userToken.json"))
ENTERPRISE_ID = os.getenv("COMAGIC_ENTERPRISE_ID", "copilot")
MODEL_OPTION_ID = int(os.getenv("COMAGIC_MODEL_OPTION_ID", "204"))


def _read_comagic_config() -> dict:
    """Read token and xUserId from ~/.comagic/userToken.json"""
    try:
        return json.loads(Path(COMAGIC_CONFIG).read_text())
    except Exception:
        return {}


def inject_comagic_headers(config, kwargs: dict) -> dict:
    """Inject CoMagic-specific headers and body fields if using CoMagic API."""
    base_url = config.base_url or ""
    if "hihonor" not in base_url.lower():
        print(f"[COMAGIC_HOOK] SKIP - base_url '{base_url}' does not match")
        return kwargs

    # Read token and userId from ~/.comagic/userToken.json
    comagic = _read_comagic_config()
    token = comagic.get("token", "")
    user_id = comagic.get("xUserId", "")

    print(f"[COMAGIC_HOOK] TRIGGERED - base_url: {base_url}")
    print(f"[COMAGIC_HOOK] config file: {COMAGIC_CONFIG}")
    print(f"[COMAGIC_HOOK] token: {token[:20]}..." if token else "[COMAGIC_HOOK] token: EMPTY!")
    print(f"[COMAGIC_HOOK] xUserId: {user_id}")

    if token:
        kwargs["api_key"] = token
    else:
        print("[COMAGIC_HOOK] WARNING: no token found, request will likely fail with 401!")

    extra_headers = kwargs.get("extra_headers", {})
    extra_headers.update({
        "X-User-Id": user_id or "default",
        "X-Enterprise-Id": ENTERPRISE_ID,
        "X-Request-ID": str(uuid.uuid4()),
        "User-Agent": "CLI/0.0.0 CoMagic/0.1.66",
    })
    kwargs["extra_headers"] = extra_headers

    # Extra body fields (must go through extra_body to survive drop_params)
    extra_body = kwargs.get("extra_body", {})
    extra_body.setdefault("model_option_id", MODEL_OPTION_ID)
    extra_body.setdefault("thinking", "disabled")
    kwargs["extra_body"] = extra_body

    return kwargs
