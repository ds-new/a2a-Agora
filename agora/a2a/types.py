"""A2A v1.0 data model as plain JSON dicts (ProtoJSON / camelCase)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

A2A_VERSION = "1.0"
JSONRPC_BINDING = "JSONRPC"
AGENT_CARD_PATH = "/.well-known/agent-card.json"

__all__ = [
    "A2A_VERSION", "JSONRPC_BINDING", "AGENT_CARD_PATH", "TaskState", "Role", "A2AError",
    "TaskNotFoundError", "TaskNotCancelableError", "PushNotificationNotSupportedError",
    "UnsupportedOperationError", "ContentTypeNotSupportedError", "InvalidAgentResponseError",
    "ExtendedAgentCardNotConfiguredError", "ExtensionSupportRequiredError", "VersionNotSupportedError",
    "InvalidParamsError", "MethodNotFoundError", "InvalidRequestError", "ParseError", "InternalError",
    "now_iso", "new_id", "text_part", "data_part", "make_message", "make_task", "make_artifact",
    "find_data", "message_text", "validate_message",
]


class TaskState:
    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"

    TERMINAL = frozenset({COMPLETED, FAILED, CANCELED, REJECTED})
    INTERRUPTED = frozenset({INPUT_REQUIRED, AUTH_REQUIRED})


class Role:
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


# --------------------------------------------------------------------------- #
# Errors: JSON-RPC codes from spec section "Error code mappings"
# --------------------------------------------------------------------------- #


class A2AError(Exception):
    code = -32603
    default_message = "Internal error"

    def __init__(self, message: str | None = None, data: Any = None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.data = data

    def to_json(self) -> dict:
        err = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err

    @staticmethod
    def from_json(err: dict) -> "A2AError":
        cls = _ERRORS_BY_CODE.get(err.get("code"), A2AError)
        exc = cls(err.get("message"), err.get("data"))
        exc.code = err.get("code", exc.code)
        return exc


class ParseError(A2AError):
    code, default_message = -32700, "Parse error"


class InvalidRequestError(A2AError):
    code, default_message = -32600, "Invalid Request"


class MethodNotFoundError(A2AError):
    code, default_message = -32601, "Method not found"


class InvalidParamsError(A2AError):
    code, default_message = -32602, "Invalid params"


class InternalError(A2AError):
    code, default_message = -32603, "Internal error"


class TaskNotFoundError(A2AError):
    code, default_message = -32001, "Task not found"


class TaskNotCancelableError(A2AError):
    code, default_message = -32002, "Task cannot be canceled"


class PushNotificationNotSupportedError(A2AError):
    code, default_message = -32003, "Push notifications are not supported"


class UnsupportedOperationError(A2AError):
    code, default_message = -32004, "This operation is not supported"


class ContentTypeNotSupportedError(A2AError):
    code, default_message = -32005, "Incompatible content types"


class InvalidAgentResponseError(A2AError):
    code, default_message = -32006, "Invalid agent response"


class ExtendedAgentCardNotConfiguredError(A2AError):
    code, default_message = -32007, "Extended agent card is not configured"


class ExtensionSupportRequiredError(A2AError):
    code, default_message = -32008, "A required extension was not declared by the client"


class VersionNotSupportedError(A2AError):
    code, default_message = -32009, "A2A protocol version not supported"


_ERRORS_BY_CODE = {
    c.code: c
    for c in (
        ParseError, InvalidRequestError, MethodNotFoundError, InvalidParamsError, InternalError,
        TaskNotFoundError, TaskNotCancelableError, PushNotificationNotSupportedError,
        UnsupportedOperationError, ContentTypeNotSupportedError, InvalidAgentResponseError,
        ExtendedAgentCardNotConfiguredError, ExtensionSupportRequiredError, VersionNotSupportedError,
    )
}

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def text_part(text: str, media_type: str | None = None) -> dict:
    part: dict = {"text": text}
    if media_type:
        part["mediaType"] = media_type
    return part


def data_part(data: Any, media_type: str = "application/json", metadata: dict | None = None) -> dict:
    part: dict = {"data": data, "mediaType": media_type}
    if metadata:
        part["metadata"] = metadata
    return part


def make_message(
    role: str,
    parts: list[dict],
    *,
    context_id: str | None = None,
    task_id: str | None = None,
    metadata: dict | None = None,
    extensions: list[str] | None = None,
    reference_task_ids: list[str] | None = None,
) -> dict:
    msg: dict = {"messageId": new_id(), "role": role, "parts": parts}
    if context_id:
        msg["contextId"] = context_id
    if task_id:
        msg["taskId"] = task_id
    if metadata:
        msg["metadata"] = metadata
    if extensions:
        msg["extensions"] = list(extensions)
    if reference_task_ids:
        msg["referenceTaskIds"] = list(reference_task_ids)
    return msg


def make_task(context_id: str, state: str = TaskState.SUBMITTED, message: dict | None = None) -> dict:
    status: dict = {"state": state, "timestamp": now_iso()}
    if message:
        status["message"] = message
    return {"id": new_id(), "contextId": context_id, "status": status, "artifacts": [], "history": []}


def make_artifact(
    parts: list[dict],
    name: str | None = None,
    description: str | None = None,
    metadata: dict | None = None,
    extensions: list[str] | None = None,
) -> dict:
    art: dict = {"artifactId": new_id(), "parts": parts}
    if name:
        art["name"] = name
    if description:
        art["description"] = description
    if metadata:
        art["metadata"] = metadata
    if extensions:
        art["extensions"] = list(extensions)
    return art


def find_data(obj: dict | None, type_: str | None = None) -> dict | None:
    """First ``data`` part of a Message/Artifact whose ``data.type`` matches."""
    if not obj:
        return None
    for part in obj.get("parts", []):
        data = part.get("data")
        if isinstance(data, dict) and (type_ is None or data.get("type") == type_):
            return data
    return None


def message_text(obj: dict | None) -> str:
    if not obj:
        return ""
    return "\n".join(p["text"] for p in obj.get("parts", []) if "text" in p)


_CONTENT_FIELDS = ("text", "raw", "url", "data")


def validate_message(msg: Any) -> None:
    if not isinstance(msg, dict):
        raise InvalidParamsError("message must be an object")
    for field in ("messageId", "role", "parts"):
        if not msg.get(field):
            raise InvalidParamsError(f"message.{field} is required")
    if msg["role"] not in (Role.USER, Role.AGENT):
        raise InvalidParamsError(f"invalid role {msg['role']!r}")
    for part in msg["parts"]:
        present = [f for f in _CONTENT_FIELDS if f in part]
        if len(present) != 1:
            raise InvalidParamsError("each Part must set exactly one of text/raw/url/data")
