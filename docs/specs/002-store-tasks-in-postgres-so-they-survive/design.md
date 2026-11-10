# Design — 002 Store tasks in Postgres so they survive restarts and are shared by every instance

## Decisions

- **psycopg 3 + `psycopg_pool.ConnectionPool` (sync), no ORM; the service applies its own schema under an advisory
  lock.** Routes stay sync. ADR: [docs/adr/001-postgres-persistence-with-psycopg.md](../../adr/001-postgres-persistence-with-psycopg.md).
- **`create_app()` reads `DATABASE_URL` at call time** and gives each app its own `Database` (pool) and
  `PostgresTaskStore`. Two `create_app()` apps on one URL are "two instances" (AC-002.3); a new `create_app()` on the
  same URL is "a restart" (AC-002.1, AC-002.2). `DATABASE_URL` unset or empty → the app starts, task endpoints answer
  `503` (AC-002.4). The module-level `app = create_app()` stays for uvicorn.
- **The pool opens lazily on first use, not in `create_app()`**, so building an app does no I/O (tests build many;
  `TestClient` without `with` runs no lifespan). The lifespan only starts a best-effort schema warm-up in a daemon
  thread and closes the pool on shutdown; startup never waits for the database (spec "Startup").
- **No "database down" state.** Every request checks out from the pool; `check=ConnectionPool.check_connection`
  discards broken connections at checkout, and the pool re-dials on demand with back-off gaps of at most 4 s
  (`reconnect_timeout=10`), so recovery is well inside 30 s (AC-002.5). The only remembered state is "schema applied"
  (a per-store flag), which is not a health state.
- **One exception, one handler.** `db.DatabaseUnavailable` is raised for a missing URL, an unparsable URL, and every
  `psycopg.OperationalError` (covers `PoolTimeout`, `PoolClosed`, connection loss and `QueryCanceled` from
  `statement_timeout`). `create_app()` registers an exception handler mapping it to `503 {"detail": "Database unavailable"}`
  and logs `database_unavailable` (warning, `error=<exception class name>`; never the URL, it carries the password).
  Any other exception stays a `500` (a bug).
- **Ids stay `str(uuid.uuid4())`, generated in Python** and stored as `uuid`; read back as `str(row_id)`, which is the
  same lowercase hyphenated text the `POST` returned (AC-002.1, AC-002.6).
- **A title containing U+0000 is a `422` on `["body", "title"]`.** PostgreSQL `text` cannot store NUL; without this
  check such a title would be a `500`. It is a validation failure in the contract's sense (nothing stored).
- **`InMemoryTaskStore` is removed** (t3), together with its unit tests; spec 001's AC-001.7 is superseded (see
  "Spec 001 interplay").

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard9_api/db.py` | `DatabaseUnavailable`; `Database` (lazy pool from a URL, `connection()` context manager mapping driver errors, `close()`) | new (t1) |
| `src/taskboard9_api/tasks/store.py` | `Task` record; `PostgresTaskStore` (`ensure_schema`, `warm_up`, `add`, `list_all`); `InMemoryTaskStore` removed | changed (t2, t3) |
| `src/taskboard9_api/tasks/routes.py` | dependency returns `PostgresTaskStore`; handlers unchanged otherwise | changed (t3) |
| `src/taskboard9_api/tasks/models.py` | NUL check on `title` | changed (t3) |
| `src/taskboard9_api/main.py` | `create_app()`: `Database.from_env()`, store on `app.state`, lifespan (warm-up thread, close), 503 exception handler | changed (t3) |
| `pyproject.toml`, `uv.lock` | `psycopg[binary]>=3.2`, `psycopg-pool>=3.2`; dev: `testcontainers[postgres]>=4.8` | changed (t1) |
| `docs/env-vars.md` | `DATABASE_URL` | changed (t1) |

### Interfaces

```python
# db.py
class DatabaseUnavailable(Exception): ...

CONNECT_TIMEOUT_S = 2          # libpq connect_timeout
CHECKOUT_TIMEOUT_S = 2.0       # pool getconn timeout
STATEMENT_TIMEOUT_MS = 3000    # server-side, via options="-c statement_timeout=3000"

class Database:
    def __init__(self, url: str | None) -> None: ...      # no I/O; None or "" = not configured
    @classmethod
    def from_env(cls) -> "Database": ...                    # os.environ.get("DATABASE_URL")
    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[TupleRow]]: ...
        # not configured / closed      -> raise DatabaseUnavailable
        # first call: build ConnectionPool(url, min_size=1, max_size=10, timeout=CHECKOUT_TIMEOUT_S,
        #   reconnect_timeout=10.0, check=ConnectionPool.check_connection, open=False, name="taskboard9-api",
        #   kwargs={"connect_timeout": 2, "options": "-c statement_timeout=3000", "tcp_user_timeout": 3000})
        #   then pool.open(wait=False); creation guarded by a threading.Lock; psycopg.Error while building -> DatabaseUnavailable
        # with pool.connection() as conn: yield conn      (commit on normal exit, rollback on exception)
        # psycopg.OperationalError anywhere inside -> raise DatabaseUnavailable from exc
    def close(self) -> None: ...                            # idempotent; later connection() raises DatabaseUnavailable

