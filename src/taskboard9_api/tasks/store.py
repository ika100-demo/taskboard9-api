"""Task storage: the Postgres-backed store (spec 002)."""

import threading
import uuid
from dataclasses import dataclass
from datetime import date

import structlog

from taskboard9_api.db import Database, DatabaseUnavailable

SCHEMA_LOCK_KEY = 0x7461736B

_LOCK_SQL = "SELECT pg_advisory_xact_lock(%s)"
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       uuid NOT NULL UNIQUE,
    title    text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date date NULL
)
"""
_INSERT_SQL = (
    "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s) RETURNING id, title, due_date"
)
_SELECT_SQL = "SELECT id, title, due_date FROM tasks ORDER BY seq"

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    due_date: date | None


class PostgresTaskStore:
    """Tasks in the ``tasks`` table, which the store creates itself on first use."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._db.connection() as conn:
                conn.execute(_LOCK_SQL, (SCHEMA_LOCK_KEY,))
                conn.execute(_CREATE_TABLE_SQL)
            self._schema_ready = True

    def warm_up(self) -> None:
        try:
            self.ensure_schema()
        except DatabaseUnavailable as exc:
            logger.info("database_warmup_failed", error=type(exc).__name__)

    def add(self, title: str, due_date: date | None) -> Task:
        self.ensure_schema()
        with self._db.connection() as conn:
            row = conn.execute(_INSERT_SQL, (uuid.uuid4(), title, due_date)).fetchone()
        if row is None:  # pragma: no cover - INSERT ... RETURNING always yields a row
            raise DatabaseUnavailable("insert returned no row")
        return Task(id=str(row[0]), title=row[1], due_date=row[2])

    def list_all(self) -> list[Task]:
        self.ensure_schema()
        with self._db.connection() as conn:
            rows = conn.execute(_SELECT_SQL).fetchall()
        return [Task(id=str(r[0]), title=r[1], due_date=r[2]) for r in rows]
