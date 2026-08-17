# foundry-harness

An agentic security evaluation harness: [DeepAgents](https://github.com/langchain-ai/deepagents)
as the multi-agent runtime, [CodeGuard](https://github.com/cosai-oasis/project-codeguard)
as the Detector's rule corpus, built against Cisco's open-source [Foundry
Security Spec](https://github.com/CiscoDevNet/foundry-security-spec) and its
11-principle constitution.

**Status:** the substrate (finding store, work queue, budget governor) is
built and tested — no LLM calls yet. The agent layer (Indexer onward) is a
roadmap, built one notebook at a time. See `docs/ARCHITECTURE.md` for the
full picture and `docs/CONSTITUTION_MAPPING.md` for how each constitution
principle maps to actual code.

## What's here

| Path | Contents |
|---|---|
| `src/foundry/substrate/` | `FindingStore` (evidence gate, fingerprinting), `WorkQueue` (atomic claim, heartbeat lease), `BudgetGovernor` (coverage-before-yield stop condition) |
| `tests/test_finding_store.py` | 12 tests proving the constitution's III/IV/VI/VIII/I principles mechanically, no LLM |
| `data/codeguard/rules/` | Vendored CodeGuard rule corpus (fetched, not committed — run `scripts/fetch_codeguard_rules.py`) |
| `data/toy_target/vulnerable_app.py` | Small deliberately-vulnerable Flask app used as the shared target from notebook 02 onward |
| `notebooks/` | Colab-executable, one section per role, cumulative |
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

Open `notebooks/00_setup.ipynb` in Colab — it clones this repo, installs
dependencies, fetches the CodeGuard rules, and prompts for an OpenAI key via
`getpass` (not stored). Then `notebooks/01_substrate.ipynb` runs the same
proofs as the test suite, interactively, with no OpenAI calls yet.

## Attribution

The Foundry Security Spec and constitution (reproduced unmodified in
`../trial-run/`) are © 2026 Cisco Systems, Inc., CC BY 4.0. The CodeGuard
rule corpus is © the Project CodeGuard contributors, CC BY 4.0 — see
`data/codeguard/ATTRIBUTION.md`. Everything under `src/`, `scripts/`,
`tests/`, and `notebooks/` is this project's own code.