# tasks/store.py
@dataclass(frozen=True, slots=True)
class Task:                    # unchanged
    id: str
    title: str
    due_date: date | None

SCHEMA_LOCK_KEY = 0x7461736B   # "task"

class PostgresTaskStore:
    def __init__(self, db: Database) -> None: ...
    def ensure_schema(self) -> None: ...   # once per instance (flag under a threading.Lock); raises DatabaseUnavailable
    def warm_up(self) -> None: ...         # ensure_schema(); logs and swallows DatabaseUnavailable
    def add(self, title: str, due_date: date | None) -> Task: ...  # ensure_schema(); INSERT ... RETURNING
    def list_all(self) -> list[Task]: ...  # ensure_schema(); SELECT ... ORDER BY seq

# tasks/routes.py
def get_task_store(request: Request) -> PostgresTaskStore: ...   # request.app.state.task_store

# main.py
def create_app() -> FastAPI: ...   # reads DATABASE_URL now; app.state.db, app.state.task_store
app = create_app()
```

## Contract

Binding; restated from the spec's system contract. Unchanged from spec 001 except the new `503`. All bodies are
`application/json`. No authentication. A Task object has exactly `id` (non-empty opaque string, UUID text today),
`title` (trimmed, 1 to 200 code points), `due_date` (`"YYYY-MM-DD"` or `null`).

### `GET /tasks`

- `200`: JSON array of every stored task, oldest first by creation across restarts and instances, each exactly as its
  `POST` returned it; `[]` when none (AC-002.1, AC-002.2, AC-002.3, AC-002.6).
- `503`: database unreachable, too slow, or `DATABASE_URL` not set; body exactly `{"detail": "Database unavailable"}`;
  answered within 5 s (AC-002.4).

### `POST /tasks`

Request: `{"title": <string>, "due_date": "YYYY-MM-DD" | null | absent}`; unknown fields (including `id`) ignored.

- `201`: the created Task; trimmed title; `due_date: null` when absent or `null`.
- `422`: FastAPI's standard body `{"detail": [{"loc": ["body", "title" | "due_date"], "msg": ..., "type": ...}, ...]}`,
  one entry per invalid field, nothing stored. Validation runs before the database is touched, so an invalid body is
  `422` also while the database is down. Title cases: missing, `null`, not a string, empty or whitespace-only after
  trimming, over 200 code points after trimming, or containing U+0000. Due date cases: as spec 001's design.
- `503`: as for `GET`; nothing stored (AC-002.4).

Status codes and bodies of `/health`, `/ready`, `/ping`, `/metrics` are unchanged; `/health` and `/ready` never touch
the database and answer `200` while it is down (AC-002.4).

## Data

Table `tasks`, created by `PostgresTaskStore.ensure_schema()` (t2) in one transaction:

```sql
SELECT pg_advisory_xact_lock(1952543595);           -- SCHEMA_LOCK_KEY
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       uuid NOT NULL UNIQUE,
    title    text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date date NULL
);
```

Write: `INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s) RETURNING id, title, due_date`.
Read: `SELECT id, title, due_date FROM tasks ORDER BY seq`. Parameters only, never string-built SQL.

Lifecycle: `create_app()` → no I/O. Lifespan start → daemon thread `store.warm_up()`. First task request →
`ensure_schema()` if not yet done, then the query, in the same checkout. Lifespan end → `db.close()`.

## Test harness (for the testers; `tests/conftest.py`)

The acceptance tests need a real PostgreSQL. The fixtures below live in `tests/conftest.py`, written with the
acceptance tests; coders rely on them for the store's unit tests.

- `postgres_url` (session): `TEST_DATABASE_URL` when set; otherwise start
  `testcontainers.postgres.PostgresContainer("postgres:17-alpine", driver=None)` and use `get_connection_url()`.
  Import `testcontainers` inside the fixture, so a missing package fails only the tests that use it.
- An autouse function fixture that sets `DATABASE_URL` to `postgres_url` (monkeypatch) and runs
  `DROP TABLE IF EXISTS tasks` before each test, so every test starts from an empty database with no table (the
  "empty database" of AC-002.2) and spec 001's tests in `tests/test_tasks.py` run unchanged against Postgres (AC-002.6).
- Clients are built as `with TestClient(create_app()) as c:` so the lifespan closes each app's pool; otherwise pools
  leak connections across tests.
- `pg_proxy`: a TCP proxy on `127.0.0.1:<free port>` to the database, with `.url` (the database URL pointing at the
  proxy), `.down()` (close the listener and every live connection: new connects are refused) and `.up()` (listen
  again on the same port). Used for AC-002.4 and AC-002.5, including "started while unreachable" (create the app
  while `.down()`).
- "DATABASE_URL not set" is `monkeypatch.delenv("DATABASE_URL")` before `create_app()`.

## Spec 001 interplay

AC-001.7 ("empty after restart") contradicts AC-002.1. Spec 001 must be amended to withdraw it
(`/component:spec --amend 001`) and `test_restart_empties_store_ac_001_7` in `tests/test_tasks.py` removed (its
replacement is the AC-002.1 restart test) before or with the acceptance tests of this spec, so no failing or skipped
test remains. Spec 001's `human_steps` (single replica) no longer applies once this ships.
