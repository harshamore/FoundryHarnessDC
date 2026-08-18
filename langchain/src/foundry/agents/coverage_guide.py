"""The Coverage-Guide role (spec.md §5.7) as a DeepAgents SubAgent.

Every MUST-level requirement (FR-067 derive checklist, FR-069 check off
from evidence, FR-070 directed tasks, FR-071 the coverage-complete flag,
FR-074 persist without rebuilding) is deterministic and lives in
`foundry.coverage.store.CoverageStore`, exercised directly -- not through
this subagent. "Coverage measures attempt, not outcome" is a mechanical
evidence check, the same way `BudgetGovernor.should_stop()` is a mechanical
conjunction, neither needs model judgment. The one place an LLM genuinely
helps is FR-073 (SHOULD, not MUST): a short estimate of remaining work with
a one-line basis, for the operator's planning -- that's what this subagent
produces.
"""
from __future__ import annotations

from foundry.agents._middleware import (
    NO_FILESYSTEM_EXPLORATION_WARNING,
    minimal_filesystem_middleware,
)
from foundry.coverage.store import CoverageStore
from foundry.coverage.tools import build_coverage_tools

COVERAGE_GUIDE_SYSTEM_PROMPT = f"""\
You are the Coverage-Guide role in a security-evaluation harness (spec.md \
§5.7). The checklist itself is built and checked off mechanically, not by \
you -- your job is narrower: call get_coverage_report, then produce a \
short estimate of remaining work with a one-line basis for the operator's \
planning (spec.md FR-073, a SHOULD, not a MUST -- the coverage-complete \
decision itself is made by code, not by you). Ground the estimate in the \
actual open/closed counts and item list the tool returns; don't guess at \
progress you haven't seen.

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""


def build_coverage_guide_subagent(store: CoverageStore) -> dict:
    return {
        "name": "coverage-guide",
        "description": (
            "Reports current coverage-checklist status and estimates "
            "remaining work for the operator (FR-073)."
        ),
        "system_prompt": COVERAGE_GUIDE_SYSTEM_PROMPT,
        "tools": build_coverage_tools(store),
        "middleware": [minimal_filesystem_middleware()],
    }
