from fastapi.testclient import TestClient


def test_create_task_returns_201_and_payload(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Alpha"}).json()["id"]

    response = client.post(
        "/api/v1/tasks",
        json={"title": "Login", "project_id": project_id},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Login"
    assert body["project_id"] == project_id
    assert body["status"] == "todo"


def test_create_task_rejects_blank_title(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Alpha"}).json()["id"]

    response = client.post(
        "/api/v1/tasks",
        json={"title": "", "project_id": project_id},
    )

    assert response.status_code == 422


def test_get_task_returns_404_for_missing_task(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/999900000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_tasks_returns_paginated_envelope(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Alpha"}).json()["id"]
    client.post("/api/v1/tasks", json={"title": "A", "project_id": project_id})
    client.post("/api/v1/tasks", json={"title": "B", "project_id": project_id})

    response = client.get("/api/v1/tasks?page=1&page_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1


def test_update_task_status(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Alpha"}).json()["id"]
    task_id = client.post(
        "/api/v1/tasks",
        json={"title": "Login", "project_id": project_id},
    ).json()["id"]

    response = client.patch(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_progress"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"