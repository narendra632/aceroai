import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import TaskIn, TaskOut, TaskUpdate
from app.db.models import User
from app.db.session import get_db
from app.services import tasks as svc

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = svc.create_task(
        db, user.id, title=body.title, notes=body.notes, priority=body.priority, due_at=body.due_at
    )
    return TaskOut.model_validate(task)


@router.get("")
def list_tasks(
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    return [TaskOut.model_validate(t) for t in svc.list_tasks(db, user.id, status)]


@router.patch("/{task_id}")
def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = svc.update_task(db, user.id, task_id, **body.model_dump(exclude_unset=True))
    return TaskOut.model_validate(task)


@router.post("/{task_id}/complete")
def complete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    return TaskOut.model_validate(svc.complete_task(db, user.id, task_id))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    svc.delete_task(db, user.id, task_id)
