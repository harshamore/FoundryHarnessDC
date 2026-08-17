"""LangChain tool wrappers around the loaded CodeGuard rule corpus --
the query interface the Detector's rule-sweep half (spec.md FR-037) uses
to see what checks are available, instead of hand-writing detection rules.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.codeguard.loader import Rule


def build_codeguard_tools(rules: list[Rule]) -> list[BaseTool]:
    by_id = {r.rule_id: r for r in rules}

    @tool
    def list_rules() -> str:
        """List every available CodeGuard rule id with its one-line description."""
        return "\n".join(f"{r.rule_id}: {r.description}" for r in rules)

    @tool
    def get_rule(rule_id: str) -> str:
        """Return the full guidance text for one CodeGuard rule id (call list_rules first to see ids)."""
        rule = by_id.get(rule_id)
        if rule is None:
            return f"No rule named '{rule_id}'. Call list_rules to see available ids."
        return f"{rule.rule_id}: {rule.description}\n---\n{rule.content}"

    return [list_rules, get_rule]
