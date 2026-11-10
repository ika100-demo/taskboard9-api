"""Shared pytest fixtures."""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from taskboard9_api.main import app

# Modules that run against Postgres (spec 002); other tests never touch the database.
_DB_MODULES = {"test_tasks", "test_tasks_postgres"}


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Database URL: TEST_DATABASE_URL, else a throwaway postgres container."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver=None) as pg:
        yield pg.get_connection_url()


@pytest.fixture(autouse=True)
def _database(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point DATABASE_URL at the test database, empty and without a table."""
    if request.module.__name__.rsplit(".", 1)[-1] not in _DB_MODULES:
        return
    url = request.getfixturevalue("postgres_url")
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS tasks")
    monkeypatch.setenv("DATABASE_URL", url)


class PgProxy:
    """A TCP proxy to the database that can be taken down and brought up again."""

    def __init__(self, target_host: str, target_port: int, url: str) -> None:
        self._target = (target_host, target_port)
        self._lock = threading.Lock()
        self._conns: list[socket.socket] = []
        self._listener: socket.socket | None = None
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        parts = urlsplit(url)
        auth = parts.netloc.rpartition("@")[0]
        netloc = f"{auth}@" if auth else ""
        self.url = urlunsplit(parts._replace(netloc=f"{netloc}127.0.0.1:{self.port}"))

    def up(self) -> None:
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen(64)
        self._listener = listener
        threading.Thread(target=self._accept, args=(listener,), daemon=True).start()

    def down(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            # On Linux close() alone does not wake a thread blocked in accept(),
            # so the socket would keep accepting.
            try:
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        with self._lock:
            conns, self._conns = self._conns, []
        for c in conns:
            for fn in (lambda s: s.shutdown(socket.SHUT_RDWR), lambda s: s.close()):
                try:
                    fn(c)
                except OSError:
                    pass

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                src, _ = listener.accept()
            except OSError:
                return
            try:
                dst = socket.create_connection(self._target, timeout=5)
            except OSError:
                src.close()
                continue
            with self._lock:
                self._conns += [src, dst]
            threading.Thread(target=self._pipe, args=(src, dst), daemon=True).start()
            threading.Thread(target=self._pipe, args=(dst, src), daemon=True).start()

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket) -> None:
        try:
            while data := a.recv(65536):
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass


@pytest.fixture()
def pg_proxy(postgres_url: str) -> Iterator[PgProxy]:
    """A proxy in front of the test database, listening (up) when handed out."""
    parts = urlsplit(postgres_url)
    proxy = PgProxy(parts.hostname or "127.0.0.1", parts.port or 5432, postgres_url)
    proxy.up()
    try:
        yield proxy
    finally:
        proxy.down()
