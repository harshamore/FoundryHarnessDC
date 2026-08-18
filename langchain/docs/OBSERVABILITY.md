# Observability (Galileo AI)

## What this is, and what it deliberately isn't

Optional, automatic-only tracing: one [Galileo](https://galileo.ai) callback,
attached to every real `agent.invoke(...)` call. DeepAgents already produces
an LLM-call / tool-call / subagent-delegation hierarchy through LangChain's
own callback system — this integration captures it, nothing more. It is
**not** an enforcement mechanism and does not touch any Substrate or role
store: no line in `src/foundry/substrate/`, `coverage/`, `reporter/`,
`triager/`, or `detector/` changes for this. It's wired entirely at the
invocation edges (`src/foundry/observability/galileo.py`), so it cannot
affect anything `docs/CONSTITUTION_MAPPING.md` actually enforces — confirmed
before building it, not assumed.

A deeper option was considered and deliberately deferred: instrumenting
`FindingStore.assign_verdict()`, `CoverageStore.review_cycle()`, and
`BudgetGovernor.should_stop()` directly with `GalileoLogger` manual spans,
so evidence-gate demotions and coverage closures become structured,
queryable Galileo data instead of text buried in tool outputs. Automatic-only
was chosen first — get real traces flowing with minimal risk, decide later
whether the deeper instrumentation is worth it.

## Strictly opt-in, fails soft

`build_galileo_callback()` (`src/foundry/observability/galileo.py`) returns
`None` whenever `GALILEO_API_KEY` isn't set — no import of the `galileo`
package is even attempted. `pytest tests/` and the local quickstart keep
needing zero external services, exactly like every other optional piece of
this build (OpenAI is the only hard requirement, and only for the live-agent
notebook cells, never for tests).

`galileo` is deliberately its own `[observability]` extra, not folded into
`[dev]` — the Setup section's install cell (`pip install -e ".[dev]"`)
never installs it. The Observability section's key-entry cell installs it
live, in-kernel, only if a key was actually entered (`%pip install --quiet
-e ".[observability]"`, guarded by `try: import galileo`) — verified
end-to-end in a fresh environment that genuinely lacked the package:
installs mid-session with no kernel restart needed, and the very next cell
picks it up immediately.

If a key **is** set but the account is unreachable or invalid, the failure
is caught and reported, never raised — verified with a real (deliberately
invalid) key against Galileo's live API:

```
Galileo tracing unavailable (GalileoHTTPException: ('Galileo API returned
HTTP status code 401. Error was: {"detail":"Invalid credentials."}', 401,
...)) -- continuing without it.
```

This is a deliberate asymmetry with the rest of the build: an invalid
`OPENAI_API_KEY` is allowed to raise (`AuthenticationError`), because that's
the actual work failing — there's no meaningful detection run without a
model. A broken Galileo connection degrades to "no tracing" instead, because
tracing is peripheral instrumentation, not the harness's job.

## How it maps onto the harness

Galileo's own hierarchy is `project → log_stream → session → trace → spans`.
This build's mapping:

| Galileo concept | Foundry Harness equivalent |
|---|---|
| `project` | User-entered in the notebook (falls back to `DEFAULT_PROJECT`, `"foundry-harness"`, if left blank) |
| `log_stream` | `colab` (fixed) |
| `trace` | Each `agent.invoke(...)` call — 9 in the notebook today |
| `run_name` (trace label) | The role that produced it: `indexer`, `cartographer`, `detector-rule-sweep`, `detector-exploratory`, `detector-directed`, `triager`, `coverage-guide`, `reporter`, `full-pipeline` |
| `agent` span | Each subagent DeepAgents' `task` tool delegates to |
| `tool` span | Every tool call already in the codebase — `queue_candidate`, `assign_verdict`, `claim_directed_task`, `publish_finding_report`, etc. |
| `llm` span | Every underlying `ChatOpenAI` call |

`project`/`log_stream` are get-or-created by name on first use — no manual
setup required in the Galileo console before running the notebook, even
if you've already created a project by that name yourself (as opposed to
letting the SDK create it). The project-name prompt follows the same
env-var-guard shape as the API key cell: setting `GALILEO_PROJECT` ahead of
time (e.g. a Colab secret, or already answered once this session) skips
the prompt — this is also the underlying `GalileoLogger`'s own env var, not
one this build invented.

## Wiring

`galileo_run_config(callback, run_name=...)` builds the `config=` argument
for one `agent.invoke(...)` call. When `callback` is `None` it returns
`None`, which LangChain treats identically to not passing `config=` at all
— every invoke() cell in the notebook calls this unconditionally, so tracing
being on or off is a single upstream decision (whether a key was entered),
never a per-cell one:

```python
response = harness_agent.invoke(
    {"messages": [...]},
    config=galileo_run_config(galileo_callback, run_name="indexer"),
)
```

`console_url(callback)` builds a direct link to the run's project/log
stream (`https://app.galileo.ai/project/{project_id}/log-streams/{log_stream_id}`)
from the underlying `GalileoLogger`'s own `project_id`/`log_stream_id` — not
fabricated, read from the same object the SDK itself populates during
construction. `run_assessment` (Phase 2) calls this once, at the end of a
run, and stores it on `AssessmentResult.galileo_console_url` — `None`
whenever tracing wasn't configured or failed to initialize. This is what
lets the Phase 3 API/Phase 4 frontend actually confirm tracing worked
instead of the caller having to trust silence either way (see
`docs/API.md`'s own note on this).

## What's unverified — and was flagged before, not discovered after

**Whether DeepAgents' `task`-tool delegation propagates the parent's
`callbacks` down into a subagent's own internal LLM/tool calls.** LangGraph
generally propagates `RunnableConfig` through nested runnables/subgraphs,
so this is likely to work — but confirming the resulting trace tree
actually shows subagent-internal spans (not just "the task tool was called
with this instruction") needs a live run with a real Galileo account, which
this build's testing discipline (no real external calls in `pytest`, no
Galileo account available in this environment) can't do headlessly. Check
the trace tree the first time this runs live with a real key.

## Constraints, named rather than glossed over

- **Free tier is 5,000 traces/month.** Plenty at this toy target's scale (9
  traces per full notebook run), a real ceiling if this ever points at
  something larger or gets run repeatedly in CI.
- **Self-hosting is Galileo Enterprise-only.** On the Free/Pro tiers, trace
  content — including real code snippets and candidate-vulnerability
  descriptions from whatever target is being evaluated — leaves to
  Galileo's SaaS cloud. Fine for the current public toy target; a
  conscious decision the moment this points at anything sensitive.
- **Not a replacement for Constitution II/FR-083.** Galileo also offers a
  real-time guardrail product (Protect); it isn't used here because
  `ReporterStore`'s denylist scan is already a deterministic, code-level
  gate — stronger than a classifier-based runtime guardrail, and this
  build's actual FR-083 enforcement.

## What Galileo adds, once traces are flowing

Built-in, model-graded agent metrics that nothing in this harness measures
on its own: tool selection quality, action advancement/completion, agent
efficiency, and Luna-model hallucination/context-adherence scoring. This is
an external, independent opinion on agent behavior quality, layered on top
of — not replacing — the harness's own code-level evidence gate
(Constitution I, `FindingStore.assign_verdict()`).

## License / data note

Trace data (prompts, tool inputs/outputs, model responses) is sent to
Galileo's own service under its own terms, separate from this repository's
license and from the Foundry spec / CodeGuard attribution in
`data/codeguard/ATTRIBUTION.md`. Nothing here changes what CC BY 4.0 content
this project reproduces from upstream.
