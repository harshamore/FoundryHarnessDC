# foundry-harness

An agentic security evaluation harness: [DeepAgents](https://github.com/langchain-ai/deepagents)
as the multi-agent runtime, [CodeGuard](https://github.com/cosai-oasis/project-codeguard)
as the Detector's rule corpus, built against Cisco's open-source [Foundry
Security Spec](https://github.com/CiscoDevNet/foundry-security-spec) and its
11-principle constitution.

**Status:** all eight core roles are built, tested, and wired into one
running pipeline — the substrate (finding store, work queue, budget
governor), Indexer, Cartographer, Detector (rule-sweep, exploratory, and
directed), Triager, Coverage-Guide, and Reporter. Coverage-Guide's
directed-detection loop is closed end to end (a live Detector actually
consumes and closes `WorkQueue` gaps, not just drains them), and a Full
Pipeline section wires all eight subagents into a single `create_deep_agent`
call instead of one per role. Optional Galileo AI tracing (automatic-only
scope, opt-in, fails soft) is wired into every real agent call — see
`docs/OBSERVABILITY.md`. Validator runs degraded (no testbed configured);
Orchestrator's lifecycle role is still the notebook's own `create_deep_agent`
calls, not a dedicated subagent with operator-approval gates.

Separately, this is being turned into a real product (frontend, live agent
visibility, real parallel execution, downloadable CISO reports, multi-language
support) — see `docs/ARCHITECTURE.md`'s "Toward a real product" section for
the full phased plan. Phase 0 (file-disambiguated indexing), Phase 1
(target ingestion from a file upload or a GitHub URL, plus a multi-language
parser for JavaScript/TypeScript/TSX/Java/Go alongside Python, plus
language-filtered CodeGuard rule-sweep), Phase 2 (a real async
orchestration layer — genuinely concurrent Detector instances, not one
call at a time; the real "index → map → detect → triage → check coverage
→ detect the gaps → repeat → report" loop, formalized as actual control
flow for the first time — Constitution V closed for real, not just
asserted), and Phase 3 (a FastAPI backend — `POST /assessments` accepting
a file upload or a GitHub URL, `GET .../events` streaming live agent/tool
activity over Server-Sent Events, `GET .../report`; see `docs/API.md`),
Phase 4 (a real Next.js frontend — `frontend/` — consuming that API: a
config form, a live SSE-driven event feed, a results view, and a
"Download CISO report" link), and Phase 5 (`ReporterStore.
build_ciso_report()` — a severity-led, remediation-prioritized markdown
report with an LLM-authored executive summary on top of the same
deterministic aggregation `build_rollup` uses, deterministic fallback
underneath if that call fails or trips the FR-083 denylist scan) are done
— see `src/foundry/target/repo.py`, `src/foundry/indexer/parser.py`,
`src/foundry/orchestration/`, `src/foundry/api/`, `frontend/`, and
`src/foundry/reporter/executive_summary.py`. The FastAPI backend is a
standalone surface (`uvicorn foundry.api.app:app`), not wired into the
Colab notebook — the notebook stays the reference/dev harness Phases 0-2
build on.

A second initiative continues past that plan (Phases 6-8), now also done:
correlating code vulnerabilities with the IaC/IAM governance around them,
to tell an exploitable finding (exposed, running under a real permission
grant) from one that's contained by good governance — static,
evidence-gated reasoning, not real dynamic exploitation (a scope decision
made explicitly with the user). Phase 6 (IaC/IAM ingestion — Terraform,
CloudFormation, Kubernetes manifests, IAM policy documents, all parsed
into a queryable `CloudResourceStore`, the infra-domain equivalent of the
Indexer), Phase 7 (deterministic exposure/governance analysis — is a
resource network-exposed, and what does its identity's grants actually
reach), and Phase 8 (exploitability classification — a new
exploitability-mapper subagent correlates confirmed findings to that
graph, classifying each exploitable/contained/not_correlated, evidence-
gated the same way `assign_verdict` is; restructures the CISO report's
findings around it) are all done — see `docs/CLOUD.md`.

See `docs/ARCHITECTURE.md` for the full picture and
`docs/CONSTITUTION_MAPPING.md` for how each constitution principle maps to
actual code.

## What's here

| Path | Contents |
|---|---|
| `src/foundry/substrate/` | `FindingStore` (evidence gate, fingerprinting), `WorkQueue` (atomic claim, heartbeat lease), `BudgetGovernor` (coverage-before-yield stop condition) |
| `src/foundry/indexer/` | `parser.py` (multi-language function inventory + call graph, no LLM — Python via `ast`, JS/TS/TSX/Java/Go via tree-sitter, class-qualified/deduped name collisions), `store.py` (query interface + the real evidence-gate resolver), `tools.py` (LangChain tool wrappers) |
| `src/foundry/cartographer/` | `store.py` (security map + digest, FR-035), `fallback.py` (per-section deterministic fallback, FR-036a, no LLM), `tools.py` (LangChain tool wrappers) |
| `src/foundry/codeguard/` | `loader.py` (parses the vendored rule corpus, FR-041; `load_rules(..., languages=...)` filters rule-sweep by the target's detected language, no LLM), `tools.py` (`list_rules`/`get_rule`) |
| `src/foundry/target/repo.py` | `from_upload()`/`from_github_url()` — build a `TargetRepo` from uploaded files or a validated, shallow-cloned public GitHub repo (command-injection-safe by construction, file-count/byte caps, dependency directories skipped), no LLM |
| `src/foundry/orchestration/` | `concurrency.py` (`run_bounded()`, a generic bounded-concurrency primitive), `agent_runner.py` (`run_single_subagent()` — `.ainvoke()` by default, `.astream_events()` when given an `on_event` callback), `events.py` (`StreamEventTranslator` — the raw LangGraph stream turned into clean live events), `detection.py` (genuinely concurrent Detector instances — broad rule-sweep+exploratory, N directed workers racing the real `WorkQueue`), `loop_control.py` (pure stop/continue decision logic), `assessment.py` (`run_assessment()` — the real full sequence, tying it all together) |
| `src/foundry/api/` | `store.py` (`AssessmentStore`, in-memory, no credential-shaped field ever), `app.py` (FastAPI: `POST /assessments`, `GET .../status`, `GET .../events` SSE, `GET .../report`) — see `docs/API.md` |
| `frontend/` | Next.js 16 app consuming the FastAPI backend: `lib/api.ts`/`lib/types.ts` (typed HTTP + SSE client), `components/ConfigForm.tsx`/`LiveEventFeed.tsx`/`ResultsSummary.tsx`, `app/page.tsx` (the idle→starting→running→complete/failed state machine). API key lives only in React state for the session, never logged or persisted |
| `src/foundry/cloud/` | Phases 6-8: `iac_parser.py` (Terraform/CloudFormation/Kubernetes, no LLM), `iam_parser.py` (IAM policy documents), `store.py` (`CloudResourceStore`), `detect.py` (content-sniffed IaC/IAM kind detection), `exposure.py`/`graph.py` (Phase 7: deterministic exposure classification + grant-reachability BFS, no LLM), `exploitability.py` (`ExploitabilityStore`, the Phase 8 evidence gate), `tools.py`/`exploitability_tools.py` (LangChain tool wrappers) — see `docs/CLOUD.md` |
| `src/foundry/agents/exploitability_mapper.py` | Phase 8's new role: correlates confirmed findings with Phase 6/7's cloud graph, classifying each exploitable/contained/not_correlated |
| `src/foundry/detector/tools.py` | `queue_candidate`/`record_rule_gap` — the Detector's only writes, both internal-only (Constitution II) — plus `build_directed_task_tools` (`claim_directed_task`/`complete_directed_task`), which consumes Coverage-Guide's queued gaps and always leaves a coverage-log sweep as evidence, whether or not anything was found |
| `src/foundry/triager/tools.py` | `list_candidates`/`get_candidate`/`assign_verdict` — `assign_verdict` binds the real Indexer resolver as a closure the model can't see or influence |
| `src/foundry/coverage/` | `store.py` (`CoverageStore`: the whole FR-067/069/070/071/074 mechanism, no LLM), `tools.py` (one read-only tool, `get_coverage_report`) |
| `src/foundry/reporter/` | `classification.py` (CWE lookup + the FR-083 denylist scan, no LLM), `store.py` (`ReporterStore`: FR-079/081/083 enforced structurally; `build_ciso_report()` is Phase 5's CISO-ready report), `executive_summary.py` (the report's one LLM-authored paragraph, deterministic fallback underneath), `tools.py` (LangChain tool wrappers) |
| `src/foundry/observability/galileo.py` | Optional Galileo AI tracing, automatic-only scope — `build_galileo_callback()`/`galileo_run_config()`/`console_url()`. Wired only at `agent.invoke()` call sites; touches no Substrate or role store. `None`/no-op whenever `GALILEO_API_KEY` isn't set, never raises even when set and unreachable |
| `src/foundry/agents/` | All eight core roles' SubAgents (Indexer, Cartographer, Detector ×3 — rule-sweep, exploratory, directed —, Triager, Coverage-Guide, Reporter), plus `_middleware.py`'s shared filesystem-tool restriction |
| `tests/` (26 files) | 354 tests total (4 skip, not fail, without the `[cloud]` extra) proving the constitution's I/II/III/IV/V/VI/VIII/XI principles and FR-020/021/022/025/026/031/041/042/054/067/068/069/070/071/074/076/079/081/083, mechanically where possible, and — for Phase 2/3's real concurrency and streaming, and Phase 8's exploitability mapper — via scripted fake chat models driving real DeepAgents graphs, and FastAPI's `TestClient`, rather than mocking around the frameworks; no external network calls |
| `data/codeguard/rules/` | Vendored CodeGuard rule corpus (fetched, not committed — run `scripts/fetch_codeguard_rules.py`) |
| `data/toy_target/vulnerable_app.py` | Small deliberately-vulnerable Flask app; the shared Python target every notebook section parses/queries |
| `data/multi_lang_toy_target/` | Phase 1's multi-language sibling — one small deliberately-vulnerable file per non-Python supported language |
| `data/cloud_toy_target/` | Phase 6's IaC/IAM sibling — Terraform + a standalone IAM policy + a Kubernetes manifest, wired into one coherent over-permissioned-role scenario, plus a self-contained vulnerable Lambda handler |
| `notebooks/01_substrate.ipynb` | The single, growing Colab notebook — setup, observability, substrate, and every role's section get appended here as they're built |
| `docs/ARCHITECTURE.md` | Full writeup: shape, roadmap, quickstart |
| `docs/CONSTITUTION_MAPPING.md` | Principle → enforcing code, updated as each piece lands |
| `docs/CODEGUARD_INTEGRATION.md` | How the rule corpus is fetched, pinned, and (eventually) consumed by the Detector |
| `docs/OBSERVABILITY.md` | Galileo integration: scope, trace/span mapping, opt-in/fail-soft design, constraints (free-tier trace budget, SaaS data exposure) |
| `docs/API.md` | The FastAPI backend: routes, live event streaming, credential handling, the Galileo process-wide-config caveat, what `/report` serves (Phase 5's CISO report) |
| `docs/CLOUD.md` | Phases 6-8: IaC/IAM ingestion, deterministic exposure/reachability analysis, and exploitability classification — what's parsed, every real gotcha found while building it (python-hcl2's version-dependent output shape, CloudFormation's short-form intrinsic tags, the identity-resource-as-workload bug), and the evidence gate `ExploitabilityStore` enforces |

## Quickstart (local)

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/fetch_codeguard_rules.py
.venv/bin/python -m pytest tests/ -v
```

No API key needed for any of the above. `pip install -e ".[dev,observability]"` additionally installs the `galileo` SDK if you want `tests/test_observability.py`'s positive-path tests to run instead of skip — still no real Galileo account or network call needed for tests either way. `pip install -e ".[dev,cloud]"` similarly installs `python-hcl2` for `tests/test_cloud_parser.py`'s Terraform-specific tests (CloudFormation/Kubernetes/IAM tests in that same file need nothing extra and always run) — see `docs/CLOUD.md`.

## Quickstart (API)

```sh
pip install -e ".[dev,api]"
uvicorn foundry.api.app:app --reload
```

Then `POST /assessments` (multipart form: `openai_api_key`, `operator_goals`,
and either `files` or `github_url`) — see `docs/API.md` for the full route
reference, the live event-streaming design, and the credential-handling
approach (a real `ChatOpenAI` instance per assessment, never a process-wide
env var).

## Quickstart (Colab)

Open `notebooks/01_substrate.ipynb` in Colab — this is the **one notebook**
the whole harness gets built in. Section 1 (Setup) clones this repo,
installs dependencies, fetches the CodeGuard rules, and prompts for an
OpenAI key via `getpass` (not stored). Section 2 (Observability) optionally
prompts for a Galileo API key via `getpass` — leave it blank to skip
entirely; every later section runs identically either way, just untraced.
If a key is entered, every real agent call from here on is captured as a
Galileo trace, tagged by role — see `docs/OBSERVABILITY.md`. Section 3
(Substrate) runs the same proofs as the test suite, interactively, no
OpenAI calls yet. Section 4 (Indexer) parses the toy target
deterministically, then makes a real OpenAI call delegating a question to
the Indexer subagent. Section 5 (Cartographer) writes a deterministic
fallback for every security-map section first (FR-036a — the map is never
empty), then a real OpenAI call lets the Cartographer subagent overwrite
those with actual analysis. Section 6 (Detector) loads the CodeGuard rule
corpus, then makes two real OpenAI calls — rule-sweep (systematic, checks
every function against the corpus) and exploratory hunting (free-form,
front-loaded with the Cartographer's security-map digest) — queuing
candidate findings into SQLite. Section 7 (Triager) makes one more real
OpenAI call, investigating every queued candidate and assigning verdicts
through the same evidence gate the Substrate section proved standalone —
a citation naming a symbol that doesn't actually exist gets auto-demoted
from `true-positive` to `needs-review`, live. Section 8 (Coverage-Guide)
builds and checks a coverage checklist mechanically (no OpenAI call needed
for any of it), wires the result directly into the Substrate section's
`BudgetGovernor` — closing Constitution VI end to end with real inputs
instead of hand-typed booleans — then makes one real OpenAI call for a
short remaining-work narrative. Section 9 (Reporter), the last core role,
publishes a self-contained report for every `true-positive` finding and a
rollup — with two live demos of its own: publishing a `needs-review`
finding gets rejected outright, and publishing a report that names the
model or provider gets rejected too, both before anything is written to
disk. Each real call costs a small real amount on `gpt-5.6-luna`. Section
10 (Full Pipeline) closes the two pieces deliberately deferred earlier: a
real `detector-directed` subagent claims and investigates every
directed-detection task Coverage-Guide queued, closing each coverage-
checklist item with a permanent evidence record whether or not anything
was found (not just draining the queue) — then all eight subagents get
wired into a single `create_deep_agent(...)` call, the actual shape an
Orchestrator wires up, rather than one call per role. Any future work gets
appended the same way — every section in this same notebook, never a
separate file, so nothing later ever loses the environment setup
established.

## Attribution

The Foundry Security Spec and constitution (reproduced unmodified in
`../trial-run/`) are © 2026 Cisco Systems, Inc., CC BY 4.0. The CodeGuard
rule corpus is © the Project CodeGuard contributors, CC BY 4.0 — see
`data/codeguard/ATTRIBUTION.md`. Everything under `src/`, `scripts/`,
`tests/`, and `notebooks/` is this project's own code.
