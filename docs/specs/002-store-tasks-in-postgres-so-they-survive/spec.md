---
spec_id: 002-store-tasks-in-postgres-so-they-survive
title: Store tasks in Postgres so they survive restarts and are shared by every instance
status: building
priority: P1
shape: service-python
parent: ika100-demo/taskboard9-gitops:001-persistent-tasks-in-postgres-with-a-web
---

# 002 — Store tasks in Postgres so they survive restarts and are shared by every instance

## Problem

The Task API keeps tasks only in its own memory, so every restart or redeploy of the API wipes the board, and the API cannot run more than one instance. The only way to see or create tasks is to call the API directly; taskboard9 has a web UI component but it has no task features yet. Storing tasks in a Postgres database and giving the web UI a task list with a create form turns taskboard9 into a board people can actually use and rely on.

## System context

Slice of the system plan `001-persistent-tasks-in-postgres-with-a-web` in `ika100-demo/taskboard9-gitops` for `taskboard9-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given a task created with `POST /tasks` `{"title": "Buy milk", "due_date": "2026-12-01"}`, when every instance of the API is stopped and started again, then `GET /tasks` still contains that task with the same `id`, `title` and `due_date`.
- **AC-001.2** Given tasks "A", "B" and "C" were created in that order and the API was then restarted, when a task "D" is created and a client sends `GET /tasks`, then the response lists "A", "B", "C", "D" in that order.
- **AC-001.3** Given the database is unreachable, when a client sends `GET /tasks` or a valid `POST /tasks`, then the response is 503 with a JSON body holding a `detail` message and no task is created; and when the database is reachable again, both requests succeed within 30 seconds without the API being restarted.

### Contract

The provider is `taskboard9-api`; the consumer is `taskboard9-web` (server side only). Base URL: the env var
`API_URL` of the web (`http://taskboard9-api` in the cluster, `http://localhost:8080` locally); no trailing slash,
paths are appended as written. All bodies are `application/json; charset=utf-8`. No authentication (A9).

**Task object** (unchanged from taskboard9-api spec 001)

| Field | Type | Notes |
|---|---|---|
| `id` | string | server-assigned, non-empty, opaque, unique; clients never parse it (UUID text today) |
| `title` | string | stored trimmed, 1 to 200 characters (Unicode code points) |
| `due_date` | string `YYYY-MM-DD` or `null` | calendar date, no time or zone; past dates allowed |

A task has exactly these three fields. Creation order is kept by the API internally and is not exposed.

### `GET /tasks`

- `200`: JSON array of every stored task, oldest first by creation (across restarts and instances), each exactly
  as returned by its `POST`; `[]` when there is none. No query parameters, no pagination.
- `503`: the database is unreachable or not configured; body `{"detail": "Database unavailable"}`.

### `POST /tasks`

Request body: `{"title": "Buy milk", "due_date": "2026-12-01"}`.

- `title` (required): JSON string; trimmed; 1 to 200 code points after trimming.
- `due_date` (optional): `YYYY-MM-DD` string of a real calendar date, or `null`, or absent. Unknown fields,
  including `id`, are ignored.

Responses:

- `201`: the created Task object; the returned title is the trimmed one; `due_date` is `null` when it was absent
  or `null`.
- `422`: validation failure, nothing stored; FastAPI's standard body
  `{"detail": [{"loc": ["body", "title"], "msg": "...", "type": "..."}]}`, one entry per invalid field
  (`loc` `["body", "title"]` or `["body", "due_date"]`).
- `503`: the database is unreachable or not configured; nothing stored; body `{"detail": "Database unavailable"}`.

**What the web sends.** The web trims the title and checks it before sending: empty after trimming gives
"Title is required.", more than 200 code points after trimming (`[...title].length`, not `title.length`) gives
"Title must be at most 200 characters."; then nothing is sent. The due date comes from an `<input type="date">`
whose value is already `YYYY-MM-DD`; an empty field is sent as `"due_date": null`. The body is exactly
`{"title": <trimmed title>, "due_date": <date or null>}`.

**What the web shows** (A6, A8): the heading "Tasks" (level 1); each entry shows its title and its `due_date`
verbatim (`YYYY-MM-DD`), or "No due date" when it is `null`; entries in the order of the array; "No tasks yet."
when the array is empty; "Tasks could not be loaded. Please try again later." when the list cannot be loaded;
"The task could not be saved. Please try again." when a create fails; the field messages above, shown at the
title field. The form fields are labelled "Title" and "Due date", the button is "Add task". After a 201 the
returned task (not the typed values) is appended as the last entry and both fields are cleared. When the list
failed to load, the form stays usable; a successful create then clears the fields and the load error stays until
the page is reloaded.

**Web-internal route** (not called by other repos, stated so both sides agree on the behaviour):
`POST /api/tasks` on the web takes the same body as the API, answers `201` with the API's Task object, `422`
with `{"field": "title", "message": "<one of the two field messages>"}` when its own check fails, and `502` with
`{"message": "The task could not be saved. Please try again."}` for every API failure.

