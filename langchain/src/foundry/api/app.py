"""FastAPI backend (Phase 3): wraps `foundry.orchestration.run_assessment`
and `foundry.target.repo` -- no logic duplicated from the notebook/library,
this surface calls the exact same tested code. Local-only, single-user
scope (see docs/API.md): no auth, an in-memory `AssessmentStore`,
credentials handled per-request and never persisted to disk or logged.

`openai_api_key` is used to construct a real `ChatOpenAI` instance passed
directly as `AssessmentConfig.model` -- never set as a process-wide
environment variable, which would be a genuine correctness bug the moment
two assessments with different keys ever overlap (`create_deep_agent`
accepts a `BaseChatModel` instance directly; every orchestration function
already types `model` as `str | Any` for exactly this reason). Galileo
credentials are the one place this build's existing, honest limitation
carries over unchanged: `GalileoLogger`'s own config is a process-wide
singleton (see `src/foundry/observability/galileo.py`), so
`GALILEO_API_KEY` is still set via `os.environ` here -- fine for this
phase's single-user, one-assessment-at-a-time practical scope, not fine if
this ever serves concurrent assessments with different Galileo accounts.
Documented in docs/API.md, not silently accepted.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langchain_openai import ChatOpenAI

from foundry.api.store import AssessmentStatus, AssessmentStore
from foundry.observability.galileo import build_galileo_callback
from foundry.orchestration.assessment import AssessmentConfig, run_assessment
from foundry.target.repo import TargetIngestionError, from_github_url, from_upload

# src/foundry/api/app.py -> repo root (4 parents up), overridable via env
# for anyone running this API outside a checkout of this repo.
_DEFAULT_RULES_DIR = Path(
    os.environ.get("FOUNDRY_RULES_DIR", str(Path(__file__).resolve().parents[3] / "data" / "codeguard" / "rules"))
)
DEFAULT_MODEL_NAME = "gpt-5.6-luna"
DEFAULT_GALILEO_PROJECT = "foundry-harness"

# The Phase 4 frontend runs on its own origin (Next.js's dev server,
# localhost:3000 by default) -- a browser enforces CORS on cross-origin
# fetch()/EventSource calls regardless of this being a local-only tool, so
# without this the frontend simply can't reach the API at all. Explicit
# origin list, not "*" -- this API accepts credentials in request bodies
# (never cookies), so wildcard-with-credentials risk doesn't apply here,
# but naming the real origin(s) instead of allowing all is still the
# better default. Configurable via env for anyone serving the frontend
# from somewhere other than the default dev port.
_CORS_ORIGINS = [o.strip() for o in os.environ.get("FOUNDRY_CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

app = FastAPI(title="Foundry Harness API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
store = AssessmentStore()

# Fire-and-forget background tasks must be referenced somewhere or asyncio
# is free to garbage-collect them mid-run -- a well-known footgun, not a
# style preference. Discarded via the task's own done-callback.
_background_tasks: set[asyncio.Task] = set()


def parse_operator_goals(raw: str) -> list[str]:
    return [g.strip() for g in raw.split(",") if g.strip()]


def build_target_summary(target) -> str:
    languages = ", ".join(sorted(target.languages)) or "no supported language detected"
    summary = f"{len(target.files)} file(s) ({languages})"
    unsupported = len(target.unsupported_files)
    if unsupported:
        summary += f", {unsupported} not indexable"
    return summary


async def _run_assessment_background(assessment_id: str, config: AssessmentConfig) -> None:
    store.mark_running(assessment_id)
    try:
        result = await run_assessment(config)
        store.mark_complete(assessment_id, result)
    except Exception as e:  # noqa: BLE001 -- surfaced to the client via /status, not swallowed
        store.mark_failed(assessment_id, f"{type(e).__name__}: {e}")


@app.post("/assessments")
async def create_assessment(
    openai_api_key: str = Form(...),
    model: str = Form(DEFAULT_MODEL_NAME),
    operator_goals: str = Form(...),
    github_url: str | None = Form(None),
    galileo_api_key: str | None = Form(None),
    galileo_project: str | None = Form(None),
    max_directed_workers: int = Form(4),
    max_concurrent: int = Form(4),
    max_cycles: int = Form(5),
    files: list[UploadFile] | None = File(None),
) -> dict[str, Any]:
    have_files = bool(files) and any(f.filename for f in files)
    if not have_files and not github_url:
        raise HTTPException(400, "Provide either files or github_url.")
    if have_files and github_url:
        raise HTTPException(400, "Provide either files or github_url, not both.")

    try:
        if github_url:
            target = from_github_url(github_url)
        else:
            file_bytes = {f.filename: await f.read() for f in files}
            target = from_upload(file_bytes)
    except TargetIngestionError as e:
        raise HTTPException(400, str(e)) from e

    goals = parse_operator_goals(operator_goals)
    if not goals:
        raise HTTPException(400, "At least one operator goal is required.")

    scratch = Path(tempfile.mkdtemp(prefix="foundry-assessment-"))
    reports_dir = scratch / "reports"

    # A real ChatOpenAI instance, not a process-wide env var -- see this
    # module's own docstring for why that distinction matters here.
    chat_model = ChatOpenAI(model=model, api_key=openai_api_key)

    galileo_callback = None
    if galileo_api_key:
        os.environ["GALILEO_API_KEY"] = galileo_api_key
        galileo_callback = build_galileo_callback(project=galileo_project or DEFAULT_GALILEO_PROJECT)

    record = store.create(target_summary=build_target_summary(target), reports_dir=reports_dir)

    config = AssessmentConfig(
        target=target,
        db_path=scratch / "assessment.sqlite3",
        reports_dir=reports_dir,
        operator_goals=goals,
        rules_dir=_DEFAULT_RULES_DIR,
        model=chat_model,
        max_directed_workers=max_directed_workers,
        max_concurrent=max_concurrent,
        max_cycles=max_cycles,
        galileo_callback=galileo_callback,
        on_event=lambda event, _id=record.id: store.append_event(_id, event),
    )

    task = asyncio.create_task(_run_assessment_background(record.id, config))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"assessment_id": record.id, "status": record.status.value, "target_summary": record.target_summary}


@app.get("/assessments/{assessment_id}/status")
async def get_status(assessment_id: str) -> dict[str, Any]:
    record = store.get(assessment_id)
    if record is None:
        raise HTTPException(404, "No such assessment.")
    body: dict[str, Any] = {
        "assessment_id": record.id,
        "status": record.status.value,
        "created_at": record.created_at,
        "target_summary": record.target_summary,
        "event_count": len(record.events),
    }
    if record.result is not None:
        body["result"] = dataclasses.asdict(record.result)
    if record.error is not None:
        body["error"] = record.error
    return body


@app.get("/assessments/{assessment_id}/events")
async def stream_events(assessment_id: str) -> StreamingResponse:
    record = store.get(assessment_id)
    if record is None:
        raise HTTPException(404, "No such assessment.")

    async def event_stream():
        last_index = 0
        while True:
            current = store.get(assessment_id)
            if current is None:
                break
            for event in current.events[last_index:]:
                yield f"data: {json.dumps(dataclasses.asdict(event))}\n\n"
            last_index = len(current.events)
            if current.status in (AssessmentStatus.COMPLETE, AssessmentStatus.FAILED):
                yield f"event: done\ndata: {json.dumps({'status': current.status.value})}\n\n"
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/assessments/{assessment_id}/report")
async def get_report(assessment_id: str) -> FileResponse:
    """Serves the CISO-ready report (Phase 5, `ReporterStore.
    build_ciso_report`): severity-led structure, remediation priorities,
    a coverage/scope statement, and an LLM-authored executive summary
    with a deterministic fallback underneath. The plain deterministic
    rollup (FR-081) still exists alongside it as `rollup.md` in the same
    `reports_dir` (and is what `AssessmentResult.rollup` carries), just
    not served by this endpoint anymore. Per-finding reports
    (`ReporterStore.publish_finding_report`'s own markdown files) also
    live in `reports_dir`, not served individually by this endpoint."""
    record = store.get(assessment_id)
    if record is None:
        raise HTTPException(404, "No such assessment.")
    if record.status != AssessmentStatus.COMPLETE:
        raise HTTPException(409, f"Assessment is {record.status.value}, not complete yet.")
    report_path = record.reports_dir / "ciso_report.md"
    if not report_path.exists():
        raise HTTPException(404, "No report was generated for this assessment.")
    return FileResponse(report_path, media_type="text/markdown", filename="ciso_report.md")
