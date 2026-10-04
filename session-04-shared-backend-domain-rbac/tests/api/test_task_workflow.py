import pytest
from httpx import AsyncClient

async def test_valid_task_transitions(client: AsyncClient) -> None:
    # 1. Create project & task
    project_id = (await client.post("/api/v1/projects", json={"name": "Workflow Project"})).json()["id"]
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
    project_id = (await client.post("/api/v1/projects", json={"name": "Workflow Project 2"})).json()["id"]
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
    project_id = (await client.post("/api/v1/projects", json={"name": "Workflow Project 3"})).json()["id"]
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
