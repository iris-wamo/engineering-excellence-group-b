import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Message

from app.auth.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.enums import ProjectRole
from app.repositories.membership_repository import MembershipRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.websockets import task_activity
from app.websockets.task_activity import connection_gauge, connection_registry
from tests.fixtures.auth import expired_token_for


@dataclass
class AuthorizationState:
    users: dict[int, Any] = field(default_factory=dict)
    workspaces: set[int] = field(default_factory=lambda: {1})
    workspace_members: set[tuple[int, int]] = field(default_factory=set)
    projects: dict[int, int] = field(default_factory=dict)
    project_members: set[tuple[int, int]] = field(default_factory=set)

    def add_user(self, user_id: int, workspace_id: int) -> None:
        self.users[user_id] = type(
            "FakeUser", (), {"id": user_id, "is_active": True}
        )()
        self.workspace_members.add((user_id, workspace_id))

    def add_project(self, project_id: int, workspace_id: int) -> None:
        self.projects[project_id] = workspace_id


@pytest.fixture
def authorization_state(monkeypatch: pytest.MonkeyPatch) -> AuthorizationState:
    state = AuthorizationState()

    async def get_user(_db: Any, user_id: int) -> Any:
        return state.users.get(user_id)

    async def get_workspace(_db: Any, workspace_id: int) -> Any:
        if workspace_id not in state.workspaces:
            return None
        return type("FakeWorkspace", (), {"id": workspace_id})()

    async def is_workspace_member(_db: Any, *, workspace_id: int, user_id: int) -> bool:
        return (user_id, workspace_id) in state.workspace_members

    async def get_user_workspaces(_db: Any, user_id: int) -> list[Any]:
        return [
            type("FakeWorkspace", (), {"id": workspace_id})()
            for member_id, workspace_id in state.workspace_members
            if member_id == user_id
        ]

    async def get_project(
        _db: Any, project_id: int, workspace_id: int | None = None
    ) -> Any:
        resolved_workspace_id = state.projects.get(project_id)
        if resolved_workspace_id is None or (
            workspace_id is not None and resolved_workspace_id != workspace_id
        ):
            return None
        return type(
            "FakeProject",
            (),
            {"id": project_id, "workspace_id": resolved_workspace_id},
        )()

    async def get_project_role(_db: Any, *, user_id: int, project_id: int) -> ProjectRole | None:
        return (
            ProjectRole.member
            if (user_id, project_id) in state.project_members
            else None
        )

    monkeypatch.setattr(UserRepository, "get_by_id", staticmethod(get_user))
    monkeypatch.setattr(WorkspaceRepository, "get_by_id", staticmethod(get_workspace))
    monkeypatch.setattr(
        WorkspaceRepository, "is_user_in_workspace", staticmethod(is_workspace_member)
    )
    monkeypatch.setattr(
        WorkspaceRepository, "get_user_workspaces", staticmethod(get_user_workspaces)
    )
    monkeypatch.setattr(ProjectRepository, "get_by_id", staticmethod(get_project))
    monkeypatch.setattr(
        MembershipRepository, "get_role_in_project", staticmethod(get_project_role)
    )
    return state


