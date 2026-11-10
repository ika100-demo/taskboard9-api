---
spec_id: 001-create-and-list-in-memory-tasks
shape: service-python
spec_hash: d74e70d29ba7
summary: POST /tasks and GET /tasks backed by a per-process in-memory store, mounted through an app factory
tasks:
  - id: t1
    title: Add TaskCreate and TaskOut schemas with title and due_date validation
    files: [src/taskboard9_api/tasks/__init__.py, src/taskboard9_api/tasks/models.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Add Task record and thread-safe InMemoryTaskStore
    files: [src/taskboard9_api/tasks/store.py]
    covers: [AC-001.1, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: Add tasks router and create_app factory wiring the store
    files: [src/taskboard9_api/tasks/routes.py, src/taskboard9_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: false
    depends_on: [t1, t2]
human_steps:
  - Confirm the taskboard9-api entry in ika100-demo/taskboard9-gitops system.yaml runs exactly one replica with no autoscaling while tasks are held in memory (spec 001); with more, a GET after a POST can miss the task.
---

# Plan — 001 Create and list in-memory tasks

Contract, interfaces and decisions: [design.md](design.md). Levels: t1, t2 (parallel) → t3.

## t1 — Add TaskCreate and TaskOut schemas with title and due_date validation

**Files:** src/taskboard9_api/tasks/__init__.py, src/taskboard9_api/tasks/models.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4
**Goal:** The request and response models of the tasks API, so that every invalid `title` or `due_date` named in the spec fails Pydantic validation on exactly that field, and valid input yields a trimmed title and a `date | None`.

**Implementation notes:**
- `tasks/__init__.py`: package docstring only; no imports (keeps `routes` → `models`/`store` free of import cycles).
- `Title = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]`; `StrictStr` so numbers and booleans are rejected, not coerced.
- `TaskCreate(BaseModel)`: `model_config = ConfigDict(extra="ignore")`; `title: Title`; `due_date: date | None = None`.
- `@field_validator("due_date", mode="before")`: return `None` for `None`; for a `str` that fully matches `^\d{4}-\d{2}-\d{2}$`, return `date.fromisoformat(value)` (its `ValueError` for "2026-02-30" propagates); otherwise raise `ValueError("due_date must be a calendar date in YYYY-MM-DD form")`. This blocks Pydantic's lax acceptance of Unix timestamps and datetime strings.
- `TaskOut(BaseModel)`: `id: str`, `title: str`, `due_date: date | None`; `from_task(task)` classmethod taking any object with those attributes (typed against `store.Task` only under `TYPE_CHECKING`, so t1 does not import t2's module at runtime).
- No `id` field on `TaskCreate`: a client-supplied `id` is dropped by `extra="ignore"` (A5).

**Done when:** `devbox run quality` passes; the AC-001.3 and AC-001.4 acceptance tests pass once t3 mounts the route (the models alone are what makes them pass).

## t2 — Add Task record and thread-safe InMemoryTaskStore

**Files:** src/taskboard9_api/tasks/store.py
**Covers:** AC-001.1, AC-001.5, AC-001.6, AC-001.7
**Goal:** A per-instance store that assigns opaque unique ids and returns tasks in creation order; a new instance is empty, which is what a restart means.

**Implementation notes:**
- `@dataclass(frozen=True, slots=True) class Task: id: str; title: str; due_date: date | None`.
- `InMemoryTaskStore.__init__`: `self._tasks: list[Task] = []`, `self._lock = threading.Lock()`.
- `add(title, due_date) -> Task`: build `Task(id=str(uuid.uuid4()), ...)`, append under the lock, return it. No validation here (the schema owns it), no size limit (non-goal).
- `list_all() -> list[Task]`: return a copy taken under the lock, oldest first.
- No module-level store instance: the app factory owns it (design: "The store lives on the app").

**Done when:** `devbox run quality` passes; the list-order, empty-list and restart tests (AC-001.5, AC-001.6, AC-001.7) pass once t3 is in.

## t3 — Add tasks router and create_app factory wiring the store

**Files:** src/taskboard9_api/tasks/routes.py, src/taskboard9_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Expose `POST /tasks` and `GET /tasks` exactly as the design's contract states, on an app built by `create_app()` that carries its own empty store.

**Implementation notes:**
- `routes.py`: `router = APIRouter(tags=["tasks"])`; `get_task_store(request: Request) -> InMemoryTaskStore` returns `request.app.state.task_store`.
- `@router.post("/tasks", status_code=201, response_model=TaskOut)`: sync `def create_task(body: TaskCreate, store = Depends(get_task_store))` → `TaskOut.from_task(store.add(body.title, body.due_date))`.
- `@router.get("/tasks", response_model=list[TaskOut])`: sync `def list_tasks(store = Depends(get_task_store))` → `[TaskOut.from_task(t) for t in store.list_all()]`.
- Log `task_created` with `task_id` via structlog (never the title, it is user content); nothing on list.
- `main.py`: move app construction into `def create_app() -> FastAPI`: build `FastAPI(title=..., version=...)`, add `MetricsMiddleware`, register `/health`, `/ready`, `/ping`, `/metrics` (move them onto the instance, e.g. as a module-level `APIRouter` included by the factory), set `app.state.task_store = InMemoryTaskStore()`, `include_router(tasks.routes.router)`.
- Keep `configure_logging(...)` and `configure_tracing()` at module import, outside the factory (once per process); keep `app = create_app()` at module level for uvicorn and the existing `tests/conftest.py`.
- Responses keep FastAPI's default 422 handler; do not add a custom exception handler (A7).

**Done when:** all acceptance tests for AC-001.1 to AC-001.7 pass, the existing tests (`test_health.py`, `test_metrics.py`, `test_tracing.py`) still pass unchanged, and `devbox run ci` is green.
