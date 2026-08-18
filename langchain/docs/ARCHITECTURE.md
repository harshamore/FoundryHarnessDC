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

All eight core roles from spec.md §4.2 (Orchestrator's lifecycle role is
this notebook's own `create_deep_agent` calls, one per section — no
dedicated Orchestrator subagent was built; Validator runs degraded, no
testbed):

```
src/foundry/
  config.py                    Settings: db path, CodeGuard rules dir, lease seconds
  substrate/
    db.py                      SQLite connection: WAL mode, schema, row access by name
    finding_store.py           Fingerprint, Citation, FindingStore — the evidence gate lives here
                                (now rejects a bare verdict with no report, FR-054);
                                also record_rule_gap/list_rule_gaps (FR-042), list_untriaged,
                                list_by_verdict
    work_queue.py               Atomic claim/lease/heartbeat/release — now consumed for real
                                 by Coverage-Guide's directed tasks (FR-070), not just its own
                                 concurrency tests
    budget.py                    Coverage-before-yield stop condition — now fed a real
                                  coverage-complete flag, not a hand-typed boolean
  indexer/
    parser.py                    AST-based function inventory (decorators included, e.g. Flask
                                  `@app.route(...)`, for FR-031) + direct-call graph (FR-020/021,
                                  decorators deliberately excluded here) — no model call
    store.py                      Persists the index; the query interface (FR-022); the real evidence-gate resolver
    tools.py                       LangChain tool wrappers around the store
  cartographer/
    store.py                       Persists the security map + digest (FR-035)
    fallback.py                     Deterministic per-section fallback (FR-036a) — no model call
    tools.py                         LangChain tool wrappers, one per section (FR-030–034)
  codeguard/
    loader.py                       Parses the vendored rule corpus (FR-041) — no model call
    tools.py                         LangChain tool wrappers: list_rules, get_rule
  detector/
    tools.py                        LangChain tool wrappers: queue_candidate, record_rule_gap
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
    detector.py                       Two SubAgent dicts: rule-sweep (FR-037) and
                                       exploratory (FR-040)
    triager.py                         The Triager as a DeepAgents SubAgent dict
    coverage_guide.py                   The Coverage-Guide as a DeepAgents SubAgent dict
                                         (FR-073 only — the narrative, not the mechanism)
    reporter.py                          The Reporter as a DeepAgents SubAgent dict
data/
  codeguard/rules/             Vendored CodeGuard corpus (fetched, git-ignored — see scripts/)
  toy_target/vulnerable_app.py  Shared fixture target every notebook section parses/queries
  reports/                       Generated by the Reporter section: one markdown file per
                                  published finding + rollup.md (git-ignored, regenerated per run)
scripts/
  fetch_codeguard_rules.py     Pins and vendors the CodeGuard corpus
tests/
  test_finding_store.py        13 tests proving Constitution I/III/IV/VI/VIII mechanically
  test_indexer.py               17 tests proving FR-020/021/022/025/026, the real resolver,
                                 the filesystem-tool restriction, and decorator capture, no LLM
  test_cartographer.py           12 tests proving FR-036a's fallback guarantee, the digest, and
                                  the filesystem-tool restriction, no LLM
  test_codeguard.py               9 tests proving the rule corpus loads and parses correctly, no LLM
  test_detector.py                 8 tests proving the tool wrappers, both SubAgent shapes, and
                                    the front-loaded security-map digest, no LLM
  test_triager.py                  12 tests proving FR-054, the evidence-gate demotion through
                                    the tool layer (not just FindingStore directly), and the
                                    SubAgent shape, no LLM
  test_coverage.py                  18 tests proving FR-067/068/069/070/071/074 and a direct
                                     integration test wiring CoverageStore to the real
                                     BudgetGovernor, no LLM
  test_reporter.py                   23 tests proving FR-079/081/083 and the FR-078/080
                                      overwrite-not-duplicate behavior, no LLM
notebooks/
  01_substrate.ipynb            The single, growing Colab notebook: Setup, Substrate,
                                 Indexer, Cartographer, Detector, Triager, Coverage-Guide,
                                 and Reporter sections — all eight core roles, in one file,
                                 never a separate notebook per role
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
any of it. Seven real OpenAI calls exist in this build now (Indexer,
Cartographer, Detector rule-sweep, Detector exploratory, Triager,
Coverage-Guide, Reporter), each a small `create_deep_agent` main agent
delegating through the `task` tool to prove the tool interface is usable
by an LLM, not just by pytest.

**Deferred by design, not forgotten**: FR-038 (dependency scanning) is
skipped for the same reason FR-039 (secret scanning) mostly overlaps with
CodeGuard's own `hardcoded-credentials` rule: the toy target has no
third-party dependency manifest to scan. `queue_directed_tasks` (FR-070)
writes real, claimable tasks to the `WorkQueue`, but nothing in this
notebook actually consumes them with a live Detector `claim_next()` call —
this was raised explicitly with the user, who asked to finish Reporter
first and then come back to it; it's the first thing to revisit, likely
alongside or just before the Full Pipeline section. FR-046 (exploratory
Detector instances consult the coverage log before choosing an area) is
half-addressed the same way: the `coverage_log` table and
`CoverageStore.record_sweep()` exist, but the Detector's exploratory
subagent doesn't call it yet. FR-084 (every code location a permalink that
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

All eight core roles are built. Everything from here on is still a new
**section appended to `01_substrate.ipynb`**, not a separate notebook:

| Section | Adds |
|---|---|
| Coverage-Guide loop closure | A live Detector actually consuming `WorkQueue` directed-detection tasks via `claim_next()`, instead of `queue_directed_tasks` writing to a queue nothing reads |
| Full pipeline | `create_deep_agent(...)` with all subagents wired together, end to end on the toy target, finding lifecycle inspected from SQLite |

Constitution IX (sandbox by infrastructure) and the parts of III/V that only
matter under a real multi-process fleet are explicitly deferred past the
Colab phase — see `docs/CONSTITUTION_MAPPING.md`.

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