@pytest.fixture
async def websocket_database() -> AsyncGenerator[None, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield AsyncMock(spec=AsyncSession)

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


class WebSocketProbe:
    def __init__(
        self,
        *,
        workspace_id: str | int | None = None,
        origin: str | None = "http://testserver",
    ) -> None:
        query = urlencode({"workspace_id": workspace_id}) if workspace_id is not None else ""
        headers = [(b"host", b"testserver")]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        self.scope: dict[str, Any] = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "scheme": "ws",
            "server": ("testserver", 80),
            "client": ("testclient", 12345),
            "root_path": "",
            "path": "/api/v1/ws/task-activity",
            "raw_path": b"/api/v1/ws/task-activity",
            "query_string": query.encode(),
            "headers": headers,
            "subprotocols": [],
            "state": {},
        }
        self.incoming: asyncio.Queue[Message] = asyncio.Queue()
        self.outgoing: asyncio.Queue[Message] = asyncio.Queue()
        self.closed = False
        self._sent_connect = False
        self.task: asyncio.Task[None] | None = None

    async def _receive(self) -> Message:
        if not self._sent_connect:
            self._sent_connect = True
            return {"type": "websocket.connect"}
        return await self.incoming.get()

    async def _send(self, message: Message) -> None:
        if self.closed:
            raise RuntimeError("The WebSocket has already closed.")
        if message["type"] == "websocket.close":
            self.closed = True
        await self.outgoing.put(message)

    async def start(self) -> dict[str, Any]:
        self.task = asyncio.create_task(app(self.scope, self._receive, self._send))
        first_event = await asyncio.wait_for(self.outgoing.get(), timeout=1)
        if first_event["type"] == "websocket.close":
            return {"handshake_status": 403}
        assert first_event["type"] == "websocket.accept"
        return await self.next_frame()

    async def send(self, message: str | bytes) -> None:
        if isinstance(message, str):
            frame: Message = {"type": "websocket.receive", "text": message}
        else:
            frame = {"type": "websocket.receive", "bytes": message}
        await self.incoming.put(frame)

    async def send_json(self, message: dict[str, Any]) -> None:
        await self.send(json.dumps(message))

    async def next_frame(self) -> dict[str, Any]:
        frame = await asyncio.wait_for(self.outgoing.get(), timeout=1)
        if frame["type"] == "websocket.send":
            decoded = json.loads(frame["text"])
            if isinstance(decoded, dict):
                return {key: value for key, value in decoded.items() if isinstance(key, str)}
            return {}
        if frame["type"] == "websocket.close":
            return {"close_code": frame["code"]}
        return dict(frame)

    async def authenticate(self, token: str) -> dict[str, Any]:
        await self.send_json({"type": "authenticate", "token": token})
        return await self.next_frame()

    async def disconnect(self) -> None:
        if self.task is not None and not self.task.done():
            await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        if self.task is not None:
            await self.task


async def authenticate_and_subscribe(
    probe: WebSocketProbe, user_id: int, project_id: int, workspace_id: int
) -> None:
    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate(create_access_token(user_id)) == {
        "type": "authenticated",
        "workspace_id": workspace_id,
    }
    await probe.send_json({"type": "subscribe", "project_id": project_id})
    assert await probe.next_frame() == {"type": "subscribed", "project_id": project_id}


@pytest.mark.parametrize("origin", [None, "https://attacker.example", "http://[invalid"])
async def test_missing_or_cross_origin_is_rejected(
    websocket_database: None, authorization_state: AuthorizationState, origin: str | None
) -> None:
    probe = WebSocketProbe(origin=origin)

    assert await probe.start() == {"handshake_status": 403}
    await probe.disconnect()

    assert connection_registry.count == 0
    assert connection_gauge._value.get() == 0


@pytest.mark.unit
async def test_missing_token_is_rejected_and_registry_gauge_returns_to_zero(
    websocket_database: None,
    authorization_state: AuthorizationState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task_activity, "AUTHENTICATION_TIMEOUT_SECONDS", 0.01)
    probe = WebSocketProbe()

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.next_frame() == {"close_code": 4401}
    await probe.disconnect()

    assert connection_registry.count == 0
    assert connection_gauge._value.get() == 0


