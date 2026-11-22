"""Authenticated, project-scoped WebSocket connections for task activity."""

import asyncio
import json
import secrets
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from prometheus_client import Gauge
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.auth.workspace_context import resolve_workspace_id
from app.core.exceptions import AppError, NotAuthenticatedError
from app.db.session import get_db
from app.repositories.membership_repository import MembershipRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository

MAX_MESSAGE_BYTES = 4096
MESSAGE_RATE_LIMIT = 30
MESSAGE_RATE_WINDOW_SECONDS = 10.0
AUTHENTICATION_TIMEOUT_SECONDS = 5.0
HEARTBEAT_INTERVAL_SECONDS = 20.0
HEARTBEAT_TIMEOUT_SECONDS = 10.0

connection_gauge = Gauge(
    "taskflow_websocket_connections",
    "Number of currently open TaskFlow WebSocket connections.",
)

router = APIRouter(tags=["task-activity"])


@dataclass
class WebSocketConnection:
    websocket: WebSocket
    db: AsyncSession
    user_id: int | None = None
    workspace_id: int | None = None
    project_id: int | None = None


class MessageRateLimiter:
    def __init__(
        self,
        limit: int = MESSAGE_RATE_LIMIT,
        window_seconds: float = MESSAGE_RATE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._messages: deque[float] = deque()

    def allow(self) -> bool:
        now = self.clock()
        while self._messages and now - self._messages[0] >= self.window_seconds:
            self._messages.popleft()
        if len(self._messages) >= self.limit:
            return False
        self._messages.append(now)
        return True


class WebSocketConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[int, WebSocketConnection] = {}

    def add(self, websocket: WebSocket, db: AsyncSession) -> WebSocketConnection:
        connection = WebSocketConnection(websocket=websocket, db=db)
        self._connections[id(websocket)] = connection
        connection_gauge.set(len(self._connections))
        return connection

    def remove(self, websocket: WebSocket) -> None:
        self._connections.pop(id(websocket), None)
        connection_gauge.set(len(self._connections))

    @property
    def count(self) -> int:
        return len(self._connections)

    async def authorize_event(self, websocket: WebSocket, project_id: int) -> bool:
        """Revalidate a subscriber immediately before a future event send."""
        connection = self._connections.get(id(websocket))
        if connection is None or connection.project_id != project_id:
            return False
        if await _can_access_project(connection, project_id):
            return True
        await _close(websocket, 4403)
        self.remove(websocket)
        return False


connection_registry = WebSocketConnectionRegistry()


def _origin_is_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin or not host:
        return False

    expected_scheme = "https" if websocket.url.scheme == "wss" else "http"
    expected_origin = f"{expected_scheme}://{host}"
    try:
        parsed_origin = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed_origin.scheme in {"http", "https"}
        and not parsed_origin.username
        and not parsed_origin.password
        and parsed_origin.path in {"", "/"}
        and not parsed_origin.query
        and not parsed_origin.fragment
        and origin.rstrip("/").casefold() == expected_origin.casefold()
    )


def _message_bytes(received: Mapping[str, Any]) -> bytes | None:
    text = received.get("text")
    if isinstance(text, str):
        return text.encode("utf-8")
    data = received.get("bytes")
    return data if isinstance(data, bytes) else None


def _decode_message(raw: bytes) -> dict[str, Any] | None:
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json({"type": "error", "code": code, "message": message})


async def _close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except (RuntimeError, WebSocketDisconnect):
        pass


async def _can_access_project(connection: WebSocketConnection, project_id: int) -> bool:
    if connection.user_id is None or connection.workspace_id is None:
        return False

    try:
        project = await ProjectRepository.get_by_id(
            connection.db, project_id, workspace_id=connection.workspace_id
        )
        if project is None:
            return False

        is_workspace_member = await WorkspaceRepository.is_user_in_workspace(
            connection.db,
            workspace_id=connection.workspace_id,
            user_id=connection.user_id,
        )
        if not is_workspace_member:
            return False

        role = await MembershipRepository.get_role_in_project(
            connection.db, user_id=connection.user_id, project_id=project_id
        )
        return role is not None
    finally:
        await connection.db.rollback()


async def _receive_frame(
    websocket: WebSocket,
    *,
    timeout: float,
    limiter: MessageRateLimiter,
) -> tuple[dict[str, Any] | None, bool, bool]:
    """Return a parsed object, disconnect status, and timeout status."""
    try:
        received = await asyncio.wait_for(websocket.receive(), timeout=timeout)
    except TimeoutError:
        return None, False, True

    if received["type"] == "websocket.disconnect":
        return None, True, False

    raw = _message_bytes(received)
    if raw is None:
        await _send_error(websocket, "INVALID_MESSAGE", "Expected a JSON object message.")
        return None, False, False
    if not limiter.allow():
        await _send_error(
            websocket,
            "RATE_LIMITED",
            f"At most {MESSAGE_RATE_LIMIT} messages are allowed per "
            f"{int(MESSAGE_RATE_WINDOW_SECONDS)} seconds.",
        )
        return None, False, False
    if len(raw) > MAX_MESSAGE_BYTES:
        await _send_error(
            websocket,
            "MESSAGE_TOO_LARGE",
            f"Messages must not exceed {MAX_MESSAGE_BYTES} bytes.",
        )
        return None, False, False

    message = _decode_message(raw)
    if message is None:
        await _send_error(websocket, "INVALID_MESSAGE", "Expected a valid JSON object.")
        return None, False, False
    return message, False, False


