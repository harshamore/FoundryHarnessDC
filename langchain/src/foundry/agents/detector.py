"""The Detector role (spec.md §5.4) as three DeepAgents SubAgents: rule-sweep
(FR-037, systematic), exploratory hunting (FR-040, free-form) -- "the two
halves of a flywheel" per the spec (spec.md §5.4: "the two modes are not
alternatives; they are the two halves of a flywheel that, once turning,
improves both detection and prevention indefinitely") -- and directed
detection (FR-070), which closes Coverage-Guide's directed-task loop by
consuming the gaps the other two halves left uncovered.

All three write only through `queue_candidate` (Constitution II: "Surface
Only What Survives" -- detection is high-volume, low-precision by design,
and none of it reaches a human until the Triager promotes it).
"""
from __future__ import annotations

from foundry.agents._middleware import (
    NO_FILESYSTEM_EXPLORATION_WARNING,
    minimal_filesystem_middleware,
)
from foundry.codeguard.loader import Rule
from foundry.codeguard.tools import build_codeguard_tools
from foundry.coverage.store import CoverageStore
from foundry.detector.tools import build_detector_tools, build_directed_task_tools
from foundry.indexer.store import IndexStore
from foundry.indexer.tools import build_index_tools
from foundry.substrate.finding_store import FindingStore
from foundry.substrate.work_queue import WorkQueue

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


DIRECTED_SYSTEM_PROMPT = f"""\
You are the Detector role's directed half in a security-evaluation harness \
(spec.md FR-070). Unlike the rule-sweep and exploratory halves, you don't \
choose what to look at -- Coverage-Guide has already identified specific \
(area, goal) gaps in what's been checked so far and queued a task for each \
one. Your job is to close them.

Call claim_directed_task to get one task -- it tells you the area, goal, \
and a specific instruction. Investigate using get_function_body/ \
get_callers/get_callees/find_symbol/full_text_search, exactly like the \
other Detector halves, grounding everything in code you actually read. If \
you find something, call queue_candidate for it (technique="directed:" \
followed by the goal, e.g. "directed:sql-injection"). Whether or not you \
found anything, call complete_directed_task with the task's id and a short \
note on what you actually checked when you're done investigating it -- \
this is the permanent record that the gap was actually checked, separate \
from whether anything was found there, and it's what closes the coverage \
checklist item, not queue_candidate.

Then call claim_directed_task again for the next one. Keep going until it \
tells you no directed tasks are available -- that's how you know to stop.

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""


def build_detector_directed_subagent(
    finding_store: FindingStore, index: IndexStore, work_queue: WorkQueue, coverage_store: CoverageStore
) -> dict:
    return {
        "name": "detector-directed",
        "description": (
            "Consumes Coverage-Guide's directed-detection tasks one at a "
            "time -- investigating each named (area, goal) gap, queuing a "
            "candidate finding for anything found, and recording a "
            "coverage sweep either way -- until none remain."
        ),
        "system_prompt": DIRECTED_SYSTEM_PROMPT,
        "tools": [
            *build_index_tools(index),
            *build_detector_tools(finding_store),
            *build_directed_task_tools(work_queue, coverage_store),
        ],
        "middleware": [minimal_filesystem_middleware()],
    }
