"""HTTP routes of the tasks API."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request

from .models import TaskCreate, TaskOut
from .store import PostgresTaskStore

router = APIRouter(tags=["tasks"])
log = structlog.get_logger()


def get_task_store(request: Request) -> PostgresTaskStore:
    """Return the store carried by the running app."""
    store: PostgresTaskStore = request.app.state.task_store
    return store


StoreDep = Annotated[PostgresTaskStore, Depends(get_task_store)]


@router.post("/tasks", status_code=201, response_model=TaskOut)
def create_task(body: TaskCreate, store: StoreDep) -> TaskOut:
    """Create a task."""
    task = store.add(body.title, body.due_date)
    log.info("task_created", task_id=task.id)
    return TaskOut.from_task(task)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(store: StoreDep) -> list[TaskOut]:
    """List all tasks, oldest first."""
    return [TaskOut.from_task(t) for t in store.list_all()]
