# Verification — 001 Create and list in-memory tasks

**Result:** pass
**Commit:** fa20542 · **Base:** 0a0e809 · **Trace:** 7/7 criteria named by tests (smoke: AC-001.1, AC-001.6)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_task_with_due_date_ac_001_1`, `::test_client_supplied_id_ignored_ac_001_1`; smoke `tests/test_smoke_tasks.py::test_create_then_list_ac_001_1` (`writes`) | `src/taskboard9_api/tasks/routes.py:26-31`, `src/taskboard9_api/tasks/store.py:23-27` (uuid4 id), `src/taskboard9_api/tasks/models.py:54-63` | asserts 201, non-empty string `id`, `title` "Buy milk", `due_date` "2026-12-01", and that the returned object is in the following `GET /tasks` |
| AC-001.2 | met | `tests/test_tasks.py::test_create_task_without_due_date_ac_001_2` (also `::test_title_trimmed_ac_001_2`, `::test_title_200_chars_ok_ac_001_2`) | `src/taskboard9_api/tasks/models.py:42-48` (default `None`), `routes.py:26` | asserts 201 and `due_date is None` for `{"title": "Buy milk"}` |
| AC-001.3 | met | `tests/test_tasks.py::test_invalid_title_422_ac_001_3` (10 cases) | `src/taskboard9_api/tasks/models.py:15-18,41` (`StrictStr`, strip, 1–200) | covers missing, null, number, boolean, array, object, empty, whitespace only, 201 chars and 201 chars padded with spaces; each asserts 422, an entry with `loc == ["body","title"]`, and `GET /tasks == []` |
| AC-001.4 | met | `tests/test_tasks.py::test_invalid_due_date_422_ac_001_4` (6 cases), `::test_both_invalid_one_entry_each_ac_001_4` | `src/taskboard9_api/tasks/models.py:20,44-51` | the three examples from the criterion plus `"20261201"`, a Unix timestamp and `true`; each asserts 422, `loc == ["body","due_date"]`, and `GET /tasks == []` |
| AC-001.5 | met | `tests/test_tasks.py::test_list_in_creation_order_ac_001_5` | `src/taskboard9_api/tasks/store.py:29-31` (copy under lock, append order), `routes.py:34-37` | asserts 200, list equals exactly the three POST responses in order (A, B, C), and 3 distinct ids |
| AC-001.6 | met | `tests/test_tasks.py::test_list_empty_ac_001_6`; smoke `tests/test_smoke_tasks.py::test_list_tasks_returns_array_ac_001_6` (read-only) | `src/taskboard9_api/main.py:54-61` (fresh store per app), `routes.py:34-37` | asserts 200 and `[]` on a fresh app; smoke asserts 200 and a JSON array |
| AC-001.7 | met | `tests/test_tasks.py::test_restart_empties_store_ac_001_7` | `src/taskboard9_api/main.py:58` (`app.state.task_store = InMemoryTaskStore()`), `store.py:19-21` | creates a task, then a new `create_app()` (the restart simulation the design's contract defines) returns `[]` |

## Non-goals

Only `POST /tasks` and `GET /tasks` exist (`routes.py:26,34`): no update, complete, delete or get-by-id; no persistence or cross-instance sharing (store is a per-app list, `store.py:16-31`); no query parameters, filtering or pagination; no auth; no size limit on the store. ✔

No template-owned layout changed beyond what the plan asks: `main.py` moved `/health`, `/ready`, `/ping`, `/metrics` onto `core_router` included by `create_app()` (plan t3), with paths and handlers unchanged; `tests/test_health.py`, `test_metrics.py`, `test_tracing.py` and `tests/conftest.py` are untouched. ✔

## Deviations from the plan

- Test files (`tests/test_tasks.py`, `tests/test_smoke_tasks.py`, `tests/test_task_models.py`, `tests/test_task_store.py`) are in no task's `files`: they are the tester's acceptance tests and the later unit tests. Acceptable.
- `src/taskboard9_api/tasks/__init__.py` holds a docstring only, while `design.md` (Modules table) says it re-exports `TaskCreate`, `TaskOut`. The plan (t1 notes) explicitly chose docstring only to avoid import cycles. Acceptable; design.md row is stale.
- `TaskOut.from_task` is typed against a local `Protocol` (`models.py:23-33,62`) instead of `store.Task` under `TYPE_CHECKING` (plan t1). Same intent (no runtime import of the store), structurally equivalent. Acceptable.
- Routes use an `Annotated[..., Depends(get_task_store)]` alias (`routes.py:23`) instead of a default-argument `Depends`. Style only. Acceptable.
- Smoke test `tests/test_smoke_tasks.py::test_invalid_title_rejected_ac_001_3` (line 19) carries `ac_001_3` in its name but the comment `# AC-001.1 read-only`. It checks AC-001.3 behaviour (whitespace title gets 422), not AC-001.1, so the comment mislabels it, and the trace's AC-001.1 smoke entry is carried by the `writes` test in the same file, not by this one. AC-001.3 is not a `(smoke)` criterion, and the full AC-001.3 check is the in-process test, so this extra smoke test neither proves nor weakens any criterion. It writes no data, so leaving it unmarked (it runs in every environment) is correct, and it gives staging and prod a second read-only check. Acceptable; fix the comment to `# AC-001.3` in a follow-up through the orchestrator, because coders may not edit acceptance tests.
- All tasks t1–t3 have `done: true`. ✔

## Contract

Matches `design.md`: 201 with exactly `id`, `title`, `due_date`; trimmed title stored (`test_title_trimmed_ac_001_2`); client `id` and unknown fields ignored (`extra="ignore"`, `models.py:39`); 422 uses FastAPI's default handler with `loc` `["body", field]`, one entry per field when both are invalid; `GET /tasks` oldest first; `create_app()` factory with module-level `app = create_app()` (`main.py:54-64`); logging and tracing stay at module import (`main.py:19-21`); `task_created` logs only `task_id`, never the title (`routes.py:30`). ✔

## Mutation check (report only)

14 of 16 mutants of the changed code were caught by the acceptance tests (88 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard9_api/tasks/store.py:9 True → False`
- `src/taskboard9_api/tasks/store.py:9 True → False`
