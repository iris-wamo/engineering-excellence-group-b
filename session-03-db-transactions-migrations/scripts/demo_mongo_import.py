"""Demo 06 — Raw Task-Import: MongoDB ➜ PostgreSQL with traceability.

Run:  uv run python scripts/demo_mongo_import.py
Requires: docker compose up -d db mongo  (Postgres on 5433, Mongo on 27017)
"""

import asyncio
import json
from datetime import UTC, datetime

from bson import ObjectId
from pymongo import MongoClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.project import Project
from app.models.task import Task

DATABASE_URL = "postgresql+asyncpg://taskflow:taskflow@localhost:5433/taskflow"
MONGO_URL = "mongodb://localhost:27017"
MONGO_DB = "taskflow_imports"


def mongo_collection():  # type: ignore[no-untyped-def]
    return MongoClient(MONGO_URL)[MONGO_DB]["raw_task_imports"]


def pp(doc: dict) -> None:  # type: ignore[type-arg]
    """Pretty-print a Mongo document, converting non-serialisable types."""

    def default(o):  # type: ignore[no-untyped-def]
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    print(json.dumps(doc, indent=2, default=default))


async def try_import(
    db: AsyncSession,
    col,  # type: ignore[no-untyped-def]
    raw: dict,  # type: ignore[type-arg]
    label: str,
) -> None:
    """Store raw payload in Mongo, attempt Postgres insert, update Mongo status."""
    now = datetime.now(UTC)
    mongo_doc = {
        "raw_payload": raw,
        "status": "PENDING",
        "postgres_task_id": None,
        "error_details": None,
        "created_at": now,
        "updated_at": now,
    }
    mongo_id = col.insert_one(mongo_doc).inserted_id

    try:
        # ---- validate ----
        title = raw.get("title") or raw.get("summary")
        if not title:
            raise ValueError("Missing 'title' or 'summary'.")
        project = await db.get(Project, int(raw["project_id"]))
        if not project:
            raise ValueError(f"Project {raw['project_id']} not found.")
        from app.models.enums import TaskPriority, TaskStatus

        status = TaskStatus(raw.get("status", "todo"))
        priority = TaskPriority(raw.get("priority", "medium"))

        # ---- insert into Postgres ----
        task = Task(
            title=str(title).strip(),
            description=raw.get("description"),
            status=status,
            priority=priority,
            project_id=project.id,
            mongo_import_id=str(mongo_id),
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        col.update_one(
            {"_id": mongo_id},
            {
                "$set": {
                    "status": "SUCCESS",
                    "postgres_task_id": task.id,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        print(f"\n✅  {label}  — Postgres task.id={task.id}")
    except Exception as exc:
        await db.rollback()
        col.update_one(
            {"_id": mongo_id},
            {
                "$set": {
                    "status": "FAILED",
                    "error_details": {"message": str(exc), "type": type(exc).__name__},
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        print(f"\n❌  {label}  — {exc}")

    doc = col.find_one({"_id": mongo_id})
    doc["_id"] = str(doc["_id"])
    pp(doc)


async def main() -> None:
    print("=" * 60)
    print(" DEMO 06 — Mongo Raw Import → Postgres Normalisation")
    print("=" * 60)

    engine = create_async_engine(DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    col = mongo_collection()

    # wipe previous demo data
    col.delete_many({})

    async with session_factory() as db:
        # find any existing project
        proj = (await db.execute(select(Project).limit(1))).scalar_one_or_none()
        if not proj:
            print("No projects in Postgres — run `make seed` first.")
            return

        # --- Scenario 1: valid payload ---
        await try_import(
            db,
            col,
            {
                "summary": "Implement OAuth2 SSO",
                "project_id": proj.id,
                "status": "in_progress",
                "priority": "high",
                "jira_key": "SEC-402",
            },
            "Successful import",
        )

        # --- Scenario 2: invalid priority (FAILED) ---
        await try_import(
            db,
            col,
            {
                "title": "Broken task",
                "project_id": proj.id,
                "priority": "ULTRA_HIGH",
            },
            "Failed import (bad priority)",
        )

    await engine.dispose()
    print("\n" + "=" * 60)
    print(" DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
