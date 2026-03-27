"""CoMagic LLM Hook — inject dynamic headers for CoMagic API.

Activated only when base_url contains 'cm.bata.hi.com' or 'comagic'.
Does nothing for other LLM providers.

Token is read from /tmp/token.txt on each request (supports rotation).
X-Request-ID is generated fresh per request.
"""

import os
import uuid
from pathlib import Path

TOKEN_FILE = os.getenv("COMAGIC_TOKEN_FILE", "/tmp/token.txt")
USER_ID_FILE = os.getenv("COMAGIC_USER_ID_FILE", "/tmp/xuerid.txt")
ENTERPRISE_ID = os.getenv("COMAGIC_ENTERPRISE_ID", "copilot")
MODEL_OPTION_ID = int(os.getenv("COMAGIC_MODEL_OPTION_ID", "204"))


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return ""


def inject_comagic_headers(config, kwargs: dict) -> dict:
    """Inject CoMagic-specific headers and body fields if using CoMagic API."""
    base_url = config.base_url or ""
    if "hihonor" not in base_url.lower():
        return kwargs

    # Dynamic token from file
    token = _read_file(TOKEN_FILE)
    if token:
        kwargs["api_key"] = token

    # Dynamic headers
    user_id = _read_file(USER_ID_FILE)
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
