# Design — 001 Create and list in-memory tasks

## Decisions

- **One `tasks` package with three modules** (schemas, store, router), mounted on the existing FastAPI app. It is the first domain feature, so it sets the layout later task features extend (`src/taskboard9_api/<domain>/{models,store,routes}.py`).
- **The store lives on the app, built by an app factory.** `main.py` gains `create_app() -> FastAPI`, which builds a fresh app with a fresh `InMemoryTaskStore` on `app.state.task_store`; the module-level `app = create_app()` stays, so the Dockerfile's `uvicorn taskboard9_api.main:app` and the existing tests keep working. A new app is a "restart" (AC-001.7) and gives every test an empty store (AC-001.5, AC-001.6) without a reset hook in production code. Routes reach the store through a FastAPI dependency `get_task_store(request) -> InMemoryTaskStore` that returns `request.app.state.task_store`.
- **Validation is Pydantic v2 plus FastAPI's standard 422** (A7). `title` is `StrictStr` with `strip_whitespace=True, min_length=1, max_length=200` (A4): strict so that `123` or `true` are rejected rather than coerced. `due_date` gets a `mode="before"` field validator, because Pydantic's lax `date` also accepts Unix timestamps (`1764547200`, `"1764547200"`) and FastAPI validates the parsed body in Python mode, where `Strict()` dates would reject every string. The validator accepts `None` or a `str` matching `^\d{4}-\d{2}-\d{2}$` that `date.fromisoformat` parses; anything else raises `ValueError` (AC-001.4).
- **Ids are `str(uuid.uuid4())`** (A5): opaque, unique without a counter shared across requests.
- **The store is a list guarded by a `threading.Lock`**: sync FastAPI endpoints run in a thread pool, and a list keeps creation order (A6) for free. No size limit (non-goal).
- **One replica.** Tasks are per process (non-goal: no sharing between instances); with several replicas a `GET` after a `POST` may hit another pod. The component must run with a single replica while this store is in memory; see the plan's `human_steps`.

No ADR: the in-memory store is explicitly temporary, and the app factory and module layout are feature-local conventions that a persistence spec may revisit.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard9_api/tasks/__init__.py` | package marker, re-exports `router`-free public names (`TaskCreate`, `TaskOut`) | new |
| `src/taskboard9_api/tasks/models.py` | `TaskCreate` (request, validation) and `TaskOut` (response) | new |
| `src/taskboard9_api/tasks/store.py` | `Task` record, `InMemoryTaskStore` (`add`, `list_all`) | new |
| `src/taskboard9_api/tasks/routes.py` | `APIRouter` with `POST /tasks`, `GET /tasks`; `get_task_store` dependency | new |
| `src/taskboard9_api/main.py` | `create_app()` factory: middleware, health/ready/ping/metrics, store on `app.state`, includes the tasks router; `app = create_app()` | changed |

### Interfaces

```python
# tasks/store.py
@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    due_date: date | None

class InMemoryTaskStore:
    def add(self, title: str, due_date: date | None) -> Task: ...   # assigns id, appends under lock
    def list_all(self) -> list[Task]: ...                            # copy, creation order

# tasks/models.py
Title = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

class TaskCreate(BaseModel):          # extra fields (including "id") are ignored: model_config extra="ignore"
    title: Title
    due_date: date | None = None      # @field_validator("due_date", mode="before"): None | "YYYY-MM-DD" only

class TaskOut(BaseModel):
    id: str
    title: str
    due_date: date | None             # serialised as "YYYY-MM-DD" or null
    @classmethod
    def from_task(cls, task: Task) -> "TaskOut": ...

# tasks/routes.py
router = APIRouter(tags=["tasks"])
def get_task_store(request: Request) -> InMemoryTaskStore: ...
@router.post("/tasks", status_code=201, response_model=TaskOut)
@router.get("/tasks", response_model=list[TaskOut])

# main.py
def create_app() -> FastAPI: ...
app = create_app()
```

Logging and tracing setup stay at module import in `main.py` (once per process), not in `create_app()`.

## Contract

All bodies are `application/json`. Unknown request fields, including a client-supplied `id`, are ignored (A5). A task has exactly the fields `id`, `title`, `due_date` (A8).

**Task object**

| Field | Type | Notes |
|---|---|---|
| `id` | string | server-assigned, non-empty, opaque, unique (UUID4 text today; clients must not parse it) |
| `title` | string | trimmed, 1–200 characters |
| `due_date` | string `YYYY-MM-DD` or `null` | calendar date, past dates allowed (A2, A3) |

### `POST /tasks`

Request body:

```json
{"title": "Buy milk", "due_date": "2026-12-01"}
```

- `title` (required): JSON string; leading/trailing whitespace is trimmed; after trimming 1–200 characters.
- `due_date` (optional): JSON string `YYYY-MM-DD` that is a real calendar date, or `null`, or absent.

Responses:

- `201` — the created Task object, e.g. `{"id": "3f0c…", "title": "Buy milk", "due_date": "2026-12-01"}`; with `due_date` absent or `null` in the request, `"due_date": null` (AC-001.1, AC-001.2). The stored and returned title is the trimmed one.
- `422` — validation error, nothing stored (AC-001.3, AC-001.4). Cases:
  - `title` missing, `null`, not a string (number, boolean, array, object), empty, whitespace only, or longer than 200 characters after trimming → an error entry with `loc` `["body", "title"]`.
  - `due_date` present and not `null`, and not a string, or a string that is not exactly `YYYY-MM-DD`, or not a real date (`"2026-02-30"`, `"tomorrow"`, `"2026-12-01T10:00:00"`, `"20261201"`, `1764547200`) → an error entry with `loc` `["body", "due_date"]`.
  - Both invalid → one entry per field.
  - Body not a JSON object or not valid JSON → `422` with FastAPI's standard body (no field guarantee; outside the criteria).

Error body (FastAPI's standard validation shape, A7):

```json
{
  "detail": [
    {"type": "string_too_short", "loc": ["body", "title"], "msg": "String should have at least 1 character", "input": "   ", "ctx": {"min_length": 1}}
  ]
}
```

Binding for tests: `detail` is an array; a field is "named" when at least one entry's `loc` is `["body", "<field>"]`. `type`, `msg`, `input` and `ctx` are informative and not part of the contract.

### `GET /tasks`

- `200` — JSON array of every Task object created since the process started, oldest first, each exactly as returned by its `POST` (AC-001.5); `[]` when none (AC-001.6). No query parameters, no pagination (A6).

### Restart (AC-001.7)

Tasks exist only in the process. In-process tests simulate a restart with `TestClient(create_app())`: a new app holds an empty store. The shared `client` fixture in `tests/conftest.py` wraps the module-level `app`, whose store accumulates across tests; tests asserting exact list contents (AC-001.5, AC-001.6, AC-001.7) should build their client from `create_app()`.

Smoke tests (deployed, through `SMOKE_BASE_URL`): `GET /tasks` returns `200` with an array (read-only, every environment, AC-001.6); create-then-list with a `smoke-<uuid>` title is `@pytest.mark.writes` (dev only, AC-001.1).

## Data

None persisted. In memory: `list[Task]` on `app.state.task_store`, lost on process exit.
