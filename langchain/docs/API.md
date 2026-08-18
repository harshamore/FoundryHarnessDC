# FastAPI backend (Phase 3)

## What this is, and its scope

A FastAPI application (`src/foundry/api/`) wrapping `foundry.orchestration.
run_assessment` and `foundry.target.repo` -- no logic duplicated from the
notebook or the library; this surface calls the exact same tested code
every other consumer does. Built for the **local-only, single-user** scope
decided when this productization plan was agreed: no authentication, no
multi-tenant secret storage, an in-memory assessment registry that doesn't
survive a process restart. These are conscious boundaries for this phase,
not oversights -- revisit if this ever needs to serve multiple concurrent
users.

## Install and run

```sh
pip install -e ".[dev,api]"
uvicorn foundry.api.app:app --reload
```

`fastapi`/`uvicorn`/`python-multipart` are their own `[api]` extra, not
folded into the base install or `[dev]` -- the same pattern `[observability]`
already established. `pytest tests/` and the local quickstart keep needing
zero of this installed; `tests/test_api_app.py` skips cleanly (not fails)
without it.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/assessments` | `POST` | Start a new assessment: upload files or give a GitHub URL, plus credentials and goals. Returns immediately with an `assessment_id`; the actual run happens in a background task. |
| `/assessments/{id}/status` | `GET` | Current status (`pending`/`running`/`complete`/`failed`), and the real `AssessmentResult` once complete. |
| `/assessments/{id}/events` | `GET` | Server-Sent Events stream of live agent/tool activity. Replays everything emitted so far, then keeps streaming until the assessment finishes. |
| `/assessments/{id}/report` | `GET` | Downloads the deterministic rollup (FR-081) once the assessment is complete. |

### `POST /assessments`

Multipart form fields:

- `openai_api_key` (required)
- `operator_goals` (required) -- comma-separated, e.g. `sql-injection, path-traversal`
- `files` (a file upload) **or** `github_url` (a `https://github.com/<owner>/<repo>` URL) -- exactly one of the two
- `model` (optional, defaults to `gpt-5.6-luna`)
- `galileo_api_key`/`galileo_project` (optional -- see the Galileo caveat below)
- `max_directed_workers`, `max_concurrent`, `max_cycles` (optional, Phase 2's concurrency/loop knobs)

## Live agent/tool visibility (the second ask this build set out to close)

`/assessments/{id}/events` is sourced from the exact same
`agent.astream_events(...)` stream `foundry.orchestration.agent_runner.
run_single_subagent` already produces when given an `on_event` callback
(Phase 2's streaming extension) -- translated into clean events by
`foundry.orchestration.events.StreamEventTranslator`. Every real subagent
call the assessment makes (Cartographer, both concurrent Detector halves,
every concurrent directed worker, Triager, Reporter) feeds the same
per-assessment event log; the SSE endpoint just tails it. This is the same
underlying event stream Galileo's callback already taps
(`src/foundry/observability/galileo.py`) -- a second, independent
consumer, not a replacement.

## Credential handling

`openai_api_key` is used to construct a real `ChatOpenAI(model=..., api_key=...)`
instance, passed directly as `AssessmentConfig.model` -- **never** set as a
process-wide environment variable. `create_deep_agent` accepts a
`BaseChatModel` instance directly, and every orchestration function
already types `model` as `str | Any` for exactly this reason: a
process-wide env var would be a real correctness bug the moment two
assessments with different keys ever overlap. Nothing in
`AssessmentRecord` (the in-memory store's own record type) has a field
shaped like a credential -- guarded by a structural test
(`tests/test_api_store.py::test_assessment_record_never_carries_a_credential_field`),
not just a convention.

**Galileo credentials are a known, documented exception.** `GalileoLogger`'s
own configuration is a process-wide singleton inside the `galileo` SDK
itself (see `src/foundry/observability/galileo.py`) -- there is no clean
way to give two concurrent assessments their own isolated Galileo
credentials without changes to the SDK's own architecture. `GALILEO_API_KEY`
is still set via `os.environ` here, same as the notebook's Setup section.
Fine for this phase's single-user, one-assessment-at-a-time practical
scope; a real limitation the moment this ever serves truly concurrent
assessments with different Galileo accounts. Flagged here deliberately,
not discovered later.

## What `/report` serves today, ahead of Phase 5

The CISO-ready report format is Phase 5's deliverable, not built yet.
`/report` serves `ReporterStore.build_rollup()`'s existing deterministic
rollup (FR-081 -- severity counts, exploited status, component grouping,
coverage status) in the meantime -- a real, working, correct file, just
not yet formatted for an executive audience. `run_assessment` now always
calls `build_rollup()` as its final step (previously only the notebook did
this, as a separate manual cell); per-finding reports
(`ReporterStore.publish_finding_report`'s own markdown files) are written
to the same `reports_dir` but aren't served individually by this endpoint
yet.

## Testing approach

`tests/test_api_app.py` uses FastAPI's `TestClient` (in-process, no real
network) with `run_assessment` monkeypatched to a fast fake. The
orchestration layer's own correctness -- real concurrency, the real loop,
real DeepAgents execution -- is already thoroughly proven in
`tests/test_orchestration_*.py`; the API tests prove the API layer's *own*
logic instead: routing, validation, credential handling (including that
neither the create response nor the status response ever echoes the key
back), the in-memory store, and SSE formatting. `galileo_api_key` is never
passed in these tests, since doing so would make `create_assessment`
construct a real `GalileoLogger` -- a genuine network call, which this
build's "no external network calls in tests" discipline rules out.

Verified live as a real running process too, not just through
`TestClient`: `uvicorn foundry.api.app:app`, a real `POST /assessments`
with a real file upload over a real HTTP connection, correctly returning a
real assessment ID and target summary.
