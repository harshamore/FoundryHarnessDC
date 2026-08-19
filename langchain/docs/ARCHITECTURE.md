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
    agent_runner.py                  run_single_subagent(): one subagent, one throwaway
                                      main agent, one real invocation -- .ainvoke() by
                                      default, .astream_events() when given an on_event
                                      callback (Phase 3). Shared by detection.py and
                                      assessment.py so the streaming logic lives in one place
    events.py                         AssessmentEvent/StreamEventTranslator (Phase 3): the
                                       raw LangGraph astream_events() stream turned into
                                       clean agent_start/tool_call/tool_result events,
                                       stack-based role tracking so a tool result the main
                                       agent receives back from a subagent is correctly
                                       attributed, not left on the subagent that just ran
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
                                        repeat -> report sequence, tying the above together;
                                        now also always runs the deterministic rollup
                                        (FR-081) as its final step
  api/
    store.py                        AssessmentStore/AssessmentRecord (Phase 3): in-memory
                                     assessment registry, no credential-shaped field ever
                                     (structurally guarded, not just convention)
    app.py                           FastAPI app: POST /assessments (file upload or GitHub
                                      URL), GET .../status, GET .../events (SSE, live
                                      agent/tool visibility), GET .../report. See docs/API.md
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
tests/ (18 files, 255 tests total)
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
  test_orchestration_detection.py       9 tests: the Phase 2 centerpiece -- real
                                         create_deep_agent(...) graphs driven by scripted fake
                                         BaseChatModel subclasses (bind_tools the only no-op
                                         override; every tool call goes through the real
                                         LangGraph ToolNode), proving N concurrent directed
                                         workers never double-claim a real WorkQueue task and
                                         rule-sweep/exploratory genuinely overlap in wall-clock
                                         time -- found and fixed the queue_candidate
                                         cross-connection race in the process. Plus 3 Phase 3
                                         tests proving the on_event streaming path produces the
                                         identical real outcome as .ainvoke(), correctly
                                         attributes interleaved concurrent workers' events
  test_orchestration_events.py           12 tests proving StreamEventTranslator (Phase 3):
                                          role attribution, the stack-based revert once a
                                          subagent's chain ends, Command vs ToolMessage output
                                          extraction -- pure, against synthetic events shaped
                                          like the real ones, no LLM
  test_orchestration_loop_control.py     9 tests proving evaluate_cycle's stop/continue
                                          decision and Constitution VI's conjunction, pure and
                                          deterministic, no LLM
  test_orchestration_assessment.py        3 tests proving run_assessment's full sequence end
                                           to end -- real indexing, real deterministic
                                           fallback, real concurrent detection, the loop
                                           correctly closing via directed-detection evidence,
                                           correctly stopping via the no-progress guard when it
                                           can't, and (Phase 3) that on_event streams live
                                           events through the whole real sequence without
                                           changing the real outcome
  test_api_store.py                       9 tests proving the in-memory AssessmentStore
                                           (Phase 3), including the structural guard that
                                           AssessmentRecord never grows a credential-shaped
                                           field, no HTTP, no LLM
  test_api_app.py                          15 tests proving the FastAPI backend (Phase 3) via
                                            TestClient with run_assessment monkeypatched --
                                            routing, validation, that neither the create nor
                                            the status response ever echoes the API key back,
                                            SSE formatting. Skips entirely (not fails) if the
                                            `fastapi`/`uvicorn`/`python-multipart` (the `[api]`
                                            extra) aren't installed
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
with Python/JavaScript-TypeScript/Java/Go). Phases 0-5 below are that plan;
it's done. A second, larger initiative continues past it (Phases 6-8):
correlating code vulnerabilities with the IaC/IAM governance around them,
to distinguish a finding that's actually exploitable (exposed, and running
under a real permission grant) from one that's contained by good
governance -- static, evidence-gated reasoning, not real dynamic
exploitation (a scope decision made explicitly with the user; see
`docs/CLOUD.md`). This is sequenced as:

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
- **Phase 3 (done)** — `src/foundry/api/`: a FastAPI backend wrapping
  `run_assessment` and `foundry.target.repo`, no logic duplicated.
  `POST /assessments` (file upload or GitHub URL, credentials, goals) runs
  in a background `asyncio.Task`; `GET .../status`, `GET .../events`
  (Server-Sent Events), `GET .../report` (the deterministic rollup, ahead
  of Phase 5's CISO-specific format). Live agent/tool visibility —
  the second of the five original asks — is now real: every subagent call
  `foundry.orchestration.agent_runner.run_single_subagent` makes can
  stream through `.astream_events()` instead of `.ainvoke()`
  (`foundry.orchestration.events.StreamEventTranslator` turns the raw
  LangGraph stream into clean `agent_start`/`tool_call`/`tool_result`
  events), and the SSE endpoint just tails the per-assessment event log
  those events feed. `openai_api_key` builds a real `ChatOpenAI` instance
  passed directly as `AssessmentConfig.model` — never a process-wide env
  var, which would race the moment two assessments used different keys.
  `GALILEO_API_KEY` is a documented exception (the `galileo` SDK's own
  config is a process-wide singleton) — see `docs/API.md`. Verified via
  FastAPI's `TestClient` with `run_assessment` monkeypatched (the
  orchestration layer's own correctness is already proven in
  `tests/test_orchestration_*.py`) plus one live run as a real `uvicorn`
  process, a real HTTP file upload over a real connection.
