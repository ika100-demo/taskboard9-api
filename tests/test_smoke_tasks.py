"""Smoke tests for spec 001 (AC-001.1, AC-001.6) through SMOKE_BASE_URL."""

from __future__ import annotations

import uuid

import httpx
import pytest


@pytest.mark.smoke
def test_list_tasks_returns_array_ac_001_6(smoke_base_url: str) -> None:  # AC-001.6
    r = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.smoke
def test_invalid_title_rejected_ac_001_3(smoke_base_url: str) -> None:  # AC-001.1 read-only
    r = httpx.post(smoke_base_url + "/tasks", json={"title": "   "}, timeout=10)
    assert r.status_code == 422


@pytest.mark.smoke
@pytest.mark.writes
def test_create_then_list_ac_001_1(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    r = httpx.post(
        smoke_base_url + "/tasks", json={"title": title, "due_date": "2026-12-01"}, timeout=10
    )
    assert r.status_code == 201
    created = r.json()
    assert created["id"] and created["title"] == title and created["due_date"] == "2026-12-01"
    listed = httpx.get(smoke_base_url + "/tasks", timeout=10).json()
    assert created in listed
