"""Service layer for raw task imports and normalization."""

import logging
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pydantic import ValidationError
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.enums import ImportStatus

from app.core.exceptions import AppError, NotFoundError
from app.db.mongo import get_raw_task_imports_collection
from app.models.task import Task
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.task_import import (
    NormalizedTaskPayload,
    TaskImportDetailResponse,
    TaskImportResponse,
)
from app.services.task_service import verify_project_membership

logger = logging.getLogger(__name__)


class TaskImportService:
    """Orchestrates ingesting raw payloads into MongoDB and normalizing to PostgreSQL."""

    @staticmethod
    async def import_raw_task(
        db: AsyncSession,
        raw_payload: dict[str, Any],
        collection: AsyncCollection[dict[str, Any]] | None = None,
        idempotency_key: str | None = None,
    ) -> TaskImportResponse:
        """Store incoming raw task payload first in MongoDB, then normalize to PostgreSQL."""
        col = collection if collection is not None else get_raw_task_imports_collection()

        # Determine effective idempotency key from argument or raw payload
        raw_key = (
            idempotency_key
            or raw_payload.get("idempotency_key")
            or raw_payload.get("jira_key")
            or raw_payload.get("external_id")
        )
        effective_key = str(raw_key).strip() if raw_key is not None else None

        # Check for existing import if idempotency key is provided
        if effective_key:
            existing = await col.find_one({"idempotency_key": effective_key})
            if existing:
                logger.info(
                    "Idempotent import match found for key %s (mongo_id: %s)",
                    effective_key,
                    existing["_id"],
                )
                raw_status = str(existing.get("status", ImportStatus.PENDING.value))
                try:
                    status_enum = ImportStatus(raw_status)
                except ValueError:
                    status_enum = ImportStatus.FAILED

                postgres_task_id = existing.get("postgres_task_id")
                updated_at = existing.get("updated_at", datetime.now(UTC))

                # Reconcile if MongoDB was left in PENDING but Postgres task was committed
                if status_enum == ImportStatus.PENDING:
                    stmt = select(Task).where(Task.mongo_import_id == str(existing["_id"]))
                    committed_task = (await db.execute(stmt)).scalar_one_or_none()
                    if committed_task is not None:
                        status_enum = ImportStatus.SUCCESS
                        postgres_task_id = committed_task.id
                        updated_at = datetime.now(UTC)
                        try:
                            await col.update_one(
                                {"_id": existing["_id"]},
                                {
                                    "$set": {
                                        "status": ImportStatus.SUCCESS.value,
                                        "postgres_task_id": committed_task.id,
                                        "updated_at": updated_at,
                                    }
                                },
                            )
                        except Exception as mongo_err:
                            logger.error(
                                "Failed to reconcile MongoDB status on retry for %s: %s",
                                existing["_id"],
                                mongo_err,
                            )

                return TaskImportResponse(
                    import_id=str(existing["_id"]),
                    status=status_enum,
                    postgres_task_id=postgres_task_id,
                    error_details=existing.get("error_details"),
                    created_at=existing.get("created_at", datetime.now(UTC)),
                    updated_at=updated_at,
                )

        now = datetime.now(UTC)
        mongo_doc: dict[str, Any] = {
            "raw_payload": raw_payload,
            "status": ImportStatus.PENDING.value,
            "postgres_task_id": None,
            "error_details": None,
            "created_at": now,
            "updated_at": now,
        }
        if effective_key:
            mongo_doc["idempotency_key"] = effective_key

        try:
            insert_result = await col.insert_one(mongo_doc)
            mongo_id = insert_result.inserted_id
        except DuplicateKeyError:
            # Concurrent duplicate request with the same idempotency key
            existing = await col.find_one({"idempotency_key": effective_key})
            if existing:
                raw_status = str(existing.get("status", ImportStatus.PENDING.value))
                try:
                    status_enum = ImportStatus(raw_status)
                except ValueError:
                    status_enum = ImportStatus.FAILED
                return TaskImportResponse(
                    import_id=str(existing["_id"]),
                    status=status_enum,
                    postgres_task_id=existing.get("postgres_task_id"),
                    error_details=existing.get("error_details"),
                    created_at=existing.get("created_at", datetime.now(UTC)),
                    updated_at=existing.get("updated_at", datetime.now(UTC)),
                )
            raise

        import_id_str = str(mongo_id)

        # Stage 1: Validation and PostgreSQL Transaction (Pre-commit)
        try:
            # 1. Fallback mapping: title or summary
            raw_title = raw_payload.get("title")
            raw_summary = raw_payload.get("summary")
            effective_title = (
                raw_title
                if (isinstance(raw_title, str) and raw_title.strip())
                else (raw_summary if isinstance(raw_summary, str) else "")
            )

            mapping_dict = {
                "title": effective_title,
                "description": raw_payload.get("description"),
                "project_id": raw_payload.get("project_id"),
                "assignee_id": raw_payload.get("assignee_id"),
                "status": raw_payload.get("status", "todo"),
                "priority": raw_payload.get("priority", "medium"),
                "due_date": raw_payload.get("due_date"),
            }

            norm_payload = NormalizedTaskPayload.model_validate(mapping_dict)

            # 2. Relational integrity validations
            project = await ProjectRepository.get_by_id(db, norm_payload.project_id)
            if project is None:
                raise ValueError(f"Project {norm_payload.project_id} not found.")

            if norm_payload.assignee_id is not None:
                assignee = await UserRepository.get_by_id(db, norm_payload.assignee_id)
                if assignee is None:
                    raise ValueError(f"Assignee user {norm_payload.assignee_id} not found.")
                await verify_project_membership(
                    db, norm_payload.assignee_id, norm_payload.project_id
                )

            # 3. Create relational task and commit
            task = Task(
                title=norm_payload.title,
                description=norm_payload.description,
                status=norm_payload.status,
                priority=norm_payload.priority,
                due_date=norm_payload.due_date,
                project_id=norm_payload.project_id,
                assignee_id=norm_payload.assignee_id,
                mongo_import_id=import_id_str,
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            committed_task_id = task.id

        except Exception as exc:
            await db.rollback()
            updated_at = datetime.now(UTC)

            # Shield client from internal DB / infrastructure details
            if isinstance(exc, (ValueError, AppError)):
                error_details = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            elif isinstance(exc, ValidationError):
                error_msgs = [f"{err['loc'][-1]}: {err['msg']}" for err in exc.errors()]
                error_details = {
                    "type": "ValidationError",
                    "message": "; ".join(error_msgs),
                }
            else:
                logger.exception(
                    "Unexpected error during task import normalization for import %s: %s",
                    import_id_str,
                    exc,
                )
                error_details = {
                    "type": "InternalNormalizationError",
                    "message": "An internal error occurred during task normalization.",
                }

            await col.update_one(
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

        # Stage 2: Post-Commit Mongo Status Update
        # The PostgreSQL commit succeeded; failures here must NOT mark the task FAILED.
        updated_at = datetime.now(UTC)
        try:
            await col.update_one(
                {"_id": mongo_id},
                {
                    "$set": {
                        "status": ImportStatus.SUCCESS.value,
                        "postgres_task_id": committed_task_id,
                        "updated_at": updated_at,
                    }
                },
            )
        except Exception as mongo_exc:
            logger.error(
                "Post-commit Mongo update failed for import %s (task_id: %s): %s",
                import_id_str,
                committed_task_id,
                mongo_exc,
                exc_info=True,
            )

        return TaskImportResponse(
            import_id=import_id_str,
            status=ImportStatus.SUCCESS,
            postgres_task_id=committed_task_id,
            error_details=None,
            created_at=now,
            updated_at=updated_at,
        )

    @staticmethod
    async def import_raw_tasks_batch(
        db: AsyncSession,
        items: list[dict[str, Any]],
        collection: AsyncCollection[dict[str, Any]] | None = None,
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
    async def get_import_by_id(
        import_id: str,
        collection: AsyncCollection[dict[str, Any]] | None = None,
    ) -> TaskImportDetailResponse:
        """Retrieve the raw task import record and current status from MongoDB."""
        col = collection if collection is not None else get_raw_task_imports_collection()

        if not ObjectId.is_valid(import_id):
            raise NotFoundError(
                "Import record not found",
                details=[{"field": "import_id", "message": f"Invalid import ID: '{import_id}'"}],
            )

        doc = await col.find_one({"_id": ObjectId(import_id)})
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
