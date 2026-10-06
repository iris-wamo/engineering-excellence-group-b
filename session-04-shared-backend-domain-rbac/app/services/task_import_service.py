"""Service layer for raw task imports and normalization."""

from datetime import UTC, date, datetime
from typing import Any

from bson import ObjectId
from pymongo.collection import Collection
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.enums import ImportStatus

from app.core.exceptions import NotFoundError
from app.db.mongo import get_raw_task_imports_collection
from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.task_import import TaskImportDetailResponse, TaskImportResponse
from app.services.task_service import _verify_project_membership


class TaskImportService:
    """Orchestrates ingesting raw payloads into MongoDB and normalizing to PostgreSQL."""

    @staticmethod
    async def import_raw_task(
        db: AsyncSession,
        raw_payload: dict[str, Any],
        collection: Collection[dict[str, Any]] | None = None,
    ) -> TaskImportResponse:
        """Store incoming raw task payload first in MongoDB, then normalize to PostgreSQL."""
        col = collection if collection is not None else get_raw_task_imports_collection()

        now = datetime.now(UTC)
        mongo_doc = {
            "raw_payload": raw_payload,
            "status": ImportStatus.PENDING.value,
            "postgres_task_id": None,
            "error_details": None,
            "created_at": now,
            "updated_at": now,
        }
        insert_result = col.insert_one(mongo_doc)
        mongo_id = insert_result.inserted_id
        import_id_str = str(mongo_id)

        try:
            # 1. Title / Summary extraction and validation
            raw_title = raw_payload.get("title") or raw_payload.get("summary")
            if not raw_title or not str(raw_title).strip():
                raise ValueError("Missing 'title' or 'summary' in raw payload.")
            title = str(raw_title).strip()

            # 2. Project ID validation
            raw_project_id = raw_payload.get("project_id")
            if raw_project_id is None:
                raise ValueError("Missing 'project_id' in raw payload.")
            try:
                project_id = int(raw_project_id)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid 'project_id': {raw_project_id}") from exc

            project = await ProjectRepository.get_by_id(db, project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found.")

            # 3. Status extraction and validation
            raw_status = raw_payload.get("status", "todo")
            try:
                status = (
                    TaskStatus(raw_status)
                    if isinstance(raw_status, TaskStatus)
                    else TaskStatus(str(raw_status).lower())
                )
            except (ValueError, KeyError) as exc:
                raise ValueError(f"Invalid status '{raw_status}'.") from exc

            # 4. Priority extraction and validation
            raw_priority = raw_payload.get("priority", "medium")
            try:
                priority = (
                    TaskPriority(raw_priority)
                    if isinstance(raw_priority, TaskPriority)
                    else TaskPriority(str(raw_priority).lower())
                )
            except (ValueError, KeyError) as exc:
                raise ValueError(f"Invalid priority '{raw_priority}'.") from exc

            # 5. Optional due date parsing
            due_date: date | None = None
            raw_due_date = raw_payload.get("due_date")
            if raw_due_date:
                if isinstance(raw_due_date, date):
                    due_date = raw_due_date
                else:
                    try:
                        due_date = date.fromisoformat(str(raw_due_date).split("T")[0])
                    except (ValueError, TypeError) as exc:
                        raise ValueError(f"Invalid due_date format: {raw_due_date}") from exc

            # 6. Optional Assignee validation and project membership verification
            assignee_id: int | None = None
            raw_assignee_id = raw_payload.get("assignee_id")
            if raw_assignee_id is not None:
                try:
                    assignee_id = int(raw_assignee_id)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Invalid 'assignee_id': {raw_assignee_id}") from exc

                assignee = await UserRepository.get_by_id(db, assignee_id)
                if assignee is None:
                    raise ValueError(f"Assignee user {assignee_id} not found.")
                await _verify_project_membership(db, assignee_id, project_id)

            # 7. Normalize & Persist into PostgreSQL
            task = Task(
                title=title,
                description=raw_payload.get("description"),
                status=status,
                priority=priority,
                due_date=due_date,
                project_id=project_id,
                assignee_id=assignee_id,
                mongo_import_id=import_id_str,
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)

            # 8. Update MongoDB with SUCCESS status & PostgreSQL reference
            updated_at = datetime.now(UTC)
            col.update_one(
                {"_id": mongo_id},
                {
                    "$set": {
                        "status": ImportStatus.SUCCESS.value,
                        "postgres_task_id": task.id,
                        "updated_at": updated_at,
                    }
                },
            )

            return TaskImportResponse(
                import_id=import_id_str,
                status=ImportStatus.SUCCESS,
                postgres_task_id=task.id,
                error_details=None,
                created_at=now,
                updated_at=updated_at,
            )

        except Exception as exc:
            await db.rollback()
            updated_at = datetime.now(UTC)
            error_details = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            col.update_one(
                {"_id": mongo_id},
                {
                    "$set": {
                        "status": ImportStatus.FAILED.value,
                        "error_details": error_details,
                        "updated_at": updated_at,
                    }
                },
            )

            return TaskImportResponse(
                import_id=import_id_str,
                status=ImportStatus.FAILED,
                postgres_task_id=None,
                error_details=error_details,
                created_at=now,
                updated_at=updated_at,
            )

    @staticmethod
    async def import_raw_tasks_batch(
        db: AsyncSession,
        items: list[dict[str, Any]],
        collection: Collection[dict[str, Any]] | None = None,
    ) -> tuple[int, int, int, list[TaskImportResponse]]:
        """Ingest multiple raw task payloads into MongoDB and normalize independently."""
        results: list[TaskImportResponse] = []
        succeeded = 0
        failed = 0

        for raw_payload in items:
            res = await TaskImportService.import_raw_task(
                db=db,
                raw_payload=raw_payload,
                collection=collection,
            )
            results.append(res)
            if res.status == ImportStatus.SUCCESS:
                succeeded += 1
            else:
                failed += 1

        return len(items), succeeded, failed, results

    @staticmethod
    def get_import_by_id(
        import_id: str,
        collection: Collection[dict[str, Any]] | None = None,
    ) -> TaskImportDetailResponse:
        """Retrieve the raw task import record and current status from MongoDB."""
        col = collection if collection is not None else get_raw_task_imports_collection()

        if not ObjectId.is_valid(import_id):
            raise NotFoundError(
                "Import record not found",
                details=[{"field": "import_id", "message": f"Invalid import ID: '{import_id}'"}],
            )

        doc = col.find_one({"_id": ObjectId(import_id)})
        if not doc:
            raise NotFoundError(
                "Import record not found",
                details=[{"field": "import_id", "message": f"Import '{import_id}' not found"}],
            )

        raw_status = str(doc.get("status", ImportStatus.PENDING.value))
        try:
            status = ImportStatus(raw_status)
        except ValueError:
            status = ImportStatus.FAILED

        return TaskImportDetailResponse(
            import_id=str(doc["_id"]),
            status=status,
            postgres_task_id=doc.get("postgres_task_id"),
            error_details=doc.get("error_details"),
            raw_payload=doc.get("raw_payload", {}),
            created_at=doc.get("created_at", datetime.now(UTC)),
            updated_at=doc.get("updated_at", datetime.now(UTC)),
        )
