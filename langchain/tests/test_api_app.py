"""Phase 3 proofs: the FastAPI backend (src/foundry/api/app.py). Tested
via FastAPI's TestClient (in-process, no real network) with
`run_assessment` monkeypatched to a fast fake -- the orchestration layer's
own correctness (real concurrency, the real loop, real DeepAgents
execution) is already thoroughly proven in test_orchestration_*.py; these
tests prove the API layer's *own* logic instead: routing, validation,
credential handling, the in-memory store, and SSE formatting.

`galileo_api_key` is never passed in these tests -- doing so would make
`create_assessment` construct a real `GalileoLogger`, a genuine network
call (see src/foundry/observability/galileo.py), which this build's own
"no external network calls in tests" discipline (already established for
Galileo and target-ingestion tests) rules out.
"""
from __future__ import annotations

import asyncio
import io
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from foundry.api import app as app_module
from foundry.orchestration.assessment import AssessmentResult
from foundry.orchestration.events import AssessmentEvent


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    """Every test gets its own empty in-memory store -- the real module
    holds one global instance (matching a real running server), so tests
    must not see each other's assessments."""
    from foundry.api.store import AssessmentStore

    fresh = AssessmentStore()
    monkeypatch.setattr(app_module, "store", fresh)
    yield fresh


@pytest.fixture
def client():
    return TestClient(app_module.app)


def _fake_result(**overrides) -> AssessmentResult:
    defaults = dict(
        cycles_run=1,
        coverage_complete=True,
        stop_reason="coverage complete",
        published_reports=1,
        security_map_digest="## digest",
        detection_results=[],
        rollup="# Evaluation Rollup\n\n**1 confirmed finding(s) published.**",
    )
    defaults.update(overrides)
    return AssessmentResult(**defaults)


def _patch_run_assessment_fast(monkeypatch, *, delay: float = 0.0, emit_events: bool = False, raise_error: Exception | None = None):
    async def fake_run_assessment(config):
        if delay:
            await asyncio.sleep(delay)
        if emit_events and config.on_event:
            config.on_event(AssessmentEvent(seq=1, timestamp="t", kind="agent_start", role="triager", detail="triager started"))
            config.on_event(AssessmentEvent(seq=2, timestamp="t", kind="tool_call", role="triager", detail="assign_verdict({})"))
        if raise_error:
            raise raise_error
        return _fake_result()

    monkeypatch.setattr(app_module, "run_assessment", fake_run_assessment)


def _wait_for_status(client, assessment_id, target_status, timeout=5.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        resp = client.get(f"/assessments/{assessment_id}/status")
        last = resp.json()
        if last["status"] == target_status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"status never reached {target_status!r}, last seen: {last}")


# ---------------------------------------------------------------------------
# POST /assessments -- validation
# ---------------------------------------------------------------------------


def test_create_assessment_requires_files_or_github_url(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch)
    resp = client.post("/assessments", data={"openai_api_key": "sk-test", "operator_goals": "sql-injection"})
    assert resp.status_code == 400
    assert "files or github_url" in resp.json()["detail"]


def test_create_assessment_rejects_both_files_and_github_url(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch)
    resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test", "operator_goals": "sql-injection", "github_url": "https://github.com/a/b"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assert resp.status_code == 400
    assert "not both" in resp.json()["detail"]


def test_create_assessment_requires_at_least_one_operator_goal(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch)
    resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test", "operator_goals": "   ,  ,"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assert resp.status_code == 400
    assert "operator goal" in resp.json()["detail"]


