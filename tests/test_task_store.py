"""Unit tests for the in-memory task store and the app wiring."""

from datetime import date
from threading import Thread

from fastapi import FastAPI
from fastapi.testclient import TestClient

from taskboard9_api.main import create_app
from taskboard9_api.tasks.routes import get_task_store
from taskboard9_api.tasks.store import InMemoryTaskStore


def test_new_store_is_empty():
    assert InMemoryTaskStore().list_all() == []


def test_add_returns_task_with_given_fields():
    task = InMemoryTaskStore().add("write", date(2030, 1, 2))
    assert task.title == "write"
    assert task.due_date == date(2030, 1, 2)


def test_add_assigns_distinct_non_empty_ids():
    store = InMemoryTaskStore()
    ids = [store.add(f"t{i}", None).id for i in range(50)]
    assert all(isinstance(i, str) and i for i in ids)
    assert len(set(ids)) == 50


def test_list_all_keeps_creation_order():
    store = InMemoryTaskStore()
    added = [store.add(t, None) for t in ("a", "b", "c")]
    assert store.list_all() == added


def test_list_all_returns_a_copy():
    store = InMemoryTaskStore()
    store.add("a", None)
    snapshot = store.list_all()
    snapshot.clear()
    assert len(store.list_all()) == 1


def test_stores_are_independent():
    first, second = InMemoryTaskStore(), InMemoryTaskStore()
    first.add("a", None)
    assert second.list_all() == []


def test_concurrent_adds_lose_nothing():
    store = InMemoryTaskStore()

    def work() -> None:
        for _ in range(200):
            store.add("x", None)

    threads = [Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    tasks = store.list_all()
    assert len(tasks) == 1600
    assert len({t.id for t in tasks}) == 1600


def test_create_app_gives_each_app_its_own_store():
    first, second = create_app(), create_app()
    assert isinstance(first, FastAPI)
    assert isinstance(first.state.task_store, InMemoryTaskStore)
    assert first.state.task_store is not second.state.task_store


def test_apps_do_not_share_tasks():
    with TestClient(create_app()) as a, TestClient(create_app()) as b:
        assert a.post("/tasks", json={"title": "only in a"}).status_code == 201
        assert len(a.get("/tasks").json()) == 1
        assert b.get("/tasks").json() == []


def test_get_task_store_returns_the_app_store():
    app = create_app()

    class _Req:
        pass

    req = _Req()
    req.app = app  # type: ignore[attr-defined]
    assert get_task_store(req) is app.state.task_store  # type: ignore[arg-type]
