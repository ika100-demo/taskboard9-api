"""Unit tests for the Database pool wrapper."""

from __future__ import annotations

import time

import pytest

from taskboard9_api.db import Database, DatabaseUnavailable


def test_unset_url_is_unavailable() -> None:
    for url in (None, ""):
        with pytest.raises(DatabaseUnavailable), Database(url).connection():
            pass


def test_unreachable_url_is_unavailable_without_password() -> None:
    db = Database("postgresql://u:secretpw@127.0.0.1:1/db")
    start = time.monotonic()
    try:
        with pytest.raises(DatabaseUnavailable) as info, db.connection():
            pass
    finally:
        db.close()
    assert time.monotonic() - start < 5
    assert "secretpw" not in str(info.value)


def test_select_one(postgres_url: str) -> None:
    db = Database(postgres_url)
    try:
        with db.connection() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
    finally:
        db.close()


def test_closed_database_raises_and_close_is_idempotent(postgres_url: str) -> None:
    db = Database(postgres_url)
    with db.connection() as conn:
        conn.execute("SELECT 1")
    db.close()
    db.close()
    with pytest.raises(DatabaseUnavailable), db.connection():
        pass
