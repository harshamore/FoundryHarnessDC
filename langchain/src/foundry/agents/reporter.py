"""The Reporter role (spec.md §5.8) as a DeepAgents SubAgent -- the only
role with a tool that produces human-facing output, and the last of the
eight core roles.

Constitution II ("Surface Only What Survives") reaches its endpoint here:
`publish_finding_report` refuses anything that isn't `true-positive`
(FR-079), checked against the finding store itself, not the model's
say-so. FR-083 (no model/provider/internal identifiers in a report) is
enforced the same way -- a denylist scan on the actual text, not a prompt
instruction hoping the model remembers.
"""
from __future__ import annotations

from foundry.agents._middleware import (
    NO_FILESYSTEM_EXPLORATION_WARNING,
    minimal_filesystem_middleware,
)
from foundry.indexer.store import IndexStore
from foundry.indexer.tools import build_index_tools
from foundry.reporter.store import ReporterStore
from foundry.reporter.tools import build_reporter_tools
from foundry.substrate.finding_store import FindingStore

REPORTER_SYSTEM_PROMPT = f"""\
You are the Reporter role in a security-evaluation harness (spec.md §5.8) \
-- the last stage before a human sees anything. Call list_true_positives \
to see what's eligible, then for each one: call get_finding_detail to \
read the Triager's investigation report, use get_function_body/get_callers \
/get_callees to ground reproduction steps in real code, call \
suggest_weakness_class for a CWE starting point (use your own judgment if \
it comes back "unmapped"), and assign a severity \
(critical/high/medium/low) based on impact and attacker prerequisites.

Each report_body you pass to publish_finding_report MUST cover: affected \
component and location, a description of the vulnerability, attacker \
prerequisites, an impact statement, reproduction steps, and the Triager's \
evidence. It MUST NOT name any LLM model, provider, internal agent \
identifier, or internal hostname (spec.md FR-083) -- publish_finding_report \
rejects the report automatically if it does, so write for an external \
reviewer who has no idea this system exists. Only true-positive findings \
can be published at all; the tool rejects anything else regardless of how \
you phrase the request.

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""


def build_reporter_subagent(
    finding_store: FindingStore, reporter_store: ReporterStore, index: IndexStore
) -> dict:
    return {
        "name": "reporter",
        "description": (
            "Publishes self-contained reports for true-positive findings "
            "only -- the sole role whose output is meant for a human "
            "outside the operating team."
        ),
        "system_prompt": REPORTER_SYSTEM_PROMPT,
        "tools": [*build_index_tools(index), *build_reporter_tools(finding_store, reporter_store)],
        "middleware": [minimal_filesystem_middleware()],
    }
