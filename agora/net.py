"""Transports: real HTTP via uvicorn, or an in-memory ASGI network for fast tests.

Both carry the same A2A JSON-RPC bytes; only the socket layer differs.
"""

from __future__ import annotations

import asyncio
import socket

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    import httpx2 as httpx  # type: ignore

import uvicorn


class MemoryNetwork(httpx.AsyncBaseTransport):
    """Routes requests to ASGI apps by host:port without opening sockets."""

    def __init__(self) -> None:
        self._apps: dict[str, httpx.ASGITransport] = {}

    def register(self, base_url: str, app) -> None:
        url = httpx.URL(base_url)
        self._apps[f"{url.host}:{url.port}"] = httpx.ASGITransport(app=app)

    async def handle_async_request(self, request):  # type: ignore[override]
        key = f"{request.url.host}:{request.url.port}"
        transport = self._apps.get(key)
        if transport is None:
            raise httpx.ConnectError(f"no agent listening at {key}", request=request)
        return await transport.handle_async_request(request)

    def client(self, timeout: float = 30.0):
        return httpx.AsyncClient(transport=self, timeout=timeout, trust_env=False)


_RESERVED: dict[int, socket.socket] = {}


def free_port() -> int:
    """Pick a free local port and keep it bound until ``HttpServerGroup.start`` serves on it.

    Closing the probe socket and binding again later would leave a window in which
    another process can take the port (seen as "address already in use" on busy hosts)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    _RESERVED[port] = s
    return port


class HttpServerGroup:
    """Runs many uvicorn servers (one per agent) inside one asyncio loop."""

    def __init__(self) -> None:
        self._servers: list[tuple[uvicorn.Server, asyncio.Task]] = []

    async def start(self, app, port: int) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off",
                                access_log=False)
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        sock = _RESERVED.pop(port, None)  # reserved by free_port: serve on it, no rebinding race
        task = asyncio.create_task(server.serve(sockets=[sock] if sock is not None else None))
        self._servers.append((server, task))
        for _ in range(400):
            if server.started:
                return
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
        raise RuntimeError(f"agent server on port {port} did not start")

    async def stop(self) -> None:
        for server, _ in self._servers:
            server.should_exit = True
        await asyncio.gather(*(t for _, t in self._servers), return_exceptions=True)
        self._servers.clear()