async def _authenticate(
    websocket: WebSocket,
    connection: WebSocketConnection,
    limiter: MessageRateLimiter,
) -> bool:
    deadline = time.monotonic() + AUTHENTICATION_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            await _close(websocket, 4401)
            return False
        message, disconnected, timed_out = await _receive_frame(
            websocket, timeout=remaining, limiter=limiter
        )
        if disconnected:
            return False
        if timed_out:
            await _close(websocket, 4401)
            return False
        if message is None:
            continue
        if message.get("type") != "authenticate" or not isinstance(
            message.get("token"), str
        ):
            await _send_error(
                websocket,
                "AUTHENTICATION_REQUIRED",
                "The first valid message must contain an access token.",
            )
            continue

        try:
            user_id = decode_access_token(message["token"])
        except NotAuthenticatedError:
            await _close(websocket, 4401)
            return False

        try:
            user = await UserRepository.get_by_id(connection.db, user_id)
            if user is None or not user.is_active:
                await _close(websocket, 4401)
                return False

            try:
                workspace_id = await resolve_workspace_id(
                    connection.db, user, websocket.query_params.get("workspace_id")
                )
            except AppError as error:
                await _close(websocket, 4403 if error.status_code == 403 else 4400)
                return False

            if not await WorkspaceRepository.is_user_in_workspace(
                connection.db, workspace_id=workspace_id, user_id=user.id
            ):
                await _close(websocket, 4403)
                return False

            connection.user_id = user.id
            connection.workspace_id = workspace_id
        finally:
            await connection.db.rollback()

        await websocket.send_json({"type": "authenticated", "workspace_id": workspace_id})
        return True


async def _handle_message(
    websocket: WebSocket,
    connection: WebSocketConnection,
    message: dict[str, Any],
) -> None:
    message_type = message.get("type")
    if message_type == "pong":
        return

    if message_type == "subscribe":
        project_id = message.get("project_id")
        if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id <= 0:
            await _send_error(
                websocket, "INVALID_MESSAGE", "project_id must be a positive integer."
            )
            return
        if not await _can_access_project(connection, project_id):
            await _send_error(
                websocket,
                "PROJECT_FORBIDDEN",
                "You are not authorized to subscribe to this project.",
            )
            return
        connection.project_id = project_id
        await websocket.send_json({"type": "subscribed", "project_id": project_id})
        return

    await _send_error(websocket, "INVALID_MESSAGE", "Unknown message type.")


async def _serve_connection(
    websocket: WebSocket, connection: WebSocketConnection, limiter: MessageRateLimiter
) -> None:
    last_heartbeat = time.monotonic()
    pending_nonce: str | None = None
    heartbeat_deadline: float | None = None

    while True:
        now = time.monotonic()
        if pending_nonce is not None and heartbeat_deadline is not None:
            if now >= heartbeat_deadline:
                await _close(websocket, 1013)
                return
            wait_seconds = heartbeat_deadline - now
        else:
            wait_seconds = max(0.0, HEARTBEAT_INTERVAL_SECONDS - (now - last_heartbeat))

        message, disconnected, timed_out = await _receive_frame(
            websocket, timeout=wait_seconds, limiter=limiter
        )
        if disconnected:
            return
        if timed_out:
            if pending_nonce is not None:
                await _close(websocket, 1013)
                return
            if connection.project_id is not None and not await _can_access_project(
                connection, connection.project_id
            ):
                await _close(websocket, 4403)
                return
            pending_nonce = secrets.token_urlsafe(16)
            heartbeat_deadline = time.monotonic() + HEARTBEAT_TIMEOUT_SECONDS
            await websocket.send_json({"type": "heartbeat", "nonce": pending_nonce})
            continue
        if message is None:
            continue

        if message.get("type") == "pong":
            if message.get("nonce") != pending_nonce or pending_nonce is None:
                await _send_error(websocket, "INVALID_MESSAGE", "Heartbeat nonce did not match.")
                continue
            pending_nonce = None
            heartbeat_deadline = None
            last_heartbeat = time.monotonic()
            continue

        await _handle_message(websocket, connection, message)


@router.websocket("/ws/task-activity")
async def task_activity(
    websocket: WebSocket, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    """Authenticate and subscribe a client to project-scoped task activity."""
    if not _origin_is_allowed(websocket):
        await _close(websocket, 4403)
        return

    await websocket.accept()
    await websocket.send_json({"type": "ready", "requires": "authenticate"})
    connection = connection_registry.add(websocket, db)
    limiter = MessageRateLimiter()

    try:
        if await _authenticate(websocket, connection, limiter):
            await _serve_connection(websocket, connection, limiter)
    except WebSocketDisconnect:
        pass
    finally:
        connection_registry.remove(websocket)
        await _close(websocket, 1000)
