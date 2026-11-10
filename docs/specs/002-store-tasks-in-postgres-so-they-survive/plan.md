---
spec_id: 002-store-tasks-in-postgres-so-they-survive
shape: service-python
spec_hash: a496af87e6c8
summary: Tasks stored in Postgres via psycopg 3 and a lazy sync pool, schema self-applied under an advisory lock, 503 when the database is unusable
tasks:
  - id: t1
    title: Add psycopg dependencies and the Database pool wrapper
    files: [pyproject.toml, uv.lock, src/taskboard9_api/db.py, docs/env-vars.md, tests/test_db.py]
    covers: [AC-002.4, AC-002.5]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Add PostgresTaskStore with the self-applied tasks schema
    files: [src/taskboard9_api/tasks/store.py, tests/test_pg_task_store.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.6]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: Wire the Postgres store into create_app with lifespan and 503 handling
    files: [src/taskboard9_api/main.py, src/taskboard9_api/tasks/routes.py, src/taskboard9_api/tasks/models.py, src/taskboard9_api/tasks/__init__.py, src/taskboard9_api/tasks/store.py, tests/test_task_store.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: false
    depends_on: [t2]
---

# Plan — 002 Store tasks in Postgres so they survive restarts and are shared by every instance

Contract, interfaces, schema and the test harness: [design.md](design.md); decision record:
[ADR-001](../../adr/001-postgres-persistence-with-psycopg.md). Levels: t1 → t2 → t3.

Prerequisite outside this plan: spec 001 amended to withdraw AC-001.7 and its test removed with this spec's acceptance
tests (design "Spec 001 interplay"). The `tests/conftest.py` database fixtures belong to the acceptance tests (design
"Test harness"); coders use them and do not edit `tests/conftest.py` or `tests/test_tasks.py`.

No gitops task: the spec states the system plan already wires the `postgres` resource (`DATABASE_URL`, PG*) into this
component.

## t1 — Add psycopg dependencies and the Database pool wrapper

**Files:** pyproject.toml, uv.lock, src/taskboard9_api/db.py, docs/env-vars.md, tests/test_db.py
**Covers:** AC-002.4, AC-002.5
**Goal:** A `Database` object that turns `DATABASE_URL` into a lazily opened, self-healing connection pool with the
spec's timeouts, and reports every "database not usable" condition as `DatabaseUnavailable`.

**Implementation notes:**
- `pyproject.toml`: add `psycopg[binary]>=3.2` and `psycopg-pool>=3.2` to `dependencies`, `testcontainers[postgres]>=4.8`
  to the `dev` extra. Do not call `uv` directly: the devbox init hook (`uv sync --all-extras`) re-locks on the next
  `devbox run ...`; commit the resulting `uv.lock`.
- `db.py` exactly as design "Interfaces": constants, `DatabaseUnavailable`, `Database(url)`, `from_env()`,
  `connection()`, `close()`.
- Pool built on first `connection()` under a `threading.Lock`: `ConnectionPool(url, min_size=1, max_size=10,
  timeout=2.0, reconnect_timeout=10.0, check=ConnectionPool.check_connection, open=False, name="taskboard9-api",
  kwargs={"connect_timeout": 2, "options": "-c statement_timeout=3000", "tcp_user_timeout": 3000})`, then
  `open(wait=False)` (never blocks on an unreachable database).
- `None`/empty URL, a closed `Database`, `psycopg.Error` while building the pool, and `psycopg.OperationalError` raised
  inside `connection()` (checkout or the caller's statements) → `raise DatabaseUnavailable(...) from exc`. Other
  exceptions propagate unchanged.
- `close()`: idempotent; closes the pool if built (`pool.close(timeout=2)`), marks the object closed.
- Never log or put the URL into an exception message (it holds the password).
- `docs/env-vars.md`: new "Database" section: `DATABASE_URL` (unset: the service starts, task endpoints answer 503;
  provided by the system's postgres resource); the PG* variables are libpq defaults and not required.
- `tests/test_db.py` (unit): an unset URL raises `DatabaseUnavailable`; an unreachable URL
  (`postgresql://u:p@127.0.0.1:1/db`) raises it within 5 s and the message does not contain the password; with
  `postgres_url`, `SELECT 1` works; after `close()` `connection()` raises; `close()` twice is fine.

**Done when:** `devbox run quality` and `devbox run test` pass (existing tests unchanged); `tests/test_db.py` passes.

## t2 — Add PostgresTaskStore with the self-applied tasks schema

**Files:** src/taskboard9_api/tasks/store.py, tests/test_pg_task_store.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.6
**Goal:** A store with the same `add`/`list_all` interface as today, backed by the `tasks` table, which creates that
table itself safely when several instances start at once.

**Implementation notes:**
- Add `SCHEMA_LOCK_KEY` and `PostgresTaskStore(db: Database)` next to `Task`; keep `InMemoryTaskStore` for now (t3
  removes it), so `main.py` keeps importing until the switch.
- `ensure_schema()`: if the flag is set, return; else under a `threading.Lock`, in one `db.connection()` run
  `SELECT pg_advisory_xact_lock(%s)` and the `CREATE TABLE IF NOT EXISTS` of design "Data"; set the flag only after
  the transaction committed.
- `warm_up()`: `ensure_schema()`; on `DatabaseUnavailable` log `database_warmup_failed` (info, error class) and return.
- `add(title, due_date)`: `ensure_schema()`; `uuid.uuid4()`; `INSERT ... RETURNING id, title, due_date` in one
  `db.connection()`; return `Task(id=str(row[0]), title=row[1], due_date=row[2])`.
- `list_all()`: `ensure_schema()`; `SELECT id, title, due_date FROM tasks ORDER BY seq`; map rows the same way.
- SQL as module constants with `%s` parameters only (bandit, injection).
- `DatabaseUnavailable` from `db` propagates unchanged; no catching in `add`/`list_all`.
- `tests/test_pg_task_store.py` (unit, uses `postgres_url`): ensure_schema twice is a no-op; eight threads with
  eight stores calling `ensure_schema()` at once all succeed; add/list round trip keeps order and fields across two
  store instances on one database; `add` on an unreachable `Database` raises `DatabaseUnavailable` and `warm_up` does not.

**Done when:** `devbox run quality` passes; `tests/test_pg_task_store.py` and all existing tests pass.

## t3 — Wire the Postgres store into create_app with lifespan and 503 handling

**Files:** src/taskboard9_api/main.py, src/taskboard9_api/tasks/routes.py, src/taskboard9_api/tasks/models.py, src/taskboard9_api/tasks/__init__.py, src/taskboard9_api/tasks/store.py, tests/test_task_store.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6
**Goal:** Every app built by `create_app()` serves `/tasks` from Postgres per the design's contract, answers `503`
for an unusable database, and starts and stays ready without one.

**Implementation notes:**
- `main.py` `create_app()`: `db = Database.from_env()`, `app.state.db = db`,
  `app.state.task_store = PostgresTaskStore(db)`; keep middleware, core router, tasks router, module-level `app`.
- Lifespan (`FastAPI(lifespan=...)`): on start, `threading.Thread(target=store.warm_up, daemon=True,
  name="db-warmup").start()`; on shutdown, `db.close()`. Nothing in startup waits for the database.
- `app.add_exception_handler(DatabaseUnavailable, ...)` → `JSONResponse(503, {"detail": "Database unavailable"})`;
  log `database_unavailable` (warning, `error=type(exc.__cause__ or exc).__name__`, path).
- `/health` and `/ready` stay untouched (no database call).
- `routes.py`: `get_task_store` / `StoreDep` typed as `PostgresTaskStore`; handlers otherwise unchanged.
- `models.py`: title rejects U+0000 (an `AfterValidator` or `field_validator("title")` raising `ValueError`), so the
  error `loc` is `["body", "title"]`.
- `store.py`: delete `InMemoryTaskStore`; `PostgresTaskStore` and `Task` stay as t2 left them.
- `tasks/__init__.py`: docstring says "Postgres-backed store" instead of "in-memory store".
- `tests/test_task_store.py`: drop the `InMemoryTaskStore` tests; keep wiring tests (each `create_app()` has its own
  `PostgresTaskStore` and `Database`; `get_task_store` returns the app's store; `create_app()` with no `DATABASE_URL`
  builds and `/health`, `/ready` answer 200 while `/tasks` answers 503); add a NUL-title 422 test.

**Done when:** all acceptance tests for AC-002.1 to AC-002.6 and spec 001's remaining acceptance tests pass, the
existing health/metrics/tracing tests pass unchanged, and `devbox run ci` is green.
