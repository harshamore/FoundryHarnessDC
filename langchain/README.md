# foundry-harness

An agentic security evaluation harness: [DeepAgents](https://github.com/langchain-ai/deepagents)
as the multi-agent runtime, [CodeGuard](https://github.com/cosai-oasis/project-codeguard)
as the Detector's rule corpus, built against Cisco's open-source [Foundry
Security Spec](https://github.com/CiscoDevNet/foundry-security-spec) and its
11-principle constitution.

**Status:** the substrate (finding store, work queue, budget governor) and
the Indexer (deterministic parser, query interface, first real OpenAI-backed
DeepAgents subagent) are built and tested. Cartographer onward is a roadmap,
built one notebook section at a time. See `docs/ARCHITECTURE.md` for the
full picture and `docs/CONSTITUTION_MAPPING.md` for how each constitution
principle maps to actual code.

## What's here

| Path | Contents |
|---|---|
| `src/foundry/substrate/` | `FindingStore` (evidence gate, fingerprinting), `WorkQueue` (atomic claim, heartbeat lease), `BudgetGovernor` (coverage-before-yield stop condition) |
| `src/foundry/indexer/` | `parser.py` (AST-based function inventory + call graph, no LLM), `store.py` (query interface + the real evidence-gate resolver), `tools.py` (LangChain tool wrappers) |
| `src/foundry/agents/indexer.py` | The Indexer as a DeepAgents `SubAgent` |
| `tests/test_finding_store.py`, `tests/test_indexer.py` | 24 tests total proving the constitution's I/III/IV/VI/VIII principles and FR-020/021/022/025/026 mechanically, no LLM |
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
(Indexer) parses the toy target deterministically, then makes this build's
first real OpenAI call — a small `create_deep_agent` delegating a question
to the Indexer subagent, costing a small real amount on `gpt-5.6-luna`.
Every later role (Cartographer, Detector, ...) gets appended as a new
section in this same notebook, not a separate file — so nothing later ever
loses the environment setup established.

## Attribution

The Foundry Security Spec and constitution (reproduced unmodified in
`../trial-run/`) are © 2026 Cisco Systems, Inc., CC BY 4.0. The CodeGuard
rule corpus is © the Project CodeGuard contributors, CC BY 4.0 — see
`data/codeguard/ATTRIBUTION.md`. Everything under `src/`, `scripts/`,
`tests/`, and `notebooks/` is this project's own code.
