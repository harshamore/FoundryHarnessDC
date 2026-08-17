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
- Reporter output: local markdown/JSON files, no issue-tracker integration
  yet.
- All 8 core roles planned, Validator degraded rather than merged/omitted.
  The 5 extension roles (Deep-Tester, Variant-Hunter, Attack-Mapper,
  Remediator, Self-Improver) are not built — per the spec's own
  recommendation for a first build.

## What's actually implemented right now

Only the **substrate** — the non-agent machinery every role will depend on —
and it has no LLM dependency at all:

```
src/foundry/
  config.py                    Settings: db path, CodeGuard rules dir, lease seconds
  substrate/
    db.py                      SQLite connection: WAL mode, schema, row access by name
    finding_store.py           Fingerprint, Citation, FindingStore — the evidence gate lives here
    work_queue.py               Atomic claim/lease/heartbeat/release
    budget.py                    Coverage-before-yield stop condition
data/
  codeguard/rules/             Vendored CodeGuard corpus (fetched, git-ignored — see scripts/)
  toy_target/vulnerable_app.py  Shared fixture target for every notebook from 02 onward
scripts/
  fetch_codeguard_rules.py     Pins and vendors the CodeGuard corpus
tests/
  test_finding_store.py        12 tests proving Constitution I/III/IV/VI/VIII mechanically
notebooks/
  00_setup.ipynb                Clone, install, fetch rules, enter OpenAI key
  01_substrate.ipynb            Same proofs as the test suite, run interactively
```

Nothing here calls an LLM. That's deliberate — the finding lifecycle,
atomic claims, and the stop condition need to be trustworthy on their own
before any agent touches them.

## What's next (roadmap, not yet built)

Each of these is its own Colab notebook, built one at a time, each starting
from the already-verified substrate above:

| Notebook | Adds |
|---|---|
| 02 | Indexer — parses `vulnerable_app.py`, exposes `get_function_body`/`get_callers`/`get_callees`/`find_symbol` as tools; first real OpenAI-backed DeepAgents subagent |
| 03 | Cartographer — security map (architecture, attack surface, trust boundaries) |
| 04 | Detector, rule-sweep half — CodeGuard `core/` rules wired in as tools |
| 05 | Detector, exploratory half — free-form hunting, coverage-log aware |
| 06 | Triager — `assign_verdict` tool wired to the real Indexer-backed resolver; a deliberately fabricated citation is used to prove the demotion path live, not just in pytest |
| 07 | Coverage-Guide + the real budget governor wired into a running fleet |
| 08 | Reporter — per-finding markdown + rollup, local files |
| 09 | Full pipeline — `create_deep_agent(...)` with all subagents wired together, end to end on the toy target, finding lifecycle inspected from SQLite |

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