@pytest.mark.unit
async def test_invalid_jwt_is_rejected(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    probe = WebSocketProbe(workspace_id=1)

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate("not-a-valid-jwt") == {"close_code": 4401}
    await probe.disconnect()

    assert connection_registry.count == 0


@pytest.mark.unit
async def test_expired_jwt_is_rejected(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    authorization_state.add_user(10, 1)
    probe = WebSocketProbe(workspace_id=1)

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate(expired_token_for(10)) == {"close_code": 4401}
    await probe.disconnect()

    assert connection_registry.count == 0


@pytest.mark.unit
async def test_inactive_user_is_rejected(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    authorization_state.add_user(11, 1)
    authorization_state.users[11].is_active = False
    probe = WebSocketProbe(workspace_id=1)

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate(create_access_token(11)) == {"close_code": 4401}
    await probe.disconnect()

    assert connection_registry.count == 0


@pytest.mark.unit
async def test_user_from_another_workspace_is_rejected(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    authorization_state.workspaces.add(2)
    authorization_state.add_user(20, 2)
    probe = WebSocketProbe(workspace_id=1)

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate(create_access_token(20)) == {"close_code": 4403}
    await probe.disconnect()

    assert connection_registry.count == 0


@pytest.mark.unit
async def test_invalid_workspace_selection_is_rejected(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    authorization_state.add_user(21, 1)
    probe = WebSocketProbe(workspace_id="invalid")

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate(create_access_token(21)) == {"close_code": 4400}
    await probe.disconnect()

    assert connection_registry.count == 0


@pytest.mark.unit
async def test_nonmember_cannot_subscribe_to_project(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    authorization_state.add_user(30, 1)
    authorization_state.add_project(300, 1)
    probe = WebSocketProbe(workspace_id=1)

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate(create_access_token(30)) == {
        "type": "authenticated",
        "workspace_id": 1,
    }
    await probe.send_json({"type": "subscribe", "project_id": 300})
    assert await probe.next_frame() == {
        "type": "error",
        "code": "PROJECT_FORBIDDEN",
        "message": "You are not authorized to subscribe to this project.",
    }

    await probe.disconnect()
    assert connection_registry.count == 0
    assert connection_gauge._value.get() == 0


@pytest.mark.unit
async def test_project_membership_is_rechecked_before_event_authorization(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    authorization_state.add_user(40, 1)
    authorization_state.add_project(400, 1)
    authorization_state.project_members.add((40, 400))
    probe = WebSocketProbe(workspace_id=1)
    await authenticate_and_subscribe(probe, 40, 400, 1)

    authorization_state.project_members.remove((40, 400))
    connection = next(iter(connection_registry._connections.values()))

    assert not await connection_registry.authorize_event(connection.websocket, 400)
    assert await probe.next_frame() == {"close_code": 4403}
    assert connection_registry.count == 0
    assert connection_gauge._value.get() == 0

    await probe.disconnect()


@pytest.mark.unit
async def test_invalid_and_oversized_messages_do_not_disconnect_other_clients(
    websocket_database: None, authorization_state: AuthorizationState
) -> None:
    authorization_state.add_user(50, 1)
    authorization_state.add_project(500, 1)
    authorization_state.project_members.add((50, 500))
    first = WebSocketProbe(workspace_id=1)
    second = WebSocketProbe(workspace_id=1)

    await authenticate_and_subscribe(first, 50, 500, 1)
    await authenticate_and_subscribe(second, 50, 500, 1)
    await first.send("not-json")
    assert (await first.next_frame())["code"] == "INVALID_MESSAGE"
    await first.send("x" * (task_activity.MAX_MESSAGE_BYTES + 1))
    assert (await first.next_frame())["code"] == "MESSAGE_TOO_LARGE"

    await second.send_json({"type": "subscribe", "project_id": 500})
    assert await second.next_frame() == {"type": "subscribed", "project_id": 500}
    assert connection_registry.count == 2
    assert connection_gauge._value.get() == 2

    await first.disconnect()
    await second.disconnect()
    assert connection_registry.count == 0
    assert connection_gauge._value.get() == 0


@pytest.mark.unit
async def test_missed_heartbeat_closes_and_removes_stale_connection(
    websocket_database: None,
    authorization_state: AuthorizationState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task_activity, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(task_activity, "HEARTBEAT_TIMEOUT_SECONDS", 0.01)
    authorization_state.add_user(60, 1)
    probe = WebSocketProbe(workspace_id=1)

    assert await probe.start() == {"type": "ready", "requires": "authenticate"}
    assert await probe.authenticate(create_access_token(60)) == {
        "type": "authenticated",
        "workspace_id": 1,
    }
    assert (await probe.next_frame())["type"] == "heartbeat"
    assert await probe.next_frame() == {"close_code": 1013}
    await probe.disconnect()

    assert connection_registry.count == 0
    assert connection_gauge._value.get() == 0


@pytest.mark.unit
def test_message_rate_limiter_rejects_bursts_and_recovers() -> None:
    now = [0.0]
    limiter = task_activity.MessageRateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

    assert limiter.allow()
    assert limiter.allow()
    assert not limiter.allow()
    now[0] = 10.0
    assert limiter.allow()
