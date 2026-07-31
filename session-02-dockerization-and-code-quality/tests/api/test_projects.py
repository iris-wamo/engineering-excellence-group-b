from fastapi.testclient import TestClient


def test_create_project_returns_201_and_payload(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "Alpha", "description": "First"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Alpha"
    assert body["description"] == "First"
    assert body["id"] is not None


def test_create_project_rejects_blank_name(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "   "})

    assert response.status_code == 422


def test_list_projects_returns_paginated_envelope(client: TestClient) -> None:
    client.post("/api/v1/projects", json={"name": "Alpha"})
    client.post("/api/v1/projects", json={"name": "Beta"})

    response = client.get("/api/v1/projects?page=1&page_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1


def test_get_project_returns_created_project_by_id(client: TestClient) -> None:
    created = client.post("/api/v1/projects", json={"name": "Alpha"}).json()

    response = client.get(f"/api/v1/projects/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_project_returns_404_error_envelope_for_missing_project(client: TestClient) -> None:
    response = client.get("/api/v1/projects/999900000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_project_returns_422_for_non_positive_id(client: TestClient) -> None:
    response = client.get("/api/v1/projects/0")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_projects_rejects_invalid_sort_by(client: TestClient) -> None:
    response = client.get("/api/v1/projects?sort_by=bogus")

    assert response.status_code == 422
