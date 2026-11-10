"""Request and response models of the tasks API."""

import re
from datetime import date
from typing import Annotated, Any, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    field_validator,
)

Title = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _TaskLike(Protocol):
    """Any object carrying the fields of a stored task."""

    @property
    def id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def due_date(self) -> date | None: ...


class TaskCreate(BaseModel):
    """Body of ``POST /tasks``; unknown fields (including ``id``) are ignored."""

    model_config = ConfigDict(extra="ignore")

    title: Title
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _parse_due_date(cls, value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, str) and _ISO_DATE.fullmatch(value):
            return date.fromisoformat(value)
        raise ValueError("due_date must be a calendar date in YYYY-MM-DD form")


class TaskOut(BaseModel):
    """A task as returned by the API."""

    id: str
    title: str
    due_date: date | None

    @classmethod
    def from_task(cls, task: _TaskLike) -> "TaskOut":
        return cls(id=task.id, title=task.title, due_date=task.due_date)