- **Phase 4 (done)** — `frontend/`: a real npm-managed Next.js 16 (App
  Router, Turbopack, TypeScript, Tailwind v4) project, sibling to `src/`,
  not embedded in the Python package. `lib/types.ts` mirrors the backend's
  own dataclasses by hand (no schema-generation step exists yet);
  `lib/api.ts` wraps `POST /assessments` (multipart `FormData`), `GET
  .../status`, and a `subscribeToEvents()` helper around the browser's
  native `EventSource` for `GET .../events` — listening for the default
  `message` event for progress and the backend's named `done` event to
  know when to fetch the final result. Three views in `app/page.tsx`'s own
  small state machine (`idle → starting → running → complete/failed`):
  `ConfigForm` (file upload / GitHub URL toggle, OpenAI key + model
  dropdown, operator goals, an advanced-options fieldset for Galileo
  credentials and the concurrency/cycle caps), `LiveEventFeed` (the SSE
  stream rendered newest-first), and `ResultsSummary` (the rollup plus a
  "Download CISO report" link straight to `GET .../report`). Credential
  discipline carries over from the backend: the API key lives only in
  the form's own React state, travels once in the `POST /assessments`
  body, and is never logged, persisted (no `localStorage`), or echoed back
  by anything the frontend renders. `src/foundry/api/app.py` gained
  `CORSMiddleware` (explicit origin allowlist via `FOUNDRY_CORS_ORIGINS`,
  default `http://localhost:3000` — not `"*"`, since naming the real
  origin costs nothing here) — without it a browser blocks every
  `fetch()`/`EventSource` call regardless of this being a local-only tool.

  Verified with `npm run build`/`npm run lint` (0 errors) and a genuine
  headless-Chromium Playwright run driving the real `next dev` server
  against a real `uvicorn` process (`run_assessment` monkeypatched to a
  fast fake — the same technique `tests/test_api_app.py` already uses,
  just outside pytest so a real browser could exercise a real HTTP/SSE
  round trip without a real OpenAI key): filled the form, uploaded a real
  file, watched live agent/tool events render, reached the results view,
  and fetched the report link's real content — confirming the uploaded
  key never appears anywhere in the rendered DOM. One non-obvious thing
  worth knowing if touching this again: Next.js dev's cross-origin
  protection treats `127.0.0.1` and `localhost` as different origins even
  though both resolve to the same dev server; browsing via `127.0.0.1`
  while the app itself uses relative URLs silently 403s the HMR
  WebSocket and static chunks, which manifests as controlled form inputs
  mysteriously reverting to their initial values (React re-renders,
  discarding the DOM's-only change, once the broken connection forces a
  remount) — not a bug in the form logic itself. Always drive local
  Next.js dev servers via `localhost`, not `127.0.0.1`.