**Database (inside taskboard9-api only).** Table `tasks`: `seq bigint generated always as identity primary key`,
`id uuid not null unique`, `title text not null` (check 1 to 200 characters), `due_date date null`. `GET /tasks`
orders by `seq`. The API creates the table itself, idempotently and safely with several instances starting at
once (`CREATE TABLE IF NOT EXISTS` under an advisory lock), at startup when the database is reachable and
otherwise before the first request that reaches it. The database starts empty (A3).

### Errors

- Error bodies are JSON with a `detail` key: an array of field entries for `422` (FastAPI's shape), a string for
  `503`. The `detail` text is informative; no caller matches on it.
- The web never shows the API's error text to a person; it shows only the texts listed above.
- `GET /tasks`: anything other than `200` with a JSON array (any 4xx or 5xx, a body that is not a JSON array,
  a connection error, a timeout) is a load failure: the page shows "Tasks could not be loaded. Please try
  again later." and never "No tasks yet.". Entries with missing fields are not repaired; the whole load fails.
- `POST /tasks`: anything other than `201` with a Task object (including `422`, which the web's own check
  should make impossible, any other 4xx, any 5xx, a connection error, a timeout) is a save failure: the page
  shows "The task could not be saved. Please try again.", keeps the entered values and leaves the list unchanged.
  The web does not retry a `POST` by itself, so a lost answer can never create the task twice.
- The API answers `500` only for a bug; a database that is down, refusing connections, not configured, or too
  slow (over its timeouts below) is always `503`, with nothing stored.

### Timeouts

- **Web to API** (`GET /tasks`, `POST /tasks`, server side): 8 seconds each (`AbortSignal.timeout(8000)`); on
  expiry the web treats the call as failed (load or save failure above). No retries.
- **Browser to web** (`POST /api/tasks`): the client aborts after 10 seconds and shows the save failure; the
  submit button is disabled while a request is in flight so one press sends one request.
- **API to Postgres**: connect timeout 2 seconds, pool checkout timeout 2 seconds, `statement_timeout` 3 seconds;
  so the API answers `503` within 5 seconds when the database is down or slow, before the web's 8 seconds run out.
- **Recovery**: the API keeps no "database down" state; every request tries the pool, which replaces broken
  connections, so requests succeed again as soon as the database accepts connections, well within the 30 seconds
  of AC-001.3. Liveness (`/health`) and readiness (`/ready`) never touch the database.
- **Startup**: the API starts and becomes ready even when the database is unreachable (task endpoints answer
  `503` until it is reachable); the web starts without the API (the page shows the load failure).

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Supersedes AC-001.7 of this repo's spec 001 ("empty after restart"): withdraw it there with
`/component:spec --amend 001` and replace its test; do not leave a failing or skipped test behind.
Config: DATABASE_URL (plus PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD) comes from the system's
postgres resource (Secret taskboard9-postgres-app). Suggested stack: psycopg 3 with psycopg_pool (sync,
the routes are sync), schema applied by the service itself with CREATE TABLE IF NOT EXISTS under
pg_advisory_lock, never blocking startup. Tests need a real PostgreSQL (a devbox recipe or
testcontainers); keep an in-process restart test via TestClient(create_app()) on the same database.

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given a task created with POST /tasks {"title": "Buy milk", "due_date": "2026-12-01"} (201), when every API process is stopped and started again against the same database, then GET /tasks answers 200 and contains a task with the same id, title "Buy milk" and due_date "2026-12-01" (system AC-001.1)
- **AC-002.2** Given an empty database, tasks "A", "B" and "C" created in that order and the API then restarted, when task "D" is created and a client sends GET /tasks, then the response is 200 with exactly A, B, C, D in that order, each with id, title and due_date as returned by its POST (system AC-001.2)
- **AC-002.3** Given two API instances using the same database, when task "A" is created through the first and then task "B" through the second, then GET /tasks on either instance lists A before B with identical fields (system AC-001.1, AC-001.2)
- **AC-002.4** Given the database is unreachable (or DATABASE_URL is not set), when a client sends GET /tasks or a valid POST /tasks, then the response arrives within 5 seconds with status 503 and a JSON body {"detail": <non-empty string>}, GET /health and GET /ready still answer 200, and once the database is reachable GET /tasks does not contain the task of that POST (system AC-001.3)
- **AC-002.5** Given the database was unreachable while the API kept running, when it becomes reachable again, then within 30 seconds GET /tasks answers 200 and a valid POST /tasks answers 201, without the API process being restarted, also when the API process was started while the database was unreachable (system AC-001.3)
- **AC-002.6** Given the database is reachable, when a client sends the requests of this repo's spec 001 (valid and invalid POST /tasks, GET /tasks), then the status codes, fields, 422 bodies and oldest-first order are exactly those of the Contract, and a 422 stores no row (system AC-001.1, AC-001.2)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

## Changelog

- 2026-11-10 created from the system plan, with its criteria (spec 147)
- 2026-11-10 approved
- 2026-11-10 building
