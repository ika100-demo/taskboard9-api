---
spec_id: 001-create-and-list-in-memory-tasks
title: Create and list in-memory tasks
status: approved
priority: P1
shape: service-python
---

# 001 — Create and list in-memory tasks

## Problem

The Task API has no tasks yet: a client of taskboard9 cannot record a piece of work or see what has been recorded. Creating a task with a title and an optional due date, and listing all tasks, is the smallest useful slice of the board and the base every later task feature builds on. Tasks live in the service's memory for now, so this slice ships without a database.

## Stories

As a taskboard9 user, I want to create a task with a title and, if I like, a due date, so that I can record work I have to do.

As a taskboard9 user, I want to list all tasks, so that I can see everything that has been recorded.

## Acceptance criteria

- **AC-001.1** Given the service is running, when a client sends `POST /tasks` with `{"title": "Buy milk", "due_date": "2026-12-01"}`, then the response is 201 with a JSON object holding a server-assigned non-empty string `id`, `title` "Buy milk" and `due_date` "2026-12-01", and a following `GET /tasks` contains that task. (smoke)
- **AC-001.2** Given the service is running, when a client sends `POST /tasks` with only `{"title": "Buy milk"}`, then the response is 201 and the returned task has `due_date` null.
- **AC-001.3** Given the service is running, when a client sends `POST /tasks` with `title` missing, null, not a string, empty, whitespace only, or longer than 200 characters after trimming, then the response is 422 with an error body that names the field `title`, and `GET /tasks` does not contain a new task.
- **AC-001.4** Given the service is running, when a client sends `POST /tasks` with a valid title and a `due_date` that is not a calendar date in `YYYY-MM-DD` form (for example "2026-02-30", "tomorrow" or "2026-12-01T10:00:00"), then the response is 422 with an error body that names the field `due_date`, and no task is created.
- **AC-001.5** Given tasks "A", "B" and "C" were created in that order, when a client sends `GET /tasks`, then the response is 200 with a JSON array of exactly those three tasks in creation order, each with `id`, `title` and `due_date` as returned on creation, and every `id` distinct.
- **AC-001.6** Given the service is running, when a client sends `GET /tasks`, then the response is 200 with a JSON array, and that array is empty `[]` when no task has been created since the service started. (smoke)
- **AC-001.7** Given tasks were created, when the service restarts, then `GET /tasks` returns `[]`.

## Non-goals

- Updating, completing or deleting tasks, and fetching a single task by id.
- Persisting tasks across restarts or sharing them between several running instances.
- Filtering, sorting other than creation order, and pagination of the list.
- Authentication, authorization and per-user task lists.
- A limit on the number of tasks held in memory.

## Assumptions

- **A1** The endpoints are `POST /tasks` and `GET /tasks`, with JSON field names `id`, `title`, `due_date` (other option: a versioned prefix such as `/v1/tasks`, or camelCase `dueDate`; affects AC-001.1 to AC-001.7).
- **A2** `due_date` is a calendar date without time or time zone, `YYYY-MM-DD`; past dates are accepted (other option: a full timestamp, or rejecting past dates; affects AC-001.1, AC-001.4).
- **A3** A missing or null `due_date` means "no due date" and is returned as `null` (other option: omit the field from the response; affects AC-001.2, AC-001.5).
- **A4** The title is trimmed of leading and trailing whitespace, stored trimmed, and must be 1 to 200 characters long after trimming; duplicate titles are allowed (other option: no trimming, a different limit, or unique titles; affects AC-001.3).
- **A5** The `id` is an opaque, server-assigned unique string; a client-supplied `id` and any other unknown fields are ignored (other option: sequential integers, or rejecting unknown fields with 422; affects AC-001.1, AC-001.5).
- **A6** The list is ordered by creation, oldest first, and returns all tasks in one response (other option: newest first, or paginated; affects AC-001.5).
- **A7** Invalid input answers 422 with an error body naming the offending field, the framework's standard validation error shape (other option: 400 with a custom error format; affects AC-001.3, AC-001.4).
- **A8** A task carries no further fields (no creation time, status or description) in this slice (other option: add `created_at`; affects AC-001.1, AC-001.5).

## Open questions

None.

## Changelog

- 2026-11-10 created
- 2026-11-10 approved
