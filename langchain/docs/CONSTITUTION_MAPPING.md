# Constitution → mechanism mapping

The Foundry constitution (`trial-run/.specify/memory/constitution.md`, 11
principles) constrains the system's *design*, not just its prompts. This
table is the running record of where each principle is actually enforced in
code — updated as each notebook/module lands. "Not yet built" means the
principle applies to a piece that hasn't been implemented in this phase.

| Principle | Mechanism | Where |
|---|---|---|
| I. Evidence Over Assertion | `FindingStore.assign_verdict()` resolves every citation against a caller-supplied `resolver` before accepting `true-positive`; an unresolved citation force-demotes to `needs-review`, with the mismatch recorded in the report. The resolver is now the real Indexer (`IndexStore.symbol_exists()`), not the Substrate section's hand-typed stand-in | `src/foundry/substrate/finding_store.py`, real resolver in `src/foundry/indexer/store.py`, proved in `tests/test_indexer.py::test_real_resolver_wired_into_evidence_gate` |
| II. Surface Only What Survives | Not yet built — lands with the Detector/Reporter subagent definitions: Detector's `tools` list will have no path to a human-visible output, only `queue_candidate`. The Indexer subagent already demonstrates the pattern in miniature: its tool list is read-only query, nothing that writes anywhere | `src/foundry/agents/indexer.py` (pattern only, not the enforcing case) |
| III. Liveness By Heartbeat, Never By Clock | `WorkQueue.claim_next()` only reclaims a row whose `leased_until` has passed; nothing reclaims on wall-clock agent runtime | `src/foundry/substrate/work_queue.py`, proved in `tests/test_finding_store.py::test_stale_lease_is_reclaimable` / `::test_fresh_lease_is_not_reclaimable` |
| IV. Claims Are Atomic And Mortal | `claim_next()` is a single `BEGIN IMMEDIATE` transaction that re-checks its own WHERE clause on the UPDATE | `src/foundry/substrate/work_queue.py`, proved under real concurrent threads in `tests/test_finding_store.py::test_concurrent_claims_never_double_claim` |
| V. The Provider Is The Rate Arbiter | The Indexer section makes the build's first real OpenAI call, but it's a single request — doesn't exercise concurrency/backoff behavior. Not yet built: no internal concurrency cap below OpenAI's actual limit, rely on LangChain's retry/backoff. Lands meaningfully with the Detector's rule-sweep (many concurrent LLM calls, one per function) | — |
| VI. Coverage Before Yield | `BudgetGovernor.should_stop()` is a strict conjunction: `coverage_complete AND yield < threshold` (or a hard spend cap); low yield alone never returns `True` while coverage is incomplete | `src/foundry/substrate/budget.py`, proved in `tests/test_finding_store.py::test_low_yield_alone_does_not_stop_when_coverage_incomplete` |
| VII. Exploited Means Demonstrated | Not yet built — lands with the Validator subagent. Source-only phase: the `mark_exploited` tool simply does not exist until a testbed is configured (degraded mode, FR-066) | — |
| VIII. Fingerprints Are Stable Under Edit | `fingerprint()` hashes `(normalized_path, symbol, vulnerability_class)` only — never a line number or snippet | `src/foundry/substrate/finding_store.py`, proved in `tests/test_finding_store.py::test_requeueing_same_identity_deduplicates_despite_edited_description` |
| IX. Sandbox By Infrastructure, Not By Prompt | **Explicitly out of scope for the Colab phase** — flagged as a real gap, not faked. Addressed later via `deepagents`' `permissions`/`backend` (defense in depth) plus real container/network isolation once a testbed exists | — |
| X. The Operator Outranks Every Agent | Not yet built — lands with the Orchestrator (final notebook): `mark_coverage_complete` and `override_verdict` tools registered with DeepAgents' `interrupt_on`, requiring explicit operator approval | — |
| XI. Persist Atomically | Every substrate write goes through `BEGIN IMMEDIATE` / `COMMIT` (or SQLite's autocommit for single-statement writes with WAL); nothing is ever deleted-then-rewritten | `src/foundry/substrate/db.py`, `finding_store.py`, `work_queue.py` |

Principles II, V, VII, IX, X depend on the LLM-agent layer (Indexer onward)
and are not testable without it — they're listed here as commitments this
build owes itself, not as claims already proven.
