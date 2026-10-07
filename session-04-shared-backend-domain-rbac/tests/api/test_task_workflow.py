from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.enums import TaskStatus
from app.models.task_status_history import TaskStatusHistory


async def test_valid_task_transitions(client: AsyncClient) -> None:
    # 1. Create project & task
    project_resp = await client.post("/api/v1/projects", json={"name": "Workflow Project"})
    project_id = project_resp.json()["id"]
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Workflow Task", "project_id": project_id},
        )
    ).json()["id"]

    # todo -> in_progress
    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"

    # in_progress -> review
    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "review"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "review"

    # review -> done
    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


async def test_reverse_task_transition_is_allowed(client: AsyncClient) -> None:
    project_resp = await client.post("/api/v1/projects", json={"name": "Workflow Project 2"})
    project_id = project_resp.json()["id"]
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Reverse Workflow Task", "project_id": project_id},
        )
    ).json()["id"]

    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"

    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "todo"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "todo"


async def test_invalid_task_transition(client: AsyncClient) -> None:
    # 1. Create project & task
    project_resp = await client.post("/api/v1/projects", json={"name": "Workflow Project 3"})
    project_id = project_resp.json()["id"]
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Workflow Task 3", "project_id": project_id},
        )
    ).json()["id"]

    # todo -> done (invalid)
    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "done"})
    assert resp.status_code == 400

    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def _create_task(client: AsyncClient, name: str) -> int:
    project_id = (await client.post("/api/v1/projects", json={"name": name})).json()["id"]
    resp = await client.post("/api/v1/tasks", json={"title": name, "project_id": project_id})
    return int(resp.json()["id"])


async def _move(client: AsyncClient, task_id: int, status: str) -> int:
    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": status})
    return resp.status_code


async def _history_rows(db: AsyncSession, task_id: int) -> list[tuple[TaskStatus, TaskStatus]]:
    rows = await db.scalars(
        select(TaskStatusHistory)
        .where(TaskStatusHistory.task_id == task_id)
        .order_by(TaskStatusHistory.id)
    )
    return [(r.previous_status, r.new_status) for r in rows]


async def _activity_count(db: AsyncSession, task_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ActivityLog)
            .where(ActivityLog.entity_type == "task", ActivityLog.entity_id == task_id)
        )
        or 0
    )


async def test_valid_move_writes_history_and_activity_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    task_id = await _create_task(client, "Audit Trail")

    for status in ("in_progress", "review", "in_progress", "review", "done"):
        assert await _move(client, task_id, status) == 200

    assert await _history_rows(db_session, task_id) == [
        (TaskStatus.todo, TaskStatus.in_progress),
        (TaskStatus.in_progress, TaskStatus.review),
        (TaskStatus.review, TaskStatus.in_progress),
        (TaskStatus.in_progress, TaskStatus.review),
        (TaskStatus.review, TaskStatus.done),
    ]
    logs = (
        await db_session.scalars(
            select(ActivityLog)
            .where(ActivityLog.entity_type == "task", ActivityLog.entity_id == task_id)
            .order_by(ActivityLog.id)
        )
    ).all()
    assert [log.action for log in logs] == ["STATUS_CHANGED"] * 5
    assert logs[0].details == {"previous_status": "todo", "new_status": "in_progress"}
    assert logs[-1].details == {"previous_status": "review", "new_status": "done"}


async def test_rejected_move_writes_nothing(client: AsyncClient, db_session: AsyncSession) -> None:
    task_id = await _create_task(client, "Rejected Move")

    assert await _move(client, task_id, "done") == 400

    assert await _history_rows(db_session, task_id) == []
    assert await _activity_count(db_session, task_id) == 0
    assert (await client.get(f"/api/v1/tasks/{task_id}")).json()["status"] == "todo"


async def test_reopen_and_rework_paths(client: AsyncClient, db_session: AsyncSession) -> None:
    task_id = await _create_task(client, "Reopen")
    for status in ("in_progress", "review", "done"):
        assert await _move(client, task_id, status) == 200

    # done -> review (reopen) and review -> in_progress (rework)
    assert await _move(client, task_id, "review") == 200
    assert await _move(client, task_id, "in_progress") == 200

    history = await _history_rows(db_session, task_id)
    assert history[-2:] == [
        (TaskStatus.done, TaskStatus.review),
        (TaskStatus.review, TaskStatus.in_progress),
    ]


async def test_skipping_steps_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    task_id = await _create_task(client, "Skips")
    assert await _move(client, task_id, "in_progress") == 200
    assert await _move(client, task_id, "done") == 400  # in_progress -> done
    assert await _move(client, task_id, "review") == 200
    assert await _move(client, task_id, "todo") == 400  # review -> todo
    assert await _move(client, task_id, "done") == 200
    assert await _move(client, task_id, "todo") == 400  # done -> todo
    assert await _move(client, task_id, "in_progress") == 400  # done -> in_progress

    # Only the 3 successful moves were recorded
    assert len(await _history_rows(db_session, task_id)) == 3


async def test_same_status_is_a_noop(client: AsyncClient, db_session: AsyncSession) -> None:
    task_id = await _create_task(client, "Idempotent")
    assert await _move(client, task_id, "in_progress") == 200
    before = await _activity_count(db_session, task_id)

    resp = await client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "in_progress"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"
    assert await _activity_count(db_session, task_id) == before
    assert await _history_rows(db_session, task_id) == [(TaskStatus.todo, TaskStatus.in_progress)]
