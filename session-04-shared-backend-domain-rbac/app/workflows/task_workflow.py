from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.models.task import Task
from app.models.enums import TaskStatus
from app.models.task_status_history import TaskStatusHistory
from app.models.activity_log import ActivityLog
from app.core.exceptions import AppError, status

class InvalidStatusTransitionError(AppError):
    code = "INVALID_STATUS_TRANSITION"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, current_status: TaskStatus, new_status: TaskStatus) -> None:
        super().__init__(
            f"Cannot transition task from {current_status.value} to {new_status.value}",
            details=[{
                "field": "status",
                "message": f"Invalid transition from {current_status.value} to {new_status.value}"
            }]
        )

class TaskWorkflow:
    ALLOWED_TRANSITIONS = {
        TaskStatus.todo: {TaskStatus.in_progress},
        TaskStatus.in_progress: {TaskStatus.todo, TaskStatus.review},
        TaskStatus.review: {TaskStatus.in_progress, TaskStatus.done},
        TaskStatus.done: {TaskStatus.review},
    }

    @classmethod
    def transition_status(
        cls, 
        db: AsyncSession, 
        task: Task, 
        new_status: TaskStatus, 
        changed_by_id: Optional[int] = None
    ) -> None:
        if new_status not in cls.ALLOWED_TRANSITIONS.get(task.status, set()):
            raise InvalidStatusTransitionError(task.status, new_status)
        
        previous_status = task.status
        task.status = new_status
        
        # Record status history
        history = TaskStatusHistory(
            task_id=task.id,
            previous_status=previous_status,
            new_status=new_status,
            changed_by_id=changed_by_id,
        )
        db.add(history)
        
        # Record activity log
        activity_log = ActivityLog(
            actor_id=changed_by_id,
            entity_type="task",
            entity_id=task.id,
            action="STATUS_CHANGED",
            details={
                "previous_status": previous_status.value,
                "new_status": new_status.value,
            },
        )
        db.add(activity_log)
