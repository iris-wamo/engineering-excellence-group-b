from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class TaskRepository:
    @staticmethod
    def create(db: Session, task: Task) -> Task:
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def get_by_id(db: Session, task_id: int) -> Task | None:
        return db.get(Task, task_id)

    @staticmethod
    def update(db: Session, task: Task) -> Task:
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def get_all(
        db: Session,
        *,
        page: int,
        page_size: int,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        project_id: int | None,
        assignee_id: int | None,
    ) -> tuple[list[Task], int]:
        filters = []

        if status is not None:
            filters.append(Task.status == status)

        if priority is not None:
            filters.append(Task.priority == priority)

        if project_id is not None:
            filters.append(Task.project_id == project_id)

        if assignee_id is not None:
            filters.append(Task.assignee_id == assignee_id)

        total = db.scalar(select(func.count()).select_from(Task).where(*filters)) or 0

        tasks = db.scalars(
            select(Task)
            .where(*filters)
            .order_by(Task.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        return list(tasks), total
