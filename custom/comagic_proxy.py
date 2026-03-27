"""CoMagic LLM Proxy — translates standard OpenAI API to CoMagic format.

Runs as a lightweight HTTP server. OpenHands connects to this proxy
as if it were a standard OpenAI-compatible endpoint.

Usage:
  python3 custom/comagic_proxy.py

OpenHands config:
  model: openai/GLM-4.7
  base_url: http://localhost:9099/v1
  api_key: (any non-empty value)

The proxy handles:
  1. Adding custom headers (X-User-Id, X-Enterprise-Id, X-Request-ID, User-Agent)
  2. Reading auth token from /tmp/token.txt (or env var)
  3. Adding extra body fields (model_option_id, thinking)
  4. Forwarding to CoMagic API
"""

import json
import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

app = FastAPI(title="CoMagic Proxy")

# ─── Configuration ────────────────────────────────────────
COMAGIC_URL = os.getenv("COMAGIC_URL", "https://cm.bata.hi.com/v2/chat/completions")
TOKEN_FILE = os.getenv("COMAGIC_TOKEN_FILE", "/tmp/token.txt")
USER_ID_FILE = os.getenv("COMAGIC_USER_ID_FILE", "/tmp/xuerid.txt")
ENTERPRISE_ID = os.getenv("COMAGIC_ENTERPRISE_ID", "copilot")
MODEL_OPTION_ID = int(os.getenv("COMAGIC_MODEL_OPTION_ID", "204"))
PROXY_PORT = int(os.getenv("COMAGIC_PROXY_PORT", "9099"))


def _read_file(path: str, default: str = "") -> str:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return default


def _get_token() -> str:
    return os.getenv("COMAGIC_TOKEN") or _read_file(TOKEN_FILE, "no-token")


def _get_user_id() -> str:
    return os.getenv("COMAGIC_USER_ID") or _read_file(USER_ID_FILE, "default-user")


# ─── Proxy Endpoint ──────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Proxy OpenAI-format request to CoMagic API."""
    body = await request.json()

    # Add CoMagic-specific fields
    body.setdefault("model_option_id", MODEL_OPTION_ID)
    body.setdefault("thinking", "disabled")

    # Build CoMagic headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_token()}",
        "X-User-Id": _get_user_id(),
        "X-Enterprise-Id": ENTERPRISE_ID,
        "X-Request-ID": str(uuid.uuid4()),
        "User-Agent": "CLI/0.0.0 CoMagic/0.1.66",
    }

    is_stream = body.get("stream", False)

    async with httpx.AsyncClient(timeout=300) as client:
        if is_stream:
            # Streaming mode: forward SSE chunks
            async def stream_generator():
                async with client.stream("POST", COMAGIC_URL, json=body, headers=headers) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        else:
            # Non-streaming mode
            resp = await client.post(COMAGIC_URL, json=body, headers=headers)
            return JSONResponse(
                content=resp.json(),
                status_code=resp.status_code,
            )


@app.get("/v1/models")
async def list_models():
    """Return available models (required by some clients)."""
    return {
        "object": "list",
        "data": [
            {"id": "GLM-4.7", "object": "model", "owned_by": "comagic"},
            {"id": "GLM-5", "object": "model", "owned_by": "comagic"},
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    print(f"CoMagic Proxy starting on port {PROXY_PORT}")
    print(f"  CoMagic URL: {COMAGIC_URL}")
    print(f"  Token file: {TOKEN_FILE}")
    print(f"  Enterprise: {ENTERPRISE_ID}")
    print(f"  Model option: {MODEL_OPTION_ID}")
    print(f"\nOpenHands 配置:")
    print(f"  model: openai/GLM-4.7")
    print(f"  base_url: http://localhost:{PROXY_PORT}/v1")
    print(f"  api_key: any-non-empty-value")
    uvicorn.run(app, host="0.0.0.0", port=PROXY_PORT)
