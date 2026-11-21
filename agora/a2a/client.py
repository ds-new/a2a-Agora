"""A2A v1.0 JSON-RPC client with Agent Card discovery and signature checks."""

from __future__ import annotations

import itertools
import json
from typing import Any, AsyncIterator

try:  # httpx, or its API-compatible successor httpx2
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    import httpx2 as httpx  # type: ignore

from .card import jsonrpc_url, verify_agent_card
from .types import A2A_VERSION, AGENT_CARD_PATH, A2AError, InvalidAgentResponseError

_ids = itertools.count(1)


class A2AClient:
    def __init__(self, http: "httpx.AsyncClient | None" = None, *, timeout: float = 30.0,
                 extensions: list[str] | tuple[str, ...] = ()):
        self.http = http or httpx.AsyncClient(timeout=timeout, trust_env=False)
        self.extensions = list(extensions)
        self.cards: dict[str, dict] = {}

    async def aclose(self) -> None:
        await self.http.aclose()

    def _headers(self, extensions: list[str] | None) -> dict[str, str]:
        headers = {"A2A-Version": A2A_VERSION, "Content-Type": "application/json"}
        exts = self.extensions if extensions is None else extensions
        if exts:
            headers["A2A-Extensions"] = ",".join(exts)
        return headers

    async def fetch_card(self, base_url: str, *, verify: bool = True, expected_did: str | None = None) -> dict:
        resp = await self.http.get(base_url.rstrip("/") + AGENT_CARD_PATH)
        resp.raise_for_status()
        card = resp.json()
        if verify:
            verify_agent_card(card, expected_did)
        self.cards[base_url] = card
        return card

    async def call(self, rpc_url: str, method: str, params: dict, *, extensions: list[str] | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
        resp = await self.http.post(rpc_url, content=json.dumps(payload), headers=self._headers(extensions))
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise A2AError.from_json(body["error"])
        if "result" not in body:
            raise InvalidAgentResponseError("JSON-RPC response without result")
        return body["result"]

    async def send_message(self, rpc_url: str, message: dict, *, configuration: dict | None = None,
                           metadata: dict | None = None, extensions: list[str] | None = None) -> dict:
        params: dict = {"message": message}
        if configuration:
            params["configuration"] = configuration
        if metadata:
            params["metadata"] = metadata
        result = await self.call(rpc_url, "SendMessage", params, extensions=extensions)
        if not isinstance(result, dict) or not ({"task", "message"} & result.keys()):
            raise InvalidAgentResponseError("SendMessageResponse must contain task or message")
        return result

    async def get_task(self, rpc_url: str, task_id: str, history_length: int | None = None) -> dict:
        params: dict = {"id": task_id}
        if history_length is not None:
            params["historyLength"] = history_length
        return await self.call(rpc_url, "GetTask", params)

    async def list_tasks(self, rpc_url: str, **filters: Any) -> dict:
        return await self.call(rpc_url, "ListTasks", filters)

    async def cancel_task(self, rpc_url: str, task_id: str) -> dict:
        return await self.call(rpc_url, "CancelTask", {"id": task_id})

    async def _sse(self, rpc_url: str, method: str, params: dict, extensions: list[str] | None) -> AsyncIterator[dict]:
        payload = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
        headers = {**self._headers(extensions), "Accept": "text/event-stream"}
        async with self.http.stream("POST", rpc_url, content=json.dumps(payload), headers=headers) as resp:
            resp.raise_for_status()
            if not resp.headers.get("content-type", "").startswith("text/event-stream"):
                body = json.loads(await resp.aread())
                raise A2AError.from_json(body.get("error", {"code": -32603, "message": "not a stream"}))
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                body = json.loads(line[5:].strip())
                if "error" in body:
                    raise A2AError.from_json(body["error"])
                yield body["result"]

    def stream_message(self, rpc_url: str, message: dict, *, extensions: list[str] | None = None) -> AsyncIterator[dict]:
        return self._sse(rpc_url, "SendStreamingMessage", {"message": message}, extensions)

    def subscribe_task(self, rpc_url: str, task_id: str) -> AsyncIterator[dict]:
        return self._sse(rpc_url, "SubscribeToTask", {"id": task_id}, None)

    @staticmethod
    def rpc_url_of(card: dict) -> str:
        return jsonrpc_url(card)
