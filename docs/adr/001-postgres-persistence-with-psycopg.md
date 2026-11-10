# ADR-001: Postgres persistence with psycopg 3, a sync pool and a self-applied schema

## Status

Accepted (spec 002, 2026-11-10).

## Context

Spec 002 moves tasks from process memory into the system's PostgreSQL (`DATABASE_URL`, provided by the gitops-app's
`postgres` resource). The API must start and stay ready while the database is down, answer `503` within 5 seconds
when it is down or slow, recover without a restart within 30 seconds, and run as several instances that may all start
at once. The routes are synchronous FastAPI handlers running in the thread pool. This is the first database in the
repo, so the choices here become the pattern for every later table.

## Decision

- **Driver and pool:** `psycopg[binary]` 3 with `psycopg_pool.ConnectionPool` (sync). No ORM: two tables' worth of SQL
  does not pay for one, and plain parameterised SQL keeps the timeouts and error mapping visible.
- **One `Database` object per app** (`src/taskboard9_api/db.py`) owns the pool: built from `DATABASE_URL` without I/O,
  opened lazily on first use, closed on app shutdown. Every driver/pool failure that means "the database is not
  usable" (`psycopg.OperationalError`, which includes `PoolTimeout`, `PoolClosed` and `QueryCanceled`) and a missing
  `DATABASE_URL` surface as one domain exception, `DatabaseUnavailable`, which the app maps to `503`.
- **Timeouts are fixed in code**, not configurable: connect 2 s, pool checkout 2 s, `statement_timeout` 3 s, pool
  `reconnect_timeout` 10 s (keeps the reconnect back-off gaps at 4 s or less, so recovery is fast).
- **The service owns its schema.** Each store applies idempotent DDL (`CREATE TABLE IF NOT EXISTS ...`) inside a
  transaction holding `pg_advisory_xact_lock(<per-store constant>)`, once per process: at startup in a background
  thread when the database is reachable, otherwise before the first request that reaches it. No migration tool.
- **Tests run against a real PostgreSQL**: `TEST_DATABASE_URL` when set, otherwise a throwaway container started by
  `testcontainers` (dev dependency). No database fakes for store or acceptance tests.

## Consequences

**Positive:** no extra deploy step or init job; several instances start safely; a database outage never takes the pod
out of rotation (`/health` and `/ready` never touch the database); one exception type keeps the 503 mapping in one place.

**Negative:** schema changes are limited to additive, idempotent DDL in the store. The first change that needs data
migration or a destructive step must introduce a migration tool in a new ADR. `devbox run test` needs Docker (or
`TEST_DATABASE_URL`): GitHub-hosted runners have it; a self-hosted runner without Docker must provide a database.