- **Phase 5 (done)** — `ReporterStore.build_ciso_report()` (`src/foundry/
  reporter/store.py`): a CISO-ready markdown report built on the exact
  same aggregation `build_rollup` already uses (both now share one
  private `_gather()` pass, so the two formats can never disagree),
  restructured severity-first with deterministic remediation priorities
  and a coverage/scope statement, plus one LLM-authored executive-summary
  paragraph on top (`src/foundry/reporter/executive_summary.py`) --
  matching the Cartographer's FR-036a / Coverage-Guide's FR-073 "real
  call, deterministic fallback underneath" pattern already established in
  this codebase. The executive summary is one direct `model.ainvoke(...)`
  call, not a DeepAgents subagent turn (it runs after every real agent
  role has already finished, so a full subagent graph would be pure
  overhead for one paragraph) -- any failure (bad key, network, timeout,
  empty response) or an FR-083 denylist hit on the model's own output
  falls back to a deterministic paragraph instead, the same "fails soft"
  shape already used for Galileo tracing. `run_assessment` writes both
  `rollup.md` (unchanged, still what `AssessmentResult.rollup` carries)
  and `ciso_report.md` as its final step; `GET /assessments/{id}/report`
  now serves the latter. Verified with a scripted fake `BaseChatModel`
  covering both the real-summary and every fallback path (model absent,
  model raises, model returns empty text, model output fails the FR-083
  scan), plus an end-to-end assertion inside the existing full
  `run_assessment` proof that `ciso_report.md` actually lands on disk
  with the right structure -- 12 new tests (269 total).
- **Phase 6 (done)** — `src/foundry/cloud/`: IaC/IAM ingestion & structural
  indexing. `iac_parser.py` (Terraform via `python-hcl2`, the `[cloud]`
  extra; CloudFormation and Kubernetes manifests via `pyyaml`, content-
  sniffed since `.yaml`/`.json` alone can't tell them apart from unrelated
  config), `iam_parser.py` (standalone IAM policy documents, both bare and
  the `aws iam get-policy-version`-style wrapper), `store.py`
  (`CloudResourceStore`, same delete-then-insert-scoped-to-one-file shape
  as `IndexStore.write_index`), `tools.py` (read-only LangChain tool
  wrappers, first used by Phase 8). `TargetRepo` gains a `cloud_files`
  property (`src/foundry/target/repo.py`) — content-sniffed, lazily
  computed, so a file already known to be unsupported-as-code doesn't get
  re-read unless its extension is even a candidate. `run_assessment`
  indexes `config.target.cloud_files` in the same deterministic,
  no-model-call step as the existing code index. New fixture
  `data/cloud_toy_target/` (Terraform + a standalone IAM policy + a
  Kubernetes manifest, wired into one coherent over-permissioned-role
  scenario) exercises all three formats plus a self-contained vulnerable
  Lambda handler, for Phase 7/8 to build on. See `docs/CLOUD.md` for the
  full picture, including several real parsing gotchas found and fixed
  while building this (python-hcl2's 5.x+ output-shape change, plain
  `yaml.safe_load` having no constructor for CloudFormation's short-form
  intrinsic tags, and an initial bug where CloudFormation reference edges
  were wrongly typed using the *referencing* resource's own type instead
  of the target's). `hcl2` is imported lazily inside `parse_terraform`
  itself, not at module load time — `foundry.orchestration.assessment`
  imports from this package unconditionally, so a top-level import would
  have broken the harness for anyone without `[cloud]` installed. 35 new
  tests (306 total), 4 of them skipped (not failed) without `[cloud]`.
- **Phase 7 (not started)** — deterministic exposure & governance analysis:
  for each parsed cloud resource, is it network-exposed, and what does its
  attached identity's grants actually reach? No LLM, no code correlation
  yet — purely infra-side, building on Phase 6's reference/grant graph.
- **Phase 8 (not started)** — exploitability classification: correlates
  confirmed findings to Phase 6/7's infra graph (evidence-gated, allowed to
  conclude "not correlated" rather than guess), producing exploitable /
  contained / not-correlated per finding, with the reachable-resource set
  as blast-radius evidence for exploitable ones. Restructures the CISO
  report's findings section around this classification.

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
