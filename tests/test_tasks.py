"""Acceptance tests for spec 001: create and list in-memory tasks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def tclient() -> TestClient:
    """A client on a fresh app with an empty store."""
    from taskboard9_api.main import create_app

    return TestClient(create_app())


def _names(response, field: str) -> bool:
    detail = response.json().get("detail")
    return isinstance(detail, list) and any(
        isinstance(e, dict) and e.get("loc") == ["body", field] for e in detail
    )


def test_create_task_with_due_date_ac_001_1(tclient):  # AC-001.1
    r = tclient.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-01"})
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] == "2026-12-01"
    assert body in tclient.get("/tasks").json()


def test_client_supplied_id_ignored_ac_001_1(tclient):  # AC-001.1
    r = tclient.post("/tasks", json={"title": "x", "id": "mine"})
    assert r.status_code == 201
    assert r.json()["id"] != "mine"


def test_create_task_without_due_date_ac_001_2(tclient):  # AC-001.2
    r = tclient.post("/tasks", json={"title": "Buy milk"})
    assert r.status_code == 201
    assert r.json()["due_date"] is None


def test_title_trimmed_ac_001_2(tclient):  # AC-001.2
    r = tclient.post("/tasks", json={"title": "  Buy milk  ", "due_date": None})
    assert r.status_code == 201
    assert r.json()["title"] == "Buy milk"
    assert r.json()["due_date"] is None


def test_title_200_chars_ok_ac_001_2(tclient):  # AC-001.2
    assert tclient.post("/tasks", json={"title": "a" * 200}).status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"title": 5},
        {"title": True},
        {"title": ["a"]},
        {"title": {"a": 1}},
        {"title": ""},
        {"title": "   "},
        {"title": "a" * 201},
        {"title": "  " + "a" * 201 + "  "},
    ],
)
def test_invalid_title_422_ac_001_3(tclient, payload):  # AC-001.3
    r = tclient.post("/tasks", json=payload)
    assert r.status_code == 422
    assert _names(r, "title")
    assert tclient.get("/tasks").json() == []


@pytest.mark.parametrize(
    "due",
    ["2026-02-30", "tomorrow", "2026-12-01T10:00:00", "20261201", 1764547200, True],
)
def test_invalid_due_date_422_ac_001_4(tclient, due):  # AC-001.4
    r = tclient.post("/tasks", json={"title": "Buy milk", "due_date": due})
    assert r.status_code == 422
    assert _names(r, "due_date")
    assert tclient.get("/tasks").json() == []


def test_both_invalid_one_entry_each_ac_001_4(tclient):  # AC-001.4
    r = tclient.post("/tasks", json={"title": "", "due_date": "nope"})
    assert r.status_code == 422
    assert _names(r, "title") and _names(r, "due_date")


def test_list_in_creation_order_ac_001_5(tclient):  # AC-001.5
    created = [tclient.post("/tasks", json={"title": t}).json() for t in "ABC"]
    r = tclient.get("/tasks")
    assert r.status_code == 200
    assert r.json() == created
    assert [t["title"] for t in r.json()] == ["A", "B", "C"]
    assert len({t["id"] for t in r.json()}) == 3


def test_list_empty_ac_001_6(tclient):  # AC-001.6
    r = tclient.get("/tasks")
    assert r.status_code == 200
    assert r.json() == []


def test_restart_empties_store_ac_001_7(tclient):  # AC-001.7
    from taskboard9_api.main import create_app

    assert tclient.post("/tasks", json={"title": "A"}).status_code == 201
    assert len(tclient.get("/tasks").json()) == 1
    restarted = TestClient(create_app())
    assert restarted.get("/tasks").json() == []
