"""The Triager role (spec.md §5.5) as a DeepAgents SubAgent -- "the noise
filter": investigates each candidate the Detector queued and assigns a
verdict, gated on structural evidence.

Unlike the Indexer/Cartographer/Detector sections, this section adds no new
enforcement mechanism of its own. `FindingStore.assign_verdict()`'s evidence
gate (Constitution I) has been built and tested since the Substrate section,
first against a hand-typed fake resolver, then against the real
Indexer-backed one once the Indexer existed. This subagent is what finally
calls it live: a real agent, investigating real candidates, whose citations
either resolve against real code or get auto-demoted -- the same gate,
now under its intended load instead of a notebook cell asserting on it.
"""
from __future__ import annotations

from foundry.agents._middleware import (
    NO_FILESYSTEM_EXPLORATION_WARNING,
    minimal_filesystem_middleware,
)
from foundry.indexer.store import IndexStore
from foundry.indexer.tools import build_index_tools
from foundry.substrate.finding_store import FindingStore
from foundry.triager.tools import build_triager_tools


def build_triager_subagent(
    finding_store: FindingStore, index: IndexStore, security_map_digest: str
) -> dict:
    system_prompt = f"""\
You are the Triager role in a security-evaluation harness (spec.md §5.5) -- \
the noise filter. Most candidates the Detector queues are not real; your \
job is to establish which ones are, with evidence, before any human sees \
them.

Call list_candidates to see what needs triaging, then for each one: read \
the implicated code (get_function_body), trace the data flow using the \
call graph (get_callers/get_callees), and reason about reachability from \
an attacker-controlled entry point using the security map below (FR-051).

You MUST NOT assign true-positive by judgment alone. Call assign_verdict \
with citations that establish reachability, a trust-boundary crossing, and \
concrete impact -- each citation is a {{path, symbol, claim}} object, and \
every one is checked against the real index. A citation naming a symbol \
that doesn't actually exist gets your true-positive automatically demoted \
to needs-review, no matter how confident your reasoning sounds (spec.md \
FR-052/FR-088, Constitution I: Evidence Over Assertion) -- so only cite \
symbols you actually confirmed via get_function_body/find_symbol, never \
ones you assume exist. If you believe a candidate is real but can't back \
it with citations that will actually resolve, assign needs-review \
honestly rather than true-positive (FR-053) -- that verdict exists exactly \
for this case. investigation_report must be non-empty and explain your \
actual reasoning (FR-054); a bare label is rejected by the tool itself.

Security map (spec.md FR-035 digest, produced by the Cartographer):
{security_map_digest}

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""
    return {
        "name": "triager",
        "description": (
            "Investigates each queued candidate finding and assigns a "
            "verdict, gated on citations that resolve to real code -- "
            "never true-positive on unverified judgment alone."
        ),
        "system_prompt": system_prompt,
        "tools": [*build_index_tools(index), *build_triager_tools(finding_store, index)],
        "middleware": [minimal_filesystem_middleware()],
    }
