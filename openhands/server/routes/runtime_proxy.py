"""
>>> CUSTOM: HiClaw — Runtime proxy for remote workers.

Proxies HTTP and WebSocket requests from the browser to the SSH tunnel
running on localhost. This allows the browser to connect via the app-server
port (3000) instead of needing direct access to the tunnel port.

Routes: /runtime/{port}/{path}  →  localhost:{port}/{path}
<<<
"""

import asyncio
import logging

import httpx
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/runtime')


# ─── Gitea proxy (Skills management UI) ──────
@router.api_route(
    '/gitea/{path:path}',
    methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'],
)
async def proxy_gitea(path: str, request: Request):
    """Proxy requests to the local Gitea instance for skills management.

    Gitea is configured with ROOT_URL=http://localhost:3000/runtime/gitea/
    so it generates all internal links with the /runtime/gitea/ prefix.
    We strip X-Frame-Options to allow iframe embedding.
    """
    from openhands.server.routes.hiclaw_config import GITEA_PORT
    target_url = f'http://localhost:{GITEA_PORT}/{path}'
    if request.url.query:
        target_url += f'?{request.url.query}'

    body = await request.body()
    headers = dict(request.headers)
    headers.pop('host', None)

    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        try:
            resp = await client.request(
                method=request.method, url=target_url, headers=headers, content=body,
            )
            resp_headers = dict(resp.headers)
            # Strip headers that cause iframe/content issues
            for h in ['x-frame-options', 'X-Frame-Options', 'content-security-policy',
                       'content-length', 'Content-Length',
                       'content-encoding', 'Content-Encoding',
                       'transfer-encoding', 'Transfer-Encoding']:
                resp_headers.pop(h, None)

            return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)
        except _httpx.ConnectError:
            return Response(content=b'Gitea not available', status_code=502)


# ─── Worker Manager proxy (SSE + API) ──────
# Allows frontend to reach Worker Manager (port 9090) through app-server (port 3000)

@router.api_route(
    '/manager/{path:path}',
    methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
)
async def proxy_manager(path: str, request: Request):
    """Proxy requests to the Worker Manager service."""
    from openhands.server.routes.hiclaw_config import WORKER_MANAGER_PORT
    target_url = f'http://localhost:{WORKER_MANAGER_PORT}/{path}'
    if request.url.query:
        target_url += f'?{request.url.query}'

    body = await request.body()
    headers = dict(request.headers)
    headers.pop('host', None)

    # For SSE endpoints, stream the response
    if 'events' in path:
        import httpx as _httpx
        async def stream_sse():
            async with _httpx.AsyncClient() as client:
                async with client.stream('GET', target_url, headers=headers, timeout=300) as resp:
                    async for line in resp.aiter_lines():
                        yield line + '\n'

        from starlette.responses import StreamingResponse
        return StreamingResponse(stream_sse(), media_type='text/event-stream')

    import httpx as _httpx
    async with _httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.request(
                method=request.method, url=target_url, headers=headers, content=body,
            )
            return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))
        except _httpx.ConnectError:
            return Response(content=b'Worker Manager not available', status_code=502)


@router.api_route(
    '/{port}/{path:path}',
    methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'],
)
async def proxy_http(port: int, path: str, request: Request):
    """Proxy HTTP requests to the local SSH tunnel port."""
    target_url = f'http://localhost:{port}/{path}'
    if request.url.query:
        target_url += f'?{request.url.query}'

    body = await request.body()
    headers = dict(request.headers)
    headers.pop('host', None)

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
        except httpx.ConnectError:
            return Response(content=b'Tunnel not available', status_code=502)


@router.websocket('/{port}/{path:path}')
async def proxy_websocket(websocket: WebSocket, port: int, path: str):
    """Proxy WebSocket connections to the local SSH tunnel port."""
    import websockets

    await websocket.accept()

    # Build the target WebSocket URL
    target_url = f'ws://localhost:{port}/{path}'
    query = str(websocket.url.query) if websocket.url.query else ''
    if query:
        target_url += f'?{query}'

    try:
        async with websockets.connect(target_url, open_timeout=10) as remote_ws:

            async def forward_to_remote():
                try:
                    while True:
                        msg = await websocket.receive()
                        if 'text' in msg and msg['text'] is not None:
                            await remote_ws.send(msg['text'])
                        elif 'bytes' in msg and msg['bytes'] is not None:
                            await remote_ws.send(msg['bytes'])
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            async def forward_to_client():
                try:
                    async for message in remote_ws:
                        if websocket.client_state != WebSocketState.CONNECTED:
                            break
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except Exception:
                    pass

            # Run both directions concurrently
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(forward_to_remote()),
                    asyncio.create_task(forward_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.warning(f'WebSocket proxy error: {e}')
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
