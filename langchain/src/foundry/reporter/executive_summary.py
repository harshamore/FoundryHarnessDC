"""CISO-ready executive summary for the evaluation rollup (Phase 5).

The deterministic aggregation in `ReporterStore` already produces a
complete, correct report -- this adds one LLM-authored paragraph on top,
framed for a CISO audience (business risk, not implementation detail).
Same "real call, deterministic fallback underneath" shape already
established by the Cartographer's FR-036a security-map fallback and
Coverage-Guide's FR-073 checklist: an executive summary that's merely
absent is a Reporter degradation, not a broken report, so nothing here
ever lets an LLM failure (bad key, network, empty response) block the
report from existing -- it falls back to a deterministic paragraph
instead, the same way Galileo tracing fails soft rather than failing the
run.

FR-083 (no model/provider/internal identifiers in a report) applies to
this generated text exactly as it does to a published finding report --
scanned before it's ever written to disk, discarded (not sanitized) if
it fails, since the goal is a report a CISO can trust top to bottom, not
one with a redacted sentence in it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from foundry.reporter.classification import find_forbidden_mentions

SEVERITIES = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class RollupFacts:
    total_findings: int
    by_severity: dict[str, int]
    exploited_count: int
    not_exploited_count: int
    component_count: int
    closed_goal_count: int
    open_goal_count: int
    stop_reason: str


def deterministic_executive_summary(facts: RollupFacts) -> str:
    """No LLM -- mechanically derivable from the same facts the rest of
    the rollup already aggregates. Always produces a complete paragraph,
    never an empty string, so it's a safe fallback in every case."""
    if facts.total_findings == 0:
        headline = "This assessment published no confirmed findings."
    else:
        worst = next((sev for sev in SEVERITIES if facts.by_severity.get(sev, 0)), "low")
        headline = (
            f"This assessment published {facts.total_findings} confirmed finding(s) "
            f"across {facts.component_count} component(s); the most severe is rated {worst}."
        )

    total_goals = facts.closed_goal_count + facts.open_goal_count
    coverage = (
        f"{facts.closed_goal_count} of {total_goals} stated goal(s) were credibly "
        "attempted and closed" + (f", {facts.open_goal_count} remain open." if facts.open_goal_count else ".")
        if total_goals
        else "No coverage goals were configured for this run."
    )

    exploited = (
        f"{facts.exploited_count} finding(s) were demonstrated exploitable during "
        f"testing, {facts.not_exploited_count} were not."
        if facts.total_findings
        else ""
    )

    parts = [f"[fallback] {headline}", coverage]
    if exploited:
        parts.append(exploited)
    parts.append(f"Assessment stop reason: {facts.stop_reason}.")
    return " ".join(parts)


def _resolve_model(model: str | Any) -> Any:
    if isinstance(model, str):
        from langchain.chat_models import init_chat_model

        return init_chat_model(model)
    return model


async def build_executive_summary(facts: RollupFacts, model: str | Any | None) -> str:
    """`model` is typed `str | Any | None` (not `str | BaseChatModel |
    None`) for the same reason `agent_runner.run_single_subagent` types
    its own `model` param loosely -- tests pass a scripted fake chat
    model instance without importing langchain_core here just for a type
    hint. `None` skips the LLM call entirely (e.g. `ReporterStore.
    build_rollup`'s own many existing callers that never touch this
    path)."""
    if model is None:
        return deterministic_executive_summary(facts)

    try:
        resolved = _resolve_model(model)
        prompt = (
            "Write a single short paragraph (3-5 sentences) summarizing this security "
            "assessment for a CISO audience: business risk and priority, not "
            "implementation detail. No preamble, no headers, no bullet points -- "
            "just the paragraph.\n\n"
            f"Confirmed findings: {facts.total_findings}\n"
            f"By severity: {dict(facts.by_severity)}\n"
            f"Exploited: {facts.exploited_count}, not exploited: {facts.not_exploited_count}\n"
            f"Affected components: {facts.component_count}\n"
            f"Coverage goals closed: {facts.closed_goal_count}, open: {facts.open_goal_count}\n"
            f"Assessment stop reason: {facts.stop_reason}"
        )
        response = await resolved.ainvoke(
            [
                {"role": "system", "content": "You write concise, factual executive summaries for security assessment reports."},
                {"role": "user", "content": prompt},
            ]
        )
        text = str(response.content or "").strip()
    except Exception:
        return deterministic_executive_summary(facts)

    if not text or find_forbidden_mentions(text):
        return deterministic_executive_summary(facts)
    return text
