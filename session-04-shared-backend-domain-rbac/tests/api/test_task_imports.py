"""Integration tests for raw task import API endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.mongo import get_raw_task_imports_collection
from app.models.project import Project


@pytest.fixture(autouse=True)
def clean_mongo_imports() -> None:
    """Ensure clean raw_task_imports collection before each test."""
    col = get_raw_task_imports_collection()
    col.delete_many({})


async def _create_test_project(
    db: AsyncSession, name: str = "API Import Project", slug: str = "api-import-project"
) -> Project:
    proj = Project(name=name, slug=slug, description="Project for API import testing")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_api_import_raw_task_success(client: AsyncClient, db_session: AsyncSession) -> None:
    project = await _create_test_project(db_session)
    payload = {
        "raw_payload": {
            "summary": "Setup Monitoring & Alerting",
            "description": "Config Prometheus and Grafana dashboards",
            "project_id": project.id,
            "priority": "high",
            "status": "todo",
            "jira_key": "DEVOPS-55",
        }
    }

    response = await client.post("/api/v1/tasks/import", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["import_id"] is not None
    assert data["postgres_task_id"] is not None
    assert data["error_details"] is None

    # Fetch import details via GET /api/v1/tasks/import/{import_id}
    detail_res = await client.get(f"/api/v1/tasks/import/{data['import_id']}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["status"] == "SUCCESS"
    assert detail_data["postgres_task_id"] == data["postgres_task_id"]
    assert detail_data["raw_payload"]["jira_key"] == "DEVOPS-55"


async def test_api_import_raw_task_failure(client: AsyncClient) -> None:
    payload = {
        "raw_payload": {
            "summary": "Task with missing project",
            "project_id": 888888,
        }
    }

    response = await client.post("/api/v1/tasks/import", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "FAILED"
    assert data["import_id"] is not None
    assert data["postgres_task_id"] is None
    assert data["error_details"] is not None
    assert "888888 not found" in data["error_details"]["message"]

    # Fetch failure record via GET /api/v1/tasks/import/{import_id}
    detail_res = await client.get(f"/api/v1/tasks/import/{data['import_id']}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["status"] == "FAILED"
    assert detail_data["error_details"] is not None


async def test_api_get_raw_task_import_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/import/6701a2b3c4d5e6f7a8b9c0d1")
    assert response.status_code == 404


async def test_api_import_raw_tasks_batch_mixed_results(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    project = await _create_test_project(db_session, name="Batch Proj", slug="batch-proj")
    batch_payload = {
        "items": [
            {
                "raw_payload": {
                    "summary": "Valid Task in Batch",
                    "project_id": project.id,
                    "priority": "high",
                }
            },
            {
                "raw_payload": {
                    "summary": "Invalid Task in Batch",
                    "project_id": 9999999,
                    "priority": "low",
                }
            },
        ]
    }

    response = await client.post("/api/v1/tasks/import/batch", json=batch_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert len(data["results"]) == 2

    res_success = data["results"][0]
    assert res_success["status"] == "SUCCESS"
    assert res_success["postgres_task_id"] is not None

    res_fail = data["results"][1]
    assert res_fail["status"] == "FAILED"
    assert res_fail["postgres_task_id"] is None
    assert "9999999 not found" in res_fail["error_details"]["message"]


async def test_api_import_raw_tasks_batch_rejects_empty_items(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tasks/import/batch", json={"items": []})
    assert response.status_code == 422