def test_create_assessment_rejects_invalid_github_url_before_any_clone(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch)
    resp = client.post(
        "/assessments",
        data={
            "openai_api_key": "sk-test",
            "operator_goals": "sql-injection",
            "github_url": "https://gitlab.com/not/github",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /assessments -- success path, credential handling
# ---------------------------------------------------------------------------


def test_create_assessment_with_file_upload_returns_pending_assessment(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch, delay=1.0)  # hold it pending long enough to observe
    resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test-not-real", "operator_goals": "sql-injection, path-traversal"},
        files={"files": ("app.py", io.BytesIO(b"def get_db(): pass"), "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "assessment_id" in body
    assert body["status"] in ("pending", "running")
    assert "python" in body["target_summary"]


def test_create_assessment_response_never_echoes_the_api_key(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch, delay=1.0)
    secret = "sk-super-secret-value-must-not-leak"
    resp = client.post(
        "/assessments",
        data={"openai_api_key": secret, "operator_goals": "sql-injection"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assert secret not in resp.text


def test_assessment_status_response_never_contains_the_api_key(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch)
    secret = "sk-super-secret-value-must-not-leak"
    create_resp = client.post(
        "/assessments",
        data={"openai_api_key": secret, "operator_goals": "sql-injection"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assessment_id = create_resp.json()["assessment_id"]
    status = _wait_for_status(client, assessment_id, "complete")
    assert secret not in str(status)


# ---------------------------------------------------------------------------
# GET /assessments/{id}/status
# ---------------------------------------------------------------------------


def test_status_for_unknown_assessment_is_404(client):
    resp = client.get("/assessments/does-not-exist/status")
    assert resp.status_code == 404


def test_status_transitions_to_complete_with_the_real_result(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch)
    create_resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test", "operator_goals": "sql-injection"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assessment_id = create_resp.json()["assessment_id"]
    status = _wait_for_status(client, assessment_id, "complete")
    assert status["result"]["coverage_complete"] is True
    assert status["result"]["published_reports"] == 1


def test_status_reflects_a_failed_assessment(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch, raise_error=RuntimeError("simulated agent failure"))
    create_resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test", "operator_goals": "sql-injection"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assessment_id = create_resp.json()["assessment_id"]
    status = _wait_for_status(client, assessment_id, "failed")
    assert "simulated agent failure" in status["error"]


# ---------------------------------------------------------------------------
# GET /assessments/{id}/events (SSE)
# ---------------------------------------------------------------------------


def test_status_for_unknown_assessment_events_is_404(client):
    resp = client.get("/assessments/does-not-exist/events")
    assert resp.status_code == 404


def test_events_stream_replays_emitted_events_then_signals_done(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch, emit_events=True)
    create_resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test", "operator_goals": "sql-injection"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assessment_id = create_resp.json()["assessment_id"]
    _wait_for_status(client, assessment_id, "complete")

    with client.stream("GET", f"/assessments/{assessment_id}/events") as resp:
        body = "".join(resp.iter_text())

    assert '"kind": "agent_start"' in body or '"kind":"agent_start"' in body
    assert "triager" in body
    assert "event: done" in body


# ---------------------------------------------------------------------------
# GET /assessments/{id}/report
# ---------------------------------------------------------------------------


def test_report_before_completion_is_409(client, monkeypatch):
    _patch_run_assessment_fast(monkeypatch, delay=2.0)
    create_resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test", "operator_goals": "sql-injection"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assessment_id = create_resp.json()["assessment_id"]
    resp = client.get(f"/assessments/{assessment_id}/report")
    assert resp.status_code == 409


def test_report_for_unknown_assessment_is_404(client):
    resp = client.get("/assessments/does-not-exist/report")
    assert resp.status_code == 404


def test_report_after_completion_serves_the_real_rollup_file(client, monkeypatch, tmp_path):
    async def fake_run_assessment(config):
        config.reports_dir.mkdir(parents=True, exist_ok=True)
        (config.reports_dir / "rollup.md").write_text("# Evaluation Rollup\n\nreal rollup content")
        return _fake_result()

    monkeypatch.setattr(app_module, "run_assessment", fake_run_assessment)

    create_resp = client.post(
        "/assessments",
        data={"openai_api_key": "sk-test", "operator_goals": "sql-injection"},
        files={"files": ("app.py", io.BytesIO(b"def f(): pass"), "text/plain")},
    )
    assessment_id = create_resp.json()["assessment_id"]
    _wait_for_status(client, assessment_id, "complete")

    resp = client.get(f"/assessments/{assessment_id}/report")
    assert resp.status_code == 200
    assert "real rollup content" in resp.text
