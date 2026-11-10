"""Unit tests for the app wiring of the Postgres task store."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from taskboard9_api.db import Database
from taskboard9_api.main import create_app
from taskboard9_api.tasks.routes import get_task_store
from taskboard9_api.tasks.store import PostgresTaskStore


def test_create_app_gives_each_app_its_own_store_and_database():
    first, second = create_app(), create_app()
    assert isinstance(first, FastAPI)
    assert isinstance(first.state.task_store, PostgresTaskStore)
    assert isinstance(first.state.db, Database)
    assert first.state.task_store is not second.state.task_store
    assert first.state.db is not second.state.db


def test_get_task_store_returns_the_app_store():
    app = create_app()

    class _Req:
        pass

    req = _Req()
    req.app = app  # type: ignore[attr-defined]
    assert get_task_store(req) is app.state.task_store  # type: ignore[arg-type]


def test_app_without_database_url_is_healthy_but_tasks_are_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 200
        resp = c.get("/tasks")
        assert resp.status_code == 503
        assert resp.json() == {"detail": "Database unavailable"}


def test_nul_in_title_is_422_on_body_title():
    with TestClient(create_app()) as c:
        resp = c.post("/tasks", json={"title": "a\u0000b"})
        assert resp.status_code == 422
        assert resp.json()["detail"][0]["loc"] == ["body", "title"]
