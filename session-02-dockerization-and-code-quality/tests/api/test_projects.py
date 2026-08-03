from httpx import AsyncClient


async def test_create_project_returns_201_and_payload(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects", json={"name": "Alpha", "description": "First"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Alpha"
    assert body["description"] == "First"
    assert body["id"] is not None


async def test_create_project_rejects_blank_name(client: AsyncClient) -> None:
    response = await client.post("/api/v1/projects", json={"name": "   "})

    assert response.status_code == 422


async def test_list_projects_returns_paginated_envelope(client: AsyncClient) -> None:
    await client.post("/api/v1/projects", json={"name": "Alpha"})
    await client.post("/api/v1/projects", json={"name": "Beta"})

    response = await client.get("/api/v1/projects?page=1&page_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1


async def test_get_project_returns_created_project_by_id(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/projects", json={"name": "Alpha"})).json()

    response = await client.get(f"/api/v1/projects/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_project_returns_404_error_envelope_for_missing_project(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/projects/999900000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_get_project_returns_422_for_non_positive_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects/0")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_list_projects_rejects_invalid_sort_by(client: AsyncClient) -> None:
    response = await client.get("/api/v1/projects?sort_by=bogus")

    assert response.status_code == 422
