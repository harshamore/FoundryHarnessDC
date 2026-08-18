# Architecture

This is a **working rebuild**, not a stub scaffold: the substrate below runs
and is tested. It follows Cisco's [Foundry Security
Spec](https://github.com/CiscoDevNet/foundry-security-spec) (`SEED` v0.1.0,
reproduced unmodified at `../trial-run/specs/001-foundry/spec.md` and
`../trial-run/.specify/memory/constitution.md`), rebuilt on
[DeepAgents](https://github.com/langchain-ai/deepagents) as the multi-agent
runtime and [CodeGuard](https://github.com/cosai-oasis/project-codeguard) as
the Detector's rule corpus. See `docs/CONSTITUTION_MAPPING.md` for the
principle-by-principle enforcement table and `docs/CODEGUARD_INTEGRATION.md`
for the rule-corpus details.

## Shape (unchanged from the spec)

A fleet of role-specialized agents, coordinated through a shared substrate,
supervised by an Orchestrator, operating on a target within a sandbox. See
spec.md §4.1 for the full diagram; the eight core roles are Orchestrator,
Indexer, Cartographer, Detector, Triager, Validator, Coverage-Guide, and
Reporter.

**Confirmed scope for this build:**
- Source-only for now — no live testbed. The Validator runs in the spec's
  own documented degraded mode (FR-066): verifies a PoC exists and is
  well-formed, never sets `exploited`. A testbed gets added later.
- LLM provider: OpenAI, key entered per-session (Colab `getpass`, never
  committed).
- Reporter output: local markdown files (one per finding + a rollup), no
  issue-tracker integration yet.
- All 8 core roles planned, Validator degraded rather than merged/omitted.
  The 5 extension roles (Deep-Tester, Variant-Hunter, Attack-Mapper,
  Remediator, Self-Improver) are not built — per the spec's own
  recommendation for a first build.

## What's actually implemented right now

All eight core roles from spec.md §4.2, now wired into one running pipeline
(Orchestrator's lifecycle role is this notebook's own `create_deep_agent`
calls — the Full Pipeline section wires all eight subagents into a single
call rather than one per role, but no dedicated Orchestrator subagent
exists; Validator runs degraded, no testbed):

```
src/foundry/
  config.py                    Settings: db path, CodeGuard rules dir, lease seconds
  substrate/
    db.py                      SQLite connection: WAL mode, schema, row access by name
    finding_store.py           Fingerprint, Citation, FindingStore — the evidence gate lives here
                                (now rejects a bare verdict with no report, FR-054);
                                also record_rule_gap/list_rule_gaps (FR-042), list_untriaged,
                                list_by_verdict
    work_queue.py               Atomic claim/lease/heartbeat/release — claim_next() now also
                                 supports prefix claiming (task_type_prefix), and directed
                                 tasks (FR-070) are actually consumed by a live Detector, not
                                 just queued
    budget.py                    Coverage-before-yield stop condition — now fed a real
                                  coverage-complete flag, not a hand-typed boolean
  indexer/
    parser.py                    Multi-language function inventory + direct-call graph
                                  (FR-020/021), no model call. Python: AST-based (decorators
                                  included, e.g. Flask `@app.route(...)`, for FR-031; excluded
                                  from the call graph itself). JavaScript/TypeScript/TSX/Java/Go
                                  (Phase 1's v1 set): tree-sitter, using tree-sitter-language-
                                  pack's bundled per-language "tags" queries -- methods are
                                  class-qualified (e.g. "UserService.getUser") where the
                                  language's query has a class/interface scope to qualify
                                  against; same-file name collisions that survive qualification
                                  (e.g. Go, which has none) get a stable `#2`/`#3` suffix rather
                                  than silently dropping or crashing (`functions` is
                                  UNIQUE(file, name))
    store.py                      Persists the index; the query interface (FR-022, now file-
                                   disambiguated -- get_function_body/find_symbol/get_callers/
                                   get_callees accept an optional `file` since `functions` has
                                   always been UNIQUE(file, name), not UNIQUE(name)); the real
                                   evidence-gate resolver
    tools.py                       LangChain tool wrappers around the store
  cartographer/
    store.py                       Persists the security map + digest (FR-035)
    fallback.py                     Deterministic per-section fallback (FR-036a) — no model call
    tools.py                         LangChain tool wrappers, one per section (FR-030–034)
  codeguard/
    loader.py                       Parses the vendored rule corpus (FR-041); load_rules()'s
                                     `languages=` filters rule-sweep to what's relevant for the
                                     target's detected language(s) (Phase 1), reconciling "tsx"
                                     (a distinct tree-sitter grammar) against CodeGuard's own
                                     "typescript"-only tagging vocabulary — no model call
    tools.py                         LangChain tool wrappers: list_rules, get_rule
  target/
    repo.py                         Phase 1 target ingestion: from_upload()/from_github_url()
                                     build a TargetRepo (root + per-file detected language) from
                                     uploaded content or a shallow-cloned public GitHub repo.
                                     GitHub URLs are validated before `git clone` ever sees them
                                     (rejected outright if not `https://github.com/<owner>/<repo>`,
                                     and the URL actually passed to the subprocess is rebuilt from
                                     the validated match groups, not the raw input string); a
                                     file-count and total-byte cap (with common dependency/build
                                     directories skipped during the walk) keeps a real repo
                                     bounded. No model call
  detector/
    tools.py                        LangChain tool wrappers: queue_candidate, record_rule_gap,
                                     and build_directed_task_tools (claim_directed_task,
                                     complete_directed_task — the latter always records a
                                     CoverageStore sweep, closing the checklist item
                                     regardless of whether a candidate was found)
  triager/
    tools.py                        LangChain tool wrappers: list_candidates, get_candidate,
                                     assign_verdict (binds the real resolver as a closure)
  coverage/
    store.py                        CoverageStore: the whole FR-067/069/070/071/074 mechanism
                                     — no model call anywhere in it
    tools.py                        One LangChain tool: get_coverage_report (read-only)
  reporter/
    classification.py                Deterministic CWE lookup (FR-076) and the FR-083
                                      denylist scan — no model call in either
    store.py                          ReporterStore: FR-079/083 enforced structurally before
                                       anything is written; FR-081's rollup, entirely deterministic
    tools.py                          LangChain tool wrappers: list_true_positives,
                                       get_finding_detail, suggest_weakness_class,
                                       publish_finding_report
  agents/
    _middleware.py                 Shared: restricts DeepAgents' default filesystem
                                    tools (ls/glob/... bound to an empty virtual FS)
                                    down to the one tool the framework requires
    indexer.py                     The Indexer as a DeepAgents SubAgent dict
    cartographer.py                  The Cartographer as a DeepAgents SubAgent dict
    detector.py                       Three SubAgent dicts: rule-sweep (FR-037), exploratory
                                       (FR-040), and directed (FR-070 — consumes Coverage-
                                       Guide's queued gaps)
    triager.py                         The Triager as a DeepAgents SubAgent dict
    coverage_guide.py                   The Coverage-Guide as a DeepAgents SubAgent dict
                                         (FR-073 only — the narrative, not the mechanism)
    reporter.py                          The Reporter as a DeepAgents SubAgent dict
  observability/
    galileo.py                     Optional Galileo AI tracing, automatic-only scope:
                                    build_galileo_callback()/galileo_run_config()/console_url().
                                    None/no-op without GALILEO_API_KEY, never raises even when
                                    set and unreachable -- wired only at agent.invoke() call
                                    sites, touches no Substrate or role store
  orchestration/
    concurrency.py                  run_bounded(): generic asyncio.Semaphore-bounded
                                     concurrency primitive -- Constitution V made real
    detection.py                     run_broad_detection_concurrently() (rule-sweep +
                                      exploratory, genuinely concurrent) and
                                      run_directed_workers_concurrently() (N directed
                                      workers, each its own connection, racing the real
                                      WorkQueue) -- each worker a real create_deep_agent(...)
                                      instance, its own sqlite3.Connection
    loop_control.py                   evaluate_cycle()/has_directed_work_available(): the
                                       pure, deterministic "stop or direct at the gaps"
                                       decision logic, no model involved
    assessment.py                      run_assessment(): the real index -> map -> detect ->
                                        triage -> check coverage -> detect the gaps ->
                                        repeat -> report sequence, tying the above together
data/
  codeguard/rules/             Vendored CodeGuard corpus (fetched, git-ignored — see scripts/)
  toy_target/vulnerable_app.py  Shared Python fixture target every notebook section parses/queries
  multi_lang_toy_target/        Phase 1's multi-language sibling: one small deliberately-
                                 vulnerable file per supported non-Python language (app.js,
                                 app.ts, UserProfile.tsx, UserService.java, main.go), same
                                 SQL-injection-shaped vulnerability in each, same-named methods
                                 across classes/receivers on purpose (exercises class
                                 qualification and the dedup fallback)
  reports/                       Generated by the Reporter section: one markdown file per
                                  published finding + rollup.md (git-ignored, regenerated per run)
scripts/
  fetch_codeguard_rules.py     Pins and vendors the CodeGuard corpus
tests/ (16 files, 215 tests total)
  test_finding_store.py        17 tests proving Constitution I/III/IV/VI/VIII mechanically,
                                including task_type_prefix claiming (used by directed detection)
                                and queue_candidate's cross-connection dedup race (Phase 2)
  test_indexer.py               27 tests proving FR-020/021/022/025/026, the real resolver,
                                 the filesystem-tool restriction, decorator capture, and
                                 file-disambiguated reads (two files, same function name,
                                 same-name-still-works-unambiguous, and the tool layer
                                 reporting ambiguity instead of guessing), no LLM
  test_multi_language_parser.py  23 tests proving the tree-sitter path for JS/TS/TSX/Java/Go
                                  against data/multi_lang_toy_target/ -- function/call-graph
                                  extraction, class qualification, the Go dedup-fallback case,
                                  and the real evidence-gate resolver working against non-Python
                                  functions, no LLM
  test_target_ingestion.py       21 tests proving from_upload()/from_github_url(): language
                                  detection, path-traversal rejection, file-count/byte caps,
                                  GitHub URL validation rejecting bad input before subprocess.run
                                  is ever called (mocked for the clone-success/failure paths --
                                  no real network calls in the suite; the real clone path was
                                  separately verified live against a real public GitHub repo),
                                  no LLM
  test_cartographer.py           12 tests proving FR-036a's fallback guarantee, the digest, and
                                  the filesystem-tool restriction, no LLM
  test_codeguard.py               15 tests proving the rule corpus loads and parses correctly,
                                   including Phase 1's language-filtered rule-sweep, no LLM
  test_detector.py                 15 tests proving the tool wrappers, all three SubAgent shapes,
                                    the front-loaded security-map digest, and the directed-task
                                    loop actually closing a coverage-checklist item end to end, no LLM
  test_triager.py                  12 tests proving FR-054, the evidence-gate demotion through
                                    the tool layer (not just FindingStore directly), and the
                                    SubAgent shape, no LLM
  test_coverage.py                  18 tests proving FR-067/068/069/070/071/074 and a direct
                                     integration test wiring CoverageStore to the real
                                     BudgetGovernor, no LLM
  test_reporter.py                   23 tests proving FR-079/081/083 and the FR-078/080
                                      overwrite-not-duplicate behavior, no LLM
  test_observability.py               9 tests proving the Galileo wrapper's opt-in/fail-soft
                                       behavior with mocked GalileoLogger/GalileoCallback --
                                       no real network calls; skips entirely (not fails) if
                                       the `galileo` package (the `observability` extra) isn't
                                       installed
  test_orchestration_concurrency.py    6 tests proving run_bounded's actual concurrency bound
                                        (real overlap detection via a shared counter + sleep,
                                        not just "never exceeded"), no LLM, no DeepAgents
  test_orchestration_detection.py       6 tests: the Phase 2 centerpiece -- real
                                         create_deep_agent(...) graphs driven by scripted fake
                                         BaseChatModel subclasses (bind_tools the only no-op
                                         override; every tool call goes through the real
                                         LangGraph ToolNode), proving N concurrent directed
                                         workers never double-claim a real WorkQueue task and
                                         rule-sweep/exploratory genuinely overlap in wall-clock
                                         time -- found and fixed the queue_candidate
                                         cross-connection race in the process
  test_orchestration_loop_control.py     9 tests proving evaluate_cycle's stop/continue
                                          decision and Constitution VI's conjunction, pure and
                                          deterministic, no LLM
  test_orchestration_assessment.py        2 tests proving run_assessment's full sequence end
                                           to end -- real indexing, real deterministic
                                           fallback, real concurrent detection, the loop
                                           correctly closing via directed-detection evidence
                                           and correctly stopping via the no-progress guard
                                           when it can't
notebooks/
  01_substrate.ipynb            The single, growing Colab notebook: Setup, Observability,
                                 Substrate, Indexer, Cartographer, Detector, Triager,
                                 Coverage-Guide, Reporter, and Full Pipeline sections — all
                                 eight core roles plus their combined wiring and optional
                                 tracing, in one file, never a separate notebook per role
```

The Indexer's actual indexing (parsing, call graph, persistence, queries) has
no LLM dependency — FR-020 requires a deterministic parser, not model
extraction. The Cartographer is the opposite case: its real content IS meant
to be LLM-authored, so the structural guarantee is FR-036a instead — every
section gets a mechanically-derived fallback before any agent runs, proven
in the notebook by intentionally letting the live agent call fail (invalid
key) and confirming every section still reads `source=fallback` rather than
being empty. The Detector is LLM-authored like the Cartographer, but its
structural guarantee is Constitution II instead: neither the rule-sweep nor
the exploratory subagent has any tool that reaches a human or an issue
tracker, only `queue_candidate` — so no matter what either agent decides,
"surface only what survives" holds by construction. The Triager adds no new
enforcement mechanism of its own — the evidence gate it calls has been built
and tested since the Substrate section; this section is what finally puts a
live agent's real (possibly wrong) citations through it. Coverage-Guide is
the same shape again, one level up: every MUST-level requirement (FR-067
derive checklist, FR-069 check off from evidence, FR-070 directed tasks,
FR-071 the coverage-complete flag, FR-074 don't rebuild from scratch) is
mechanical, exercised directly from `CoverageStore` with no LLM involved --
"coverage measures attempt, not outcome" is an evidence check, the same way
`BudgetGovernor.should_stop()` is a mechanical conjunction. The payoff:
`coverage_store.is_complete()` now feeds `gov.should_stop()` directly,
closing Constitution VI end to end with real inputs on both sides instead
of the hand-typed booleans the Substrate section's own tests used.

The Reporter is the last role and Constitution II's endpoint: only
`true-positive` findings are ever eligible, checked against the finding
store itself (FR-079) rather than trusted from the model, and every report
is scanned for forbidden model/provider/internal-identifier mentions before
a byte is written (FR-083) -- both proven live in the notebook by
deliberately trying to publish a `needs-review` finding and a report that
names the model, and watching both get rejected with the real reason, not
a hand-crafted test assertion. FR-076/077 (weakness taxonomy and severity
scheme, both left open by the spec's own `[NEEDS CLARIFICATION]` markers)
are resolved for this build as CWE and a four-tier qualitative scale
(critical/high/medium/low) -- a judgment call, documented here rather than
silently made. FR-081's rollup (counts, component grouping, coverage
status) is entirely deterministic aggregation, no LLM needed to compute
any of it. Nine real OpenAI calls exist in this build now (Indexer,
Cartographer, Detector rule-sweep, Detector exploratory, Triager,
Coverage-Guide, Reporter, Detector directed, and the Full Pipeline's
all-eight-subagents call), each a `create_deep_agent` main agent delegating
through the `task` tool to prove the tool interface is usable by an LLM,
not just by pytest.

**The directed-detection loop, closed (FR-070) — the Full Pipeline
section.** `queue_directed_tasks` writes real, claimable tasks to the
`WorkQueue`; until this section nothing consumed them. Closing this
surfaced a real gap, not just a missing consumer: `CoverageStore.
review_cycle()` closes a checklist item on *evidence* (a `findings` row or
a `coverage_log` sweep matching that exact area/goal), not on work-queue
status — so a directed pass that checks an area and finds nothing would
have drained its task with no effect on coverage at all. Fixed at the tool
layer: `build_directed_task_tools`'s `complete_directed_task`
(`src/foundry/detector/tools.py`) now always calls `CoverageStore.
record_sweep()` using the *claimed task's own* area/goal, tracked
server-side rather than re-supplied by the model, regardless of whether
`queue_candidate` was also called — the same "tool decides what counts as
evidence, model just supplies what it found" shape as the Triager's real
resolver. `WorkQueue.claim_next()` gained a `task_type_prefix` parameter
(`tests/test_finding_store.py`) so a directed Detector can claim "any
directed-detection task" without knowing the exact area/goal-encoded
`task_type` up front. Proven live in the notebook and in
`tests/test_detector.py::test_complete_directed_task_closes_the_matching_coverage_checklist_item`.

**One agent, every role — also the Full Pipeline section.** All eight
subagents (indexer, cartographer, detector ×3, triager, coverage-guide,
reporter) now register on a single `create_deep_agent(...)` call instead
of one call per role, the actual shape an Orchestrator wires up. This adds
no new enforcement mechanism — Constitution II still holds per-subagent's
own `tools` list regardless of how many subagents share one main agent —
but it is the first point in this build where the main agent has more than
one subagent to choose between on a real request.

**Optional Galileo AI tracing — its own Observability section, ahead of
Substrate.** A `GalileoCallback` attached to every real `agent.invoke(...)`
call, added purely at the invocation edges (`src/foundry/observability/
galileo.py`) — confirmed before building it that this touches zero lines
in any Substrate or role store, so it can't affect anything this document's
constitution mapping enforces. Strictly opt-in (`None`/no-op without
`GALILEO_API_KEY`) and fails soft (a bad key or unreachable Galileo account
degrades to "no tracing," verified against a real, deliberately invalid key
returning a real HTTP 401, caught and reported, never raised) — a
deliberate asymmetry with `OPENAI_API_KEY`, which is allowed to raise since
that's the actual work failing. See `docs/OBSERVABILITY.md` for the full
trace/span mapping and the constraints worth knowing (free-tier trace
budget, SaaS data exposure, self-hosting is Enterprise-only).

**Deferred by design, not forgotten**: FR-038 (dependency scanning) is
skipped for the same reason FR-039 (secret scanning) mostly overlaps with
CodeGuard's own `hardcoded-credentials` rule: the toy target has no
third-party dependency manifest to scan. FR-046 (exploratory Detector
instances consult the coverage log before choosing an area) is
half-addressed: the `coverage_log` table and `CoverageStore.record_sweep()`
exist and are now exercised by the directed half, but the exploratory
subagent doesn't call it. FR-084 (every code location a permalink that
resolves for the reader) isn't attempted -- reports cite `path:line-range`
directly instead, since there's no commit-pinned VCS host story for a toy
target parsed straight off disk; the spec itself leaves this one's
mechanics as a `[NEEDS CLARIFICATION]`.

**A live-only failure mode worth knowing about**: `create_deep_agent`
attaches a default filesystem middleware to every agent and subagent
(`ls`/`read_file`/`glob`/... bound to an empty, in-memory virtual
filesystem) regardless of the `tools` list a `SubAgent` dict specifies. The
first live Cartographer run tried `ls /`, `ls /workspace`, and a recursive
glob instead of the real index tools it was given, found nothing, and wrote
"no target code discoverable" into every section (still correctly labeled
`source=llm` — the write tools *were* called, just with bad content, which
is exactly why FR-036a's structural fallback matters). `src/foundry/agents/
_middleware.py::minimal_filesystem_middleware()` restricts this down to the
one tool the framework requires (`read_file` can't be excluded), applied to
both the Indexer and Cartographer subagents and their main agents; the
system prompt also now explicitly tells the model to ignore it.

## What's next (roadmap, not yet built)

All eight core roles are built, and three pieces that were previously
deferred — the directed-detection loop closure, the all-subagents
pipeline, and optional Galileo tracing — are done. What's left is
deliberately out of scope for this build, not oversight:

- A dedicated Orchestrator subagent with `interrupt_on`-gated tools
  (`mark_coverage_complete`, `override_verdict`) for Constitution X ("the
  operator outranks every agent") — this notebook's sequence of
  `create_deep_agent` calls stands in for orchestration, but no tool
  anywhere requires explicit operator approval before executing.
- A real testbed, which would take the Validator out of degraded mode
  (Constitution VII) and give Constitution IX (sandbox by infrastructure)
  something real to attach to.
- Genuinely concurrent subagent instances (multiple Detector or Triager
  workers running at once against a real, larger target), which is what
  would actually exercise Constitution V beyond what a single top-level
  call with occasional parallel tool dispatch already covers. Once this
  lands, Galileo trace timestamps are a natural way to *show* the
  concurrency actually happened, not just assert it.
- Deeper Galileo instrumentation (manual `GalileoLogger` spans inside
  `FindingStore.assign_verdict()`, `CoverageStore.review_cycle()`, and
  `BudgetGovernor.should_stop()`), so evidence-gate demotions and coverage
  closures become structured, queryable Galileo data instead of text
  buried in tool outputs — deliberately deferred in favor of automatic-only
  tracing first; see `docs/OBSERVABILITY.md`.

See `docs/CONSTITUTION_MAPPING.md` for the full principle-by-principle
status.

### Toward a real product (multi-session program, in progress)

Separately from the constitution gaps above, this notebook-driven reference
implementation is being turned into an actual product: a web frontend
(upload a file or a public GitHub URL, plus OpenAI/Galileo credentials), a
live view of which agent/tool is running during an assessment, genuinely
concurrent agent execution instead of one call at a time, a downloadable
CISO-ready report, and multi-language support (tree-sitter-based, starting
with Python/JavaScript-TypeScript/Java/Go). This is sequenced as:

- **Phase 0 (done)** — file-disambiguated `IndexStore` reads
  (`get_function_body`/`find_symbol`/`get_callers`/`get_callees` now accept
  an optional `file`; `functions` has always been `UNIQUE(file, name)`, not
  `UNIQUE(name)` — this was never actually guaranteed unique, it just never
  collided against the single-file toy target). Blocking prerequisite for
  multi-file and multi-language targets, where name collisions become
  likely rather than theoretical.
- **Phase 1 (done)** — `src/foundry/target/repo.py`'s `from_upload()`/
  `from_github_url()` build a `TargetRepo` from uploaded content or a
  validated, shallow-cloned public GitHub URL (file-count/byte caps,
  common dependency directories skipped, command-injection-safe by
  construction — the URL actually passed to `git clone` is rebuilt from
  validated regex groups, never the raw input). `src/foundry/indexer/
  parser.py` now dispatches by file extension: Python keeps its proven
  `ast`-based path unchanged, JavaScript/TypeScript/TSX/Java/Go go through
  tree-sitter (`tree-sitter-language-pack`'s bundled per-language tags
  queries), with same-file name collisions handled honestly (class-
  qualified where the language's query supports it, a stable `#2`/`#3`
  suffix fallback where it doesn't, e.g. Go). CodeGuard rule-sweep is now
  language-filterable (`load_rules(..., languages=...)`, using the
  `Rule.languages` field the corpus already carried but nothing read
  before this). Verified against a real, live public GitHub repo end to
  end (clone → walk → parse → index → query), not just the vendored
  fixtures.
- **Phase 2 (done)** — `src/foundry/orchestration/`: `concurrency.py`'s
  `run_bounded()` (a generic `asyncio.Semaphore`-bounded concurrency
  primitive — Constitution V made real, not just asserted); `detection.py`'s
  `run_broad_detection_concurrently()` (rule-sweep + exploratory, two
  genuinely concurrent subagent instances) and
  `run_directed_workers_concurrently()` (N directed-detection workers,
  each on its own connection, racing the real `WorkQueue.claim_next()`);
  `loop_control.py`'s `evaluate_cycle()`/`has_directed_work_available()`
  (the pure, deterministic decision logic); and `assessment.py`'s
  `run_assessment()`, which formalizes the real "index → map → detect →
  triage → check coverage → detect the gaps → repeat → report" sequence as
  actual control flow for the first time — `BudgetGovernor.should_stop()`
  and `CoverageStore.review_cycle()`/`is_complete()` previously had zero
  callers in `src/`, only in tests and hand-sequenced notebook cells. This
  is also where the earlier-paused pipeline-reordering discussion
  resolves: directed detection now runs right after Coverage-Guide
  identifies gaps, inside a real loop, not stuck after Reporter in a
  single-pass demo.

  Building this surfaced a real, previously-latent race:
  `FindingStore.queue_candidate()`'s dedup check (SELECT, then
  conditionally INSERT) was only ever proven safe for concurrent callers
  *sharing one connection* (`lock_for` serializes that case); two
  genuinely separate connections — exactly what concurrent Detector
  workers use — can both pass the SELECT before either commits, and the
  loser used to see a raw `sqlite3.IntegrityError` instead of the same
  "already queued" outcome a same-connection race produces. Fixed by
  catching the `IntegrityError` and reading back the winning row, proven
  under both real concurrent DeepAgents agent execution
  (`tests/test_orchestration_detection.py`) and a dedicated
  regression test in `tests/test_finding_store.py`.

  Verified without a real OpenAI key (none available in this build
  environment): scripted fake `BaseChatModel` subclasses drive real
  `create_deep_agent(...)` graphs — real `task`-tool delegation, real
  `claim_directed_task`/`complete_directed_task`/`queue_candidate` tool
  calls through the real LangGraph `ToolNode` — the only thing faked is
  the model's response content. `bind_tools` is the sole framework method
  overridden as a no-op.
- **Phase 3/4** — a FastAPI backend wrapping the same `src/foundry/*`
  library (no logic duplicated), streaming agent/tool events via
  `CompiledStateGraph.astream_events()` (the same underlying LangChain
  event stream Galileo's callback already taps); a React/Next.js frontend
  consuming it.
- **Phase 5** — a CISO-ready markdown report, extending
  `ReporterStore.build_rollup`'s existing deterministic aggregation with an
  LLM-authored executive summary (deterministic fallback underneath,
  matching the Cartographer's FR-036a / Coverage-Guide's FR-073 pattern),
  downloadable from the backend.

Scoped deliberately to local-only, single-user for now — no auth or
multi-tenant secret storage yet; API keys live in memory for the session
only, matching the credential-handling discipline this build has followed
throughout (`GALILEO_API_KEY` never written to disk, never logged).

## Quickstart

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/fetch_codeguard_rules.py
.venv/bin/python -m pytest tests/ -v
```

All of the above runs with no API key and no network access beyond the
one-time CodeGuard fetch.

## Attribution

`../trial-run/specs/001-foundry/spec.md` and
`../trial-run/.specify/memory/constitution.md` are reproduced unmodified from
[CiscoDevNet/foundry-security-spec](https://github.com/CiscoDevNet/foundry-security-spec),
© 2026 Cisco Systems, Inc., CC BY 4.0. `data/codeguard/` is vendored from
[cosai-oasis/project-codeguard](https://github.com/cosai-oasis/project-codeguard),
CC BY 4.0 — see `data/codeguard/ATTRIBUTION.md`. Everything under `src/`,
`scripts/`, `tests/`, and `notebooks/` is this project's own code.
