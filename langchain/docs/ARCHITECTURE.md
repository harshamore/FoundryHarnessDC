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

The **substrate** (no LLM dependency at all) plus the **Indexer** (deterministic parsing, one real OpenAI-backed subagent call):

```
src/foundry/
  config.py                    Settings: db path, CodeGuard rules dir, lease seconds
  substrate/
    db.py                      SQLite connection: WAL mode, schema, row access by name
    finding_store.py           Fingerprint, Citation, FindingStore — the evidence gate lives here
    work_queue.py               Atomic claim/lease/heartbeat/release
    budget.py                    Coverage-before-yield stop condition
  indexer/
    parser.py                    AST-based function inventory + direct-call graph (FR-020/021) — no model call
    store.py                      Persists the index; the query interface (FR-022); the real evidence-gate resolver
    tools.py                       LangChain tool wrappers around the store
  agents/
    indexer.py                     The Indexer as a DeepAgents SubAgent dict
data/
  codeguard/rules/             Vendored CodeGuard corpus (fetched, git-ignored — see scripts/)
  toy_target/vulnerable_app.py  Shared fixture target every notebook section parses/queries
scripts/
  fetch_codeguard_rules.py     Pins and vendors the CodeGuard corpus
tests/
  test_finding_store.py        12 tests proving Constitution I/III/IV/VI/VIII mechanically
  test_indexer.py               12 tests proving FR-020/021/022/025/026 and the real resolver, no LLM
notebooks/
  01_substrate.ipynb            The single, growing Colab notebook: Setup, Substrate, and
                                 Indexer sections so far, with every future role appended
                                 below as its own section — never a separate file
```

The Indexer's actual indexing (parsing, call graph, persistence, queries) has
no LLM dependency — FR-020 requires a deterministic parser, not model
extraction. The one real OpenAI call in this build so far is the Indexer
section's closing demo: a small `create_deep_agent` main agent delegating a
question to the Indexer subagent through the `task` tool, to prove the query
interface is actually usable by an LLM, not just by pytest.

## What's next (roadmap, not yet built)

Everything from here on is a new **section appended to `01_substrate.ipynb`**
— Setup, Substrate, and Indexer are already sections one through three of
that same file, not separate notebooks. That keeps the whole build in one
Colab runtime, so a later section never loses the environment (installed
packages, OpenAI key, in-progress SQLite database) an earlier section set
up. Each section still starts from the already-verified index above:

| Section | Adds |
|---|---|
| Cartographer | Security map (architecture, attack surface, trust boundaries) |
| Detector, rule-sweep half | CodeGuard `core/` rules wired in as tools |
| Detector, exploratory half | Free-form hunting, coverage-log aware |
| Triager | `assign_verdict` tool wired to the real Indexer-backed resolver; a deliberately fabricated citation is used to prove the demotion path live, not just in pytest |
| Coverage-Guide | The real budget governor wired into a running fleet |
| Reporter | Per-finding markdown + rollup, local files |
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
