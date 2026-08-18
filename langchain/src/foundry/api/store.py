"""In-memory assessment registry (Phase 3). No persistence across process
restarts -- a deliberate, documented scope boundary matching the
local-only/single-user decision this whole phase was scoped to (see
docs/API.md), not an oversight.

Nothing stored here ever includes a credential: `AssessmentRecord` only
ever holds a human-readable `target_summary` (built once, before any key
is used) plus the same `AssessmentEvent`/`AssessmentResult` objects
`foundry.orchestration` already produces -- neither type has a field for
an API key. Credentials live only as local variables inside one HTTP
request handler and the `ChatOpenAI`/Galileo objects built from them for
that one assessment's background task; never written here, never logged.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from foundry.orchestration.assessment import AssessmentResult
from foundry.orchestration.events import AssessmentEvent


class AssessmentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class AssessmentRecord:
    id: str
    status: AssessmentStatus
    created_at: str
    target_summary: str
    reports_dir: Path
    events: list[AssessmentEvent] = field(default_factory=list)
    result: AssessmentResult | None = None
    error: str | None = None


class AssessmentStore:
    """In-memory only. Each record's `events` list is append-only and safe
    to read while the background task is still appending to it -- a
    single writer (the assessment's own background task, via `on_event`)
    and any number of readers (SSE connections tailing by index), which is
    safe under asyncio's single-threaded cooperative model without extra
    locking: a `list.append` and a `list[i:]` slice are each atomic with
    respect to other coroutines, since neither yields control mid-operation.
    """

    def __init__(self) -> None:
        self._records: dict[str, AssessmentRecord] = {}

    def create(self, target_summary: str, reports_dir: Path) -> AssessmentRecord:
        assessment_id = str(uuid.uuid4())
        record = AssessmentRecord(
            id=assessment_id,
            status=AssessmentStatus.PENDING,
            created_at=datetime.now(timezone.utc).isoformat(),
            target_summary=target_summary,
            reports_dir=reports_dir,
        )
        self._records[assessment_id] = record
        return record

    def get(self, assessment_id: str) -> AssessmentRecord | None:
        return self._records.get(assessment_id)

    def append_event(self, assessment_id: str, event: AssessmentEvent) -> None:
        record = self._records.get(assessment_id)
        if record is not None:
            record.events.append(event)

    def mark_running(self, assessment_id: str) -> None:
        record = self._records.get(assessment_id)
        if record is not None:
            record.status = AssessmentStatus.RUNNING

    def mark_complete(self, assessment_id: str, result: AssessmentResult) -> None:
        record = self._records.get(assessment_id)
        if record is not None:
            record.status = AssessmentStatus.COMPLETE
            record.result = result

    def mark_failed(self, assessment_id: str, error: str) -> None:
        record = self._records.get(assessment_id)
        if record is not None:
            record.status = AssessmentStatus.FAILED
            record.error = error
