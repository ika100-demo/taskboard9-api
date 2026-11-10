"""In-memory task storage."""

import threading
import uuid
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    due_date: date | None


class InMemoryTaskStore:
    """Thread-safe, per-instance task list; a new instance is empty."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: date | None) -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, due_date=due_date)
        with self._lock:
            self._tasks.append(task)
        return task

    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks)
