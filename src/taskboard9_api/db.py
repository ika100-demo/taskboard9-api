"""Postgres connection pool wrapper (spec 002).

The pool opens lazily and heals itself; every "database not usable" condition is
reported as :class:`DatabaseUnavailable`. The URL holds the password and is never
logged or put into an exception message.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool

CONNECT_TIMEOUT_S = 2
CHECKOUT_TIMEOUT_S = 2.0
STATEMENT_TIMEOUT_MS = 3000


class DatabaseUnavailable(Exception):  # noqa: N818 - name fixed by the design
    """The database is not configured, not reachable or closed."""


class Database:
    """Lazily opened, self-healing connection pool built from a database URL."""

    def __init__(self, url: str | None) -> None:
        self._url = url
        self._pool: ConnectionPool[psycopg.Connection[TupleRow]] | None = None
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def from_env(cls) -> Database:
        return cls(os.environ.get("DATABASE_URL"))

    def _get_pool(self) -> ConnectionPool[psycopg.Connection[TupleRow]]:
        with self._lock:
            if self._closed:
                raise DatabaseUnavailable("database connection is closed")
            if self._pool is None:
                if not self._url:
                    raise DatabaseUnavailable("DATABASE_URL is not set")
                try:
                    pool: ConnectionPool[psycopg.Connection[TupleRow]] = ConnectionPool(
                        self._url,
                        min_size=1,
                        max_size=10,
                        timeout=CHECKOUT_TIMEOUT_S,
                        reconnect_timeout=10.0,
                        check=ConnectionPool.check_connection,
                        open=False,
                        name="taskboard9-api",
                        kwargs={
                            "connect_timeout": CONNECT_TIMEOUT_S,
                            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
                            "tcp_user_timeout": STATEMENT_TIMEOUT_MS,
                        },
                    )
                    pool.open(wait=False)
                except psycopg.Error as exc:
                    raise DatabaseUnavailable("cannot create the database pool") from exc
                self._pool = pool
            return self._pool

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[TupleRow]]:
        """Check out a connection: commit on normal exit, roll back on an exception."""
        pool = self._get_pool()
        try:
            with pool.connection() as conn:
                yield conn
        except psycopg.OperationalError as exc:
            raise DatabaseUnavailable("database is unavailable") from exc

    def close(self) -> None:
        with self._lock:
            self._closed = True
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.close(timeout=2)
