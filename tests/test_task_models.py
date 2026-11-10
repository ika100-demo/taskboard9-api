"""Unit tests for the task request and response models."""

from datetime import date

import pytest
from pydantic import ValidationError

from taskboard9_api.tasks.models import TaskCreate, TaskOut
from taskboard9_api.tasks.store import Task


def test_due_date_defaults_to_none():
    assert TaskCreate(title="a").due_date is None


def test_due_date_none_passes_through():
    assert TaskCreate(title="a", due_date=None).due_date is None


def test_due_date_parsed_from_iso_string():
    assert TaskCreate(title="a", due_date="2030-05-06").due_date == date(2030, 5, 6)


def test_leap_day_is_valid():
    assert TaskCreate(title="a", due_date="2028-02-29").due_date == date(2028, 2, 29)


@pytest.mark.parametrize(
    "bad",
    ["2027-02-29", "2030-13-01", "2030-1-1", "2030-01-01T00:00", "", 20300101, " 2030-01-01"],
)
def test_bad_due_date_rejected(bad):
    with pytest.raises(ValidationError):
        TaskCreate(title="a", due_date=bad)


def test_title_of_exactly_200_chars_after_trimming_is_valid():
    title = TaskCreate(title="  " + "x" * 200 + "  ").title
    assert title == "x" * 200


def test_title_of_201_chars_rejected():
    with pytest.raises(ValidationError):
        TaskCreate(title="x" * 201)


@pytest.mark.parametrize("bad", ["", "   ", None, 5])
def test_bad_title_rejected(bad):
    with pytest.raises(ValidationError):
        TaskCreate(title=bad)


def test_title_is_trimmed():
    assert TaskCreate(title="  hi  ").title == "hi"


def test_unknown_fields_including_id_are_ignored():
    model = TaskCreate.model_validate({"title": "a", "id": "mine", "extra": 1})
    assert not hasattr(model, "id")
    assert not hasattr(model, "extra")


def test_task_out_from_task():
    task = Task(id="abc", title="t", due_date=date(2030, 1, 1))
    out = TaskOut.from_task(task)
    assert (out.id, out.title, out.due_date) == ("abc", "t", date(2030, 1, 1))


def test_task_out_from_task_without_due_date():
    out = TaskOut.from_task(Task(id="abc", title="t", due_date=None))
    assert out.due_date is None
    assert out.model_dump(mode="json") == {"id": "abc", "title": "t", "due_date": None}
