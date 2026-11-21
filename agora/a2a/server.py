"""A2A v1.0 server: JSON-RPC 2.0 binding over HTTP with SSE streaming.

Implements SendMessage, SendStreamingMessage, GetTask, ListTasks, CancelTask,
SubscribeToTask and GetExtendedAgentCard. Push-notification config methods
answer PushNotificationNotSupportedError (the card says pushNotifications=false).
Service parameters ``A2A-Version`` and ``A2A-Extensions`` are read from headers
(or the query string for the version), as section 9.2 requires.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .types import (
    A2A_VERSION,
    AGENT_CARD_PATH,
    A2AError,
    ExtendedAgentCardNotConfiguredError,
    ExtensionSupportRequiredError,
    InternalError,
    InvalidAgentResponseError,
    InvalidParamsError,
    InvalidRequestError,
    MethodNotFoundError,
    ParseError,
    PushNotificationNotSupportedError,
    Role,
    TaskNotCancelableError,
    TaskNotFoundError,
    TaskState,
    UnsupportedOperationError,
    VersionNotSupportedError,
    make_task,
    new_id,
    now_iso,
    validate_message,
)

log = logging.getLogger("agora.a2a")
SUPPORTED_VERSIONS = {A2A_VERSION}


@dataclass
class RequestContext:
    message: dict
    context_id: str
    task: dict | None
    extensions: set[str]
    headers: dict[str, str]
    configuration: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def is_continuation(self) -> bool:
        return self.task is not None


class AgentExecutor(Protocol):
    async def execute(self, ctx: RequestContext, handle: "TaskHandle") -> dict | None:
        """Either return a Message (no task) or drive ``handle`` through task states."""

    async def cancel(self, task: dict) -> None:  # pragma: no cover - optional
        ...


class TaskHandle:
    """Creates and updates one task, publishing A2A stream events."""

    def __init__(self, server: "A2AServer", context_id: str, task: dict | None, inbound: dict):
        self._server = server
        self.context_id = context_id
        self.task = task
        self._inbound = inbound
        self.created = asyncio.Event()
        if task is not None:
            self.created.set()

    async def _ensure(self) -> dict:
        if self.task is None:
            task = make_task(self.context_id, TaskState.SUBMITTED)
            task["history"].append({**self._inbound, "taskId": task["id"]})
            self._server.tasks[task["id"]] = task
            self.task = task
            self.created.set()
            await self._server._publish(task["id"], {"task": self._server.view(task)})
        return self.task

    async def update(self, state: str, message: dict | None = None) -> dict:
        task = await self._ensure()
        status: dict = {"state": state, "timestamp": now_iso()}
        if message is not None:
            message = {**message, "role": Role.AGENT, "taskId": task["id"], "contextId": task["contextId"]}
            status["message"] = message
            task["history"].append(message)
        task["status"] = status
        await self._server._publish(
            task["id"], {"statusUpdate": {"taskId": task["id"], "contextId": task["contextId"], "status": status}}
        )
        return task

    async def add_artifact(self, artifact: dict, append: bool = False, last_chunk: bool = True) -> None:
        task = await self._ensure()
        task["artifacts"].append(artifact)
        await self._server._publish(
            task["id"],
            {"artifactUpdate": {"taskId": task["id"], "contextId": task["contextId"], "artifact": artifact,
                                "append": append, "lastChunk": last_chunk}},
        )

    async def working(self, message: dict | None = None) -> dict:
        return await self.update(TaskState.WORKING, message)

    async def require_input(self, message: dict) -> dict:
        return await self.update(TaskState.INPUT_REQUIRED, message)

    async def complete(self, message: dict | None = None, artifacts: list[dict] | None = None) -> dict:
        for art in artifacts or []:
            await self.add_artifact(art)
        return await self.update(TaskState.COMPLETED, message)

    async def reject(self, message: dict | None = None) -> dict:
        return await self.update(TaskState.REJECTED, message)

    async def fail(self, message: dict | None = None) -> dict:
        return await self.update(TaskState.FAILED, message)


class A2AServer:
    def __init__(
        self,
        card_provider,
        executor: AgentExecutor,
        *,
        supported_extensions: set[str] | None = None,
        required_extensions: set[str] | None = None,
        rpc_path: str = "/a2a",
    ):
        self._card_provider = card_provider  # callable -> signed card dict
        self.executor = executor
        self.supported_extensions = set(supported_extensions or ())
        self.required_extensions = set(required_extensions or ())
        self.rpc_path = rpc_path
        self.tasks: dict[str, dict] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self.app = Starlette(
            routes=[
                Route(AGENT_CARD_PATH, self._agent_card, methods=["GET"]),
                Route(rpc_path, self._rpc, methods=["POST"]),
            ]
        )

    # ------------------------------------------------------------------ utils
    def view(self, task: dict, history_length: int | None = None) -> dict:
        out = json.loads(json.dumps(task))  # snapshot, detached from live state
        if history_length is not None:
            out["history"] = out["history"][-history_length:] if history_length > 0 else []
        return out

    async def _publish(self, task_id: str, event: dict) -> None:
        for q in list(self._subscribers.get(task_id, [])):
            await q.put(event)

    def _subscribe(self, task_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(task_id, []).append(q)
        return q

    def _unsubscribe(self, task_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(task_id, [])
        if q in subs:
            subs.remove(q)

    # ------------------------------------------------------------- endpoints
    async def _agent_card(self, request: Request) -> Response:
        return JSONResponse(self._card_provider(), headers={"Cache-Control": "max-age=60"})

    def _negotiate(self, request: Request) -> set[str]:
        version = request.headers.get("A2A-Version") or request.query_params.get("A2A-Version") or "0.3"
        major_minor = ".".join(version.strip().split(".")[:2])
        if major_minor not in SUPPORTED_VERSIONS:
            raise VersionNotSupportedError(f"A2A-Version {version} not supported; use {A2A_VERSION}")
        requested = {u.strip() for u in request.headers.get("A2A-Extensions", "").split(",") if u.strip()}
        missing = self.required_extensions - requested
        if missing:
            raise ExtensionSupportRequiredError(data={"required": sorted(missing)})
        return requested & self.supported_extensions

    async def _rpc(self, request: Request) -> Response:
        req_id: Any = None
        try:
            try:
                body = json.loads(await request.body())
            except json.JSONDecodeError as exc:
                raise ParseError(str(exc)) from exc
            if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
                raise InvalidRequestError()
            req_id = body.get("id")
            params = body.get("params") or {}
            if not isinstance(params, dict):
                raise InvalidParamsError("params must be an object")
            activated = self._negotiate(request)
            headers = {"A2A-Version": A2A_VERSION}
            if activated:
                headers["A2A-Extensions"] = ",".join(sorted(activated))
            method = body["method"]
            hdrs = {k.lower(): v for k, v in request.headers.items()}
            if method == "SendStreamingMessage":
                return EventSourceResponse(
                    self._sse(req_id, self._stream_message(params, activated, hdrs)), headers=headers
                )
            if method == "SubscribeToTask":
                return EventSourceResponse(self._sse(req_id, self._subscribe_task(params)), headers=headers)
            result = await self._dispatch(method, params, activated, hdrs)
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result}, headers=headers)
        except A2AError as exc:
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": exc.to_json()})
        except Exception as exc:  # noqa: BLE001
            log.exception("unhandled error in A2A handler")
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": InternalError(str(exc)).to_json()})

    async def _dispatch(self, method: str, params: dict, activated: set[str], headers: dict) -> Any:
        if method == "SendMessage":
            return await self._send_message(params, activated, headers)
        if method == "GetTask":
            task = self._get(params)
            return self.view(task, params.get("historyLength"))
        if method == "ListTasks":
            return self._list_tasks(params)
        if method == "CancelTask":
            return await self._cancel(params)
        if method in {
            "CreateTaskPushNotificationConfig", "GetTaskPushNotificationConfig",
            "ListTaskPushNotificationConfigs", "DeleteTaskPushNotificationConfig",
        }:
            raise PushNotificationNotSupportedError()
        if method == "GetExtendedAgentCard":
            raise ExtendedAgentCardNotConfiguredError()
        raise MethodNotFoundError(f"unknown method {method!r}")

    # ------------------------------------------------------------- handlers
    def _get(self, params: dict) -> dict:
        task = self.tasks.get(params.get("id", ""))
        if task is None:
            raise TaskNotFoundError(data={"id": params.get("id")})
        return task

    def _prepare(self, params: dict, activated: set[str], headers: dict) -> tuple[RequestContext, TaskHandle]:
        msg = params.get("message")
        validate_message(msg)
        if msg["role"] != Role.USER:
            raise InvalidParamsError("client messages must use ROLE_USER")
        task = None
        if msg.get("taskId"):
            task = self.tasks.get(msg["taskId"])
            if task is None:
                raise TaskNotFoundError(data={"id": msg["taskId"]})
            if task["status"]["state"] in TaskState.TERMINAL:
                raise UnsupportedOperationError("task is in a terminal state")
            if msg.get("contextId") and msg["contextId"] != task["contextId"]:
                raise InvalidParamsError("contextId does not match the task")
            context_id = task["contextId"]
        else:
            context_id = msg.get("contextId") or new_id()
        msg = {**msg, "contextId": context_id}
        if task is not None:
            task["history"].append(msg)
        ctx = RequestContext(
            message=msg, context_id=context_id, task=task, extensions=activated, headers=headers,
            configuration=params.get("configuration") or {}, metadata=params.get("metadata") or {},
        )
        return ctx, TaskHandle(self, context_id, task, msg)

    def _direct_reply(self, result: dict | None, ctx: RequestContext) -> dict:
        if not isinstance(result, dict) or "parts" not in result:
            raise InvalidAgentResponseError("executor returned neither a task nor a message")
        return {**result, "role": Role.AGENT, "contextId": ctx.context_id}

    async def _send_message(self, params: dict, activated: set[str], headers: dict) -> dict:
        ctx, handle = self._prepare(params, activated, headers)
        if ctx.configuration.get("returnImmediately"):
            runner = asyncio.create_task(self.executor.execute(ctx, handle))
            created = asyncio.create_task(handle.created.wait())
            await asyncio.wait({runner, created}, return_when=asyncio.FIRST_COMPLETED)
            created.cancel()
            if handle.task is not None:
                return {"task": self.view(handle.task, ctx.configuration.get("historyLength"))}
            return {"message": self._direct_reply(await runner, ctx)}
        result = await self.executor.execute(ctx, handle)
        if handle.task is None:
            return {"message": self._direct_reply(result, ctx)}
        return {"task": self.view(handle.task, ctx.configuration.get("historyLength"))}

    async def _stream_message(self, params: dict, activated: set[str], headers: dict) -> AsyncIterator[dict]:
        ctx, handle = self._prepare(params, activated, headers)
        queue: asyncio.Queue = asyncio.Queue()
        sub_key: list[str] = []
        if handle.task is not None:
            sub_key.append(handle.task["id"])
            self._subscribers.setdefault(handle.task["id"], []).append(queue)
            yield {"task": self.view(handle.task)}
        else:
            # subscribe as soon as the task id exists
            orig_ensure = handle._ensure

            async def ensure_and_subscribe() -> dict:
                fresh = handle.task is None
                if fresh:
                    task = make_task(handle.context_id, TaskState.SUBMITTED)
                    task["history"].append({**handle._inbound, "taskId": task["id"]})
                    self.tasks[task["id"]] = task
                    handle.task = task
                    sub_key.append(task["id"])
                    self._subscribers.setdefault(task["id"], []).append(queue)
                    handle.created.set()
                    await self._publish(task["id"], {"task": self.view(task)})
                return await orig_ensure()

            handle._ensure = ensure_and_subscribe  # type: ignore[method-assign]
        runner = asyncio.create_task(self.executor.execute(ctx, handle))
        try:
            while True:
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({getter, runner}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    event = getter.result()
                    yield event
                    state = (event.get("statusUpdate") or {}).get("status", {}).get("state") or (
                        event.get("task") or {}).get("status", {}).get("state")
                    if state in TaskState.TERMINAL or state in TaskState.INTERRUPTED:
                        break
                    continue
                getter.cancel()
                result = runner.result()
                while not queue.empty():
                    yield queue.get_nowait()
                if handle.task is None:
                    yield {"message": self._direct_reply(result, ctx)}
                break
        finally:
            for tid in sub_key:
                self._unsubscribe(tid, queue)

    async def _subscribe_task(self, params: dict) -> AsyncIterator[dict]:
        task = self._get(params)
        if task["status"]["state"] in TaskState.TERMINAL:
            raise UnsupportedOperationError("task is in a terminal state")
        queue = self._subscribe(task["id"])
        try:
            yield {"task": self.view(task)}
            while True:
                event = await queue.get()
                yield event
                state = (event.get("statusUpdate") or {}).get("status", {}).get("state")
                if state in TaskState.TERMINAL or state in TaskState.INTERRUPTED:
                    break
        finally:
            self._unsubscribe(task["id"], queue)

    async def _sse(self, req_id: Any, events: AsyncIterator[dict]) -> AsyncIterator[dict]:
        try:
            async for event in events:
                yield {"data": json.dumps({"jsonrpc": "2.0", "id": req_id, "result": event})}
        except A2AError as exc:
            yield {"data": json.dumps({"jsonrpc": "2.0", "id": req_id, "error": exc.to_json()})}

    def _list_tasks(self, params: dict) -> dict:
        tasks = list(self.tasks.values())
        if params.get("contextId"):
            tasks = [t for t in tasks if t["contextId"] == params["contextId"]]
        if params.get("status"):
            tasks = [t for t in tasks if t["status"]["state"] == params["status"]]
        tasks.sort(key=lambda t: t["status"].get("timestamp", ""), reverse=True)
        page_size = max(1, min(int(params.get("pageSize") or 50), 100))
        start = int(params.get("pageToken") or 0)
        page = tasks[start:start + page_size]
        nxt = str(start + page_size) if start + page_size < len(tasks) else ""
        hl = params.get("historyLength")
        return {"tasks": [self.view(t, hl) for t in page], "nextPageToken": nxt,
                "pageSize": page_size, "totalSize": len(tasks)}

    async def _cancel(self, params: dict) -> dict:
        task = self._get(params)
        if task["status"]["state"] in TaskState.TERMINAL:
            raise TaskNotCancelableError()
        cancel = getattr(self.executor, "cancel", None)
        if cancel is not None:
            await cancel(task)
        task["status"] = {"state": TaskState.CANCELED, "timestamp": now_iso()}
        await self._publish(task["id"], {"statusUpdate": {"taskId": task["id"], "contextId": task["contextId"],
                                                          "status": task["status"]}})
        return self.view(task)
