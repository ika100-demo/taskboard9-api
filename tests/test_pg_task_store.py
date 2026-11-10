"""Unit tests for PostgresTaskStore (spec 002)."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from taskboard9_api.db import Database, DatabaseUnavailable
from taskboard9_api.tasks.store import PostgresTaskStore

UNREACHABLE = "postgresql://u:p@127.0.0.1:1/db"


@pytest.fixture()
def db(postgres_url: str) -> Iterator[Database]:
    database = Database(postgres_url)
    try:
        yield database
    finally:
        database.close()


def _drop_tasks(url: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS tasks")


def test_ensure_schema_twice_is_a_noop(db: Database, postgres_url: str) -> None:
    _drop_tasks(postgres_url)
    store = PostgresTaskStore(db)
    store.ensure_schema()
    store.ensure_schema()
    assert store.list_all() == []


def test_concurrent_ensure_schema_succeeds(postgres_url: str) -> None:
    _drop_tasks(postgres_url)
    dbs = [Database(postgres_url) for _ in range(8)]
    try:
        stores = [PostgresTaskStore(d) for d in dbs]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(s.ensure_schema) for s in stores]
            for f in futures:
                f.result(timeout=30)
    finally:
        for d in dbs:
            d.close()


def test_round_trip_keeps_order_and_fields(postgres_url: str) -> None:
    _drop_tasks(postgres_url)
    db1, db2 = Database(postgres_url), Database(postgres_url)
    try:
        first, second = PostgresTaskStore(db1), PostgresTaskStore(db2)
        a = first.add("A", date(2026, 12, 1))
        b = second.add("B", None)
        c = first.add("C", date(2027, 1, 2))
        assert [t.title for t in (a, b, c)] == ["A", "B", "C"]
        assert a.due_date == date(2026, 12, 1)
        assert b.due_date is None
        assert first.list_all() == [a, b, c]
        assert second.list_all() == [a, b, c]
    finally:
        db1.close()
        db2.close()


def test_unreachable_database() -> None:
    db = Database(UNREACHABLE)
    try:
        store = PostgresTaskStore(db)
        store.warm_up()
        with pytest.raises(DatabaseUnavailable):
            store.add("x", None)
    finally:
        db.close()
