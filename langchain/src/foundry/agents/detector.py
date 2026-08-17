"""The Detector role (spec.md §5.4) as two DeepAgents SubAgents: rule-sweep
(FR-037, systematic) and exploratory hunting (FR-040, free-form) -- "the
two halves of a flywheel" per the spec, sharing the same finding-store
tools (spec.md §5.4: "the two modes are not alternatives; they are the two
halves of a flywheel that, once turning, improves both detection and
prevention indefinitely").

Both write only through `queue_candidate` (Constitution II: "Surface Only
What Survives" -- detection is high-volume, low-precision by design, and
none of it reaches a human until the Triager, not built yet, promotes it).
"""
from __future__ import annotations

from foundry.agents._middleware import (
    NO_FILESYSTEM_EXPLORATION_WARNING,
    minimal_filesystem_middleware,
)
from foundry.codeguard.loader import Rule
from foundry.codeguard.tools import build_codeguard_tools
from foundry.detector.tools import build_detector_tools
from foundry.indexer.store import IndexStore
from foundry.indexer.tools import build_index_tools
from foundry.substrate.finding_store import FindingStore

RULE_SWEEP_SYSTEM_PROMPT = f"""\
You are the Detector role's rule-sweep half in a security-evaluation \
harness (spec.md FR-037). Your job is systematic, not creative: for every \
function in the index, check whether it plausibly violates any CodeGuard \
rule. Use list_rules to see what's available, get_rule for the full text \
of a specific rule, and get_function_body/get_callers/get_callees to read \
the code a rule would apply to.

When a function looks like it violates a rule, call queue_candidate with \
the rule id as `technique` (e.g. "codeguard-1-hardcoded-credentials"), not \
"exploratory". Queuing is not a verdict -- a low bar for candidates is \
correct here; a later Triager role filters signal from noise. Do not skip \
a function because a rule "obviously" doesn't apply without actually \
checking its body -- a missed candidate here is permanent, a wrong one \
just costs a later triage step.

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""


def build_detector_rule_sweep_subagent(
    finding_store: FindingStore, index: IndexStore, rules: list[Rule]
) -> dict:
    return {
        "name": "detector-rule-sweep",
        "description": (
            "Systematically checks every function against the CodeGuard "
            "rule corpus and queues a candidate finding for anything that "
            "plausibly violates a rule."
        ),
        "system_prompt": RULE_SWEEP_SYSTEM_PROMPT,
        "tools": [
            *build_index_tools(index),
            *build_codeguard_tools(rules),
            *build_detector_tools(finding_store),
        ],
        "middleware": [minimal_filesystem_middleware()],
    }


def build_detector_exploratory_subagent(
    finding_store: FindingStore, index: IndexStore, security_map_digest: str
) -> dict:
    system_prompt = f"""\
You are the Detector role's exploratory half in a security-evaluation \
harness (spec.md FR-040). Unlike the rule-sweep half, you are not bound to \
a checklist: reason freely about this specific target's design to find \
what a generic rule would miss. Ground every candidate in code you \
actually read via get_function_body/get_callers/get_callees/find_symbol/ \
full_text_search -- never guess. Use queue_candidate with technique= \
"exploratory" for anything you find.

If you are confident a finding is real and can explain why no generic \
rule would have caught it, also call record_rule_gap (spec.md FR-042) -- \
this is how the rule corpus grows. Don't call it reflexively; only when \
you can name the specific pattern a rule is missing.

Security map (spec.md FR-035 digest, already produced by the Cartographer \
-- front-loaded here rather than fetched via a tool, since it's small \
enough to fit directly and every claim in it should already be grounded):
{security_map_digest}

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""
    return {
        "name": "detector-exploratory",
        "description": (
            "Freely explores the target for vulnerabilities a generic rule "
            "wouldn't catch, grounded in the actual code, not assumption."
        ),
        "system_prompt": system_prompt,
        "tools": [*build_index_tools(index), *build_detector_tools(finding_store)],
        "middleware": [minimal_filesystem_middleware()],
    }
