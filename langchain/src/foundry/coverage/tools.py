"""LangChain tool wrapper for the Coverage-Guide's one LLM-relevant piece:
FR-073's "estimate of remaining work, with a one-line basis" (SHOULD, not
MUST). Every MUST-level requirement (FR-067/069/070/071/072/074) is
mechanical and is exercised directly from `CoverageStore`, not through a
tool an agent calls.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.coverage.store import CoverageStore


def build_coverage_tools(store: CoverageStore) -> list[BaseTool]:
    @tool
    def get_coverage_report() -> str:
        """Get the current coverage checklist: what's closed, what's still open, and why."""
        open_items = store.open_items()
        closed_items = store.closed_items()
        lines = [f"{len(closed_items)} closed, {len(open_items)} still open."]
        if closed_items:
            lines.append("Closed:")
            lines.extend(f"  - {r['area']} / {r['goal']} (closed {r['closed_at']})" for r in closed_items)
        if open_items:
            lines.append("Still open:")
            lines.extend(f"  - {r['area']} / {r['goal']}: {r['bar']}" for r in open_items)
        return "\n".join(lines)

    return [get_coverage_report]
