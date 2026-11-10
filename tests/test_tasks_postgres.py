"""Acceptance tests for spec 002: tasks stored in Postgres."""

from __future__ import annotations

import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from taskboard9_api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def _rows(url: str) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute("SELECT id::text, title, due_date FROM tasks ORDER BY seq").fetchall()


def _poll(fn, timeout: float = 30.0):
    """Call fn until it returns a truthy value or the timeout passes."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
        except Exception as exc:  # noqa: BLE001 - keep polling
            last = exc
        if last is not None and not isinstance(last, Exception) and last:
            return last
        time.sleep(0.5)
    return None


def _assert_503(response, elapsed: float) -> None:
    assert elapsed < 5.0
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail


def _timed(fn, *args, **kwargs):
    start = time.monotonic()
    r = fn(*args, **kwargs)
    return r, time.monotonic() - start


def test_task_survives_restart_ac_002_1():  # AC-002.1
    with _client() as c:
        r = c.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-01"})
        assert r.status_code == 201
        created = r.json()
    with _client() as c2:
        r2 = c2.get("/tasks")
        assert r2.status_code == 200
        assert created in r2.json()
        match = [t for t in r2.json() if t["id"] == created["id"]]
        assert match == [{"id": created["id"], "title": "Buy milk", "due_date": "2026-12-01"}]


def test_order_across_restart_ac_002_2():  # AC-002.2
    created = []
    with _client() as c:
        created += [c.post("/tasks", json={"title": t}).json() for t in "ABC"]
    with _client() as c2:
        created.append(c2.post("/tasks", json={"title": "D"}).json())
        r = c2.get("/tasks")
        assert r.status_code == 200
        assert r.json() == created
        assert [t["title"] for t in r.json()] == ["A", "B", "C", "D"]


def test_two_instances_share_tasks_ac_002_3():  # AC-002.3
    with _client() as first, _client() as second:
        a = first.post("/tasks", json={"title": "A", "due_date": "2026-12-01"}).json()
        b = second.post("/tasks", json={"title": "B"}).json()
        for c in (first, second):
            r = c.get("/tasks")
            assert r.status_code == 200
            assert r.json() == [a, b]


def test_db_down_at_start_returns_503_ac_002_4(pg_proxy, monkeypatch):  # AC-002.4
    monkeypatch.setenv("DATABASE_URL", pg_proxy.url)
    pg_proxy.down()
    with _client() as c:
        r, t = _timed(c.get, "/tasks")
        _assert_503(r, t)
        r, t = _timed(c.post, "/tasks", json={"title": "lost"})
        _assert_503(r, t)
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 200
        pg_proxy.up()
        listed = _poll(lambda: c.get("/tasks").status_code == 200 and c.get("/tasks"))
        assert listed is not None
        assert "lost" not in [t["title"] for t in listed.json()]


def test_db_down_after_ready_returns_503_ac_002_4(pg_proxy, monkeypatch):  # AC-002.4
    monkeypatch.setenv("DATABASE_URL", pg_proxy.url)
    with _client() as c:
        assert c.post("/tasks", json={"title": "kept"}).status_code == 201
        pg_proxy.down()
        r, t = _timed(c.get, "/tasks")
        _assert_503(r, t)
        r, t = _timed(c.post, "/tasks", json={"title": "lost"})
        _assert_503(r, t)
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 200
        pg_proxy.up()
        listed = _poll(lambda: c.get("/tasks").status_code == 200 and c.get("/tasks"))
        assert listed is not None
        assert [t["title"] for t in listed.json()] == ["kept"]


def test_database_url_unset_returns_503_ac_002_4(monkeypatch):  # AC-002.4
    monkeypatch.delenv("DATABASE_URL")
    with _client() as c:
        r, t = _timed(c.get, "/tasks")
        _assert_503(r, t)
        r, t = _timed(c.post, "/tasks", json={"title": "lost"})
        _assert_503(r, t)
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 200


def test_invalid_body_is_422_while_db_down_ac_002_4(pg_proxy, monkeypatch):  # AC-002.4
    monkeypatch.setenv("DATABASE_URL", pg_proxy.url)
    pg_proxy.down()
    with _client() as c:
        assert c.post("/tasks", json={"title": "  "}).status_code == 422
        r, t = _timed(c.get, "/tasks")
        _assert_503(r, t)


def test_recovers_without_restart_ac_002_5(pg_proxy, monkeypatch):  # AC-002.5
    monkeypatch.setenv("DATABASE_URL", pg_proxy.url)
    with _client() as c:
        assert c.post("/tasks", json={"title": "before"}).status_code == 201
        pg_proxy.down()
        assert c.get("/tasks").status_code == 503
        pg_proxy.up()
        assert _poll(lambda: c.get("/tasks").status_code == 200) is True
        r = c.post("/tasks", json={"title": "after"})
        assert r.status_code == 201
        assert [t["title"] for t in c.get("/tasks").json()] == ["before", "after"]


def test_recovers_when_started_while_down_ac_002_5(pg_proxy, monkeypatch):  # AC-002.5
    monkeypatch.setenv("DATABASE_URL", pg_proxy.url)
    pg_proxy.down()
    with _client() as c:
        assert c.get("/tasks").status_code == 503
        pg_proxy.up()
        assert _poll(lambda: c.get("/tasks").status_code == 200) is True
        assert _poll(lambda: c.post("/tasks", json={"title": "late"}).status_code == 201) is True
        assert [t["title"] for t in c.get("/tasks").json()] == ["late"]


def test_spec_001_requests_exact_contract_ac_002_6(postgres_url):  # AC-002.6
    with _client() as c:
        a = c.post("/tasks", json={"title": "  Buy milk  ", "due_date": "2026-12-01"})
        b = c.post("/tasks", json={"title": "B", "id": "mine"})
        assert (a.status_code, b.status_code) == (201, 201)
        assert set(a.json()) == {"id", "title", "due_date"}
        assert a.json()["title"] == "Buy milk" and a.json()["due_date"] == "2026-12-01"
        assert b.json()["due_date"] is None and b.json()["id"] != "mine"
        r = c.get("/tasks")
        assert r.status_code == 200
        assert r.json() == [a.json(), b.json()]
        # the rows really live in the database, in creation order
        assert [(i, t, d.isoformat() if d else None) for i, t, d in _rows(postgres_url)] == [
            (a.json()["id"], "Buy milk", "2026-12-01"),
            (b.json()["id"], "B", None),
        ]


def test_422_body_and_no_row_stored_ac_002_6(postgres_url):  # AC-002.6
    with _client() as c:
        assert c.post("/tasks", json={"title": "ok"}).status_code == 201
        r = c.post("/tasks", json={"title": "", "due_date": "nope"})
        assert r.status_code == 422
        entries = r.json()["detail"]
        assert sorted(tuple(e["loc"]) for e in entries) == [
            ("body", "due_date"),
            ("body", "title"),
        ]
        assert all({"loc", "msg", "type"} <= set(e) for e in entries)
        assert c.post("/tasks", json={"title": "a\u0000b"}).status_code == 422
        assert [t for _, t, _ in _rows(postgres_url)] == ["ok"]
        assert [t["title"] for t in c.get("/tasks").json()] == ["ok"]


@pytest.mark.parametrize("title", ["a" * 200, "é" * 200])
def test_200_code_points_stored_ac_002_6(postgres_url, title):  # AC-002.6
    with _client() as c:
        r = c.post("/tasks", json={"title": title})
        assert r.status_code == 201
        assert [t for _, t, _ in _rows(postgres_url)] == [title]
