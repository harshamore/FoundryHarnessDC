"""Phase 3 proofs: AssessmentStore (src/foundry/api/store.py) -- the
in-memory assessment registry. Pure Python, no HTTP, no agent involved.
"""
from __future__ import annotations

from pathlib import Path

from foundry.api.store import AssessmentStatus, AssessmentStore
from foundry.orchestration.assessment import AssessmentResult
from foundry.orchestration.events import AssessmentEvent


def test_create_returns_a_pending_record_with_a_real_uuid():
    store = AssessmentStore()
    record = store.create(target_summary="1 file (python)", reports_dir=Path("/tmp/reports"))
    assert record.status == AssessmentStatus.PENDING
    assert record.target_summary == "1 file (python)"
    assert record.events == []
    assert record.result is None
    assert len(record.id) == 36  # a real uuid4 string, not a placeholder


def test_get_returns_none_for_unknown_id():
    store = AssessmentStore()
    assert store.get("does-not-exist") is None


def test_get_returns_the_created_record_by_id():
    store = AssessmentStore()
    created = store.create(target_summary="x", reports_dir=Path("/tmp/reports"))
    fetched = store.get(created.id)
    assert fetched is created


def test_append_event_appends_to_the_right_record_only():
    store = AssessmentStore()
    record_a = store.create(target_summary="a", reports_dir=Path("/tmp/reports"))
    record_b = store.create(target_summary="b", reports_dir=Path("/tmp/reports"))
    event = AssessmentEvent(seq=1, timestamp="t", kind="agent_start", role="triager", detail="triager started")

    store.append_event(record_a.id, event)

    assert store.get(record_a.id).events == [event]
    assert store.get(record_b.id).events == []


def test_append_event_for_unknown_id_does_not_raise():
    store = AssessmentStore()
    event = AssessmentEvent(seq=1, timestamp="t", kind="agent_start", role="triager", detail="d")
    store.append_event("does-not-exist", event)  # must not raise


def test_mark_running_updates_status():
    store = AssessmentStore()
    record = store.create(target_summary="x", reports_dir=Path("/tmp/reports"))
    store.mark_running(record.id)
    assert store.get(record.id).status == AssessmentStatus.RUNNING


def test_mark_complete_sets_status_and_result():
    store = AssessmentStore()
    record = store.create(target_summary="x", reports_dir=Path("/tmp/reports"))
    result = AssessmentResult(
        cycles_run=1,
        coverage_complete=True,
        stop_reason="coverage complete",
        published_reports=2,
        security_map_digest="digest",
        detection_results=[],
        rollup="# Evaluation Rollup\n\n**2 confirmed finding(s) published.**",
    )
    store.mark_complete(record.id, result)
    fetched = store.get(record.id)
    assert fetched.status == AssessmentStatus.COMPLETE
    assert fetched.result is result


def test_mark_failed_sets_status_and_error():
    store = AssessmentStore()
    record = store.create(target_summary="x", reports_dir=Path("/tmp/reports"))
    store.mark_failed(record.id, "boom")
    fetched = store.get(record.id)
    assert fetched.status == AssessmentStatus.FAILED
    assert fetched.error == "boom"


def test_assessment_record_never_carries_a_credential_field():
    """Structural guard, not just a convention: AssessmentRecord's own
    field set must never grow an api_key-shaped field -- if it ever does,
    this test forces a conscious decision, not a silent leak."""
    import dataclasses

    from foundry.api.store import AssessmentRecord

    field_names = {f.name for f in dataclasses.fields(AssessmentRecord)}
    assert not any("key" in name.lower() or "credential" in name.lower() or "token" in name.lower() for name in field_names)
