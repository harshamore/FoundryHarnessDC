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
call instead of one per role. Validator runs degraded (no testbed
configured); Orchestrator's lifecycle role is still the notebook's own
`create_deep_agent` calls, not a dedicated subagent with operator-approval
gates — see `docs/ARCHITECTURE.md` for the full picture and
`docs/CONSTITUTION_MAPPING.md` for how each constitution principle maps to
actual code.

## What's here

| Path | Contents |
|---|---|
| `src/foundry/substrate/` | `FindingStore` (evidence gate, fingerprinting), `WorkQueue` (atomic claim, heartbeat lease), `BudgetGovernor` (coverage-before-yield stop condition) |
| `src/foundry/indexer/` | `parser.py` (AST-based function inventory, decorators included, + call graph, no LLM), `store.py` (query interface + the real evidence-gate resolver), `tools.py` (LangChain tool wrappers) |
| `src/foundry/cartographer/` | `store.py` (security map + digest, FR-035), `fallback.py` (per-section deterministic fallback, FR-036a, no LLM), `tools.py` (LangChain tool wrappers) |
| `src/foundry/codeguard/` | `loader.py` (parses the vendored rule corpus, FR-041, no LLM), `tools.py` (`list_rules`/`get_rule`) |
| `src/foundry/detector/tools.py` | `queue_candidate`/`record_rule_gap` — the Detector's only writes, both internal-only (Constitution II) — plus `build_directed_task_tools` (`claim_directed_task`/`complete_directed_task`), which consumes Coverage-Guide's queued gaps and always leaves a coverage-log sweep as evidence, whether or not anything was found |
| `src/foundry/triager/tools.py` | `list_candidates`/`get_candidate`/`assign_verdict` — `assign_verdict` binds the real Indexer resolver as a closure the model can't see or influence |
| `src/foundry/coverage/` | `store.py` (`CoverageStore`: the whole FR-067/069/070/071/074 mechanism, no LLM), `tools.py` (one read-only tool, `get_coverage_report`) |
| `src/foundry/reporter/` | `classification.py` (CWE lookup + the FR-083 denylist scan, no LLM), `store.py` (`ReporterStore`: FR-079/081/083 enforced structurally), `tools.py` (LangChain tool wrappers) |
| `src/foundry/agents/` | All eight core roles' SubAgents (Indexer, Cartographer, Detector ×3 — rule-sweep, exploratory, directed —, Triager, Coverage-Guide, Reporter), plus `_middleware.py`'s shared filesystem-tool restriction |
| `tests/` (9 files) | 122 tests total proving the constitution's I/II/III/IV/VI/VIII/XI principles and FR-020/021/022/025/026/031/041/042/054/067/068/069/070/071/074/076/079/081/083, mechanically, no LLM |
| `data/codeguard/rules/` | Vendored CodeGuard rule corpus (fetched, not committed — run `scripts/fetch_codeguard_rules.py`) |
| `data/toy_target/vulnerable_app.py` | Small deliberately-vulnerable Flask app; the shared target every section parses/queries |
| `notebooks/01_substrate.ipynb` | The single, growing Colab notebook — setup, substrate, and every role's section get appended here as they're built |
| `docs/ARCHITECTURE.md` | Full writeup: shape, roadmap, quickstart |
| `docs/CONSTITUTION_MAPPING.md` | Principle → enforcing code, updated as each piece lands |
| `docs/CODEGUARD_INTEGRATION.md` | How the rule corpus is fetched, pinned, and (eventually) consumed by the Detector |

## Quickstart (local)

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/fetch_codeguard_rules.py
.venv/bin/python -m pytest tests/ -v
```

No API key needed for any of the above.

## Quickstart (Colab)

Open `notebooks/01_substrate.ipynb` in Colab — this is the **one notebook**
the whole harness gets built in. Section 1 (Setup) clones this repo,
installs dependencies, fetches the CodeGuard rules, and prompts for an
OpenAI key via `getpass` (not stored). Section 2 (Substrate) runs the same
proofs as the test suite, interactively, no OpenAI calls yet. Section 3
(Indexer) parses the toy target deterministically, then makes a real OpenAI
call delegating a question to the Indexer subagent. Section 4 (Cartographer)
writes a deterministic fallback for every security-map section first
(FR-036a — the map is never empty), then a real OpenAI call lets the
Cartographer subagent overwrite those with actual analysis. Section 5
(Detector) loads the CodeGuard rule corpus, then makes two real OpenAI
calls — rule-sweep (systematic, checks every function against the corpus)
and exploratory hunting (free-form, front-loaded with the Cartographer's
security-map digest) — queuing candidate findings into SQLite. Section 6
(Triager) makes one more real OpenAI call, investigating every queued
candidate and assigning verdicts through the same evidence gate the
Substrate section proved standalone — a citation naming a symbol that
doesn't actually exist gets auto-demoted from `true-positive` to
`needs-review`, live. Section 7 (Coverage-Guide) builds and checks a
coverage checklist mechanically (no OpenAI call needed for any of it),
wires the result directly into the Substrate section's `BudgetGovernor` —
closing Constitution VI end to end with real inputs instead of hand-typed
booleans — then makes one real OpenAI call for a short remaining-work
narrative. Section 8 (Reporter), the last core role, publishes a
self-contained report for every `true-positive` finding and a rollup —
with two live demos of its own: publishing a `needs-review` finding gets
rejected outright, and publishing a report that names the model or
provider gets rejected too, both before anything is written to disk. Each
real call costs a small real amount on `gpt-5.6-luna`. Section 9 (Full
Pipeline) closes the two pieces deliberately deferred earlier: a real
`detector-directed` subagent claims and investigates every
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
