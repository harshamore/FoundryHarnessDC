"""LangChain tool wrappers for the Triager role (spec.md §5.5).

`assign_verdict` is the one that matters structurally: it binds the real
Indexer-backed resolver (`IndexStore.symbol_exists`) as a closure the model
never sees or controls -- the agent supplies citations, the tool decides
whether they resolve. This is the same `FindingStore.assign_verdict()`
evidence gate the Substrate section tested with a fake resolver and the
Indexer section rewired to the real one; nothing about the gate itself
changes here, only that a live agent is now the caller instead of a
notebook cell.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.indexer.store import IndexStore
from foundry.substrate.finding_store import Citation, FindingStore


def build_triager_tools(finding_store: FindingStore, index: IndexStore) -> list[BaseTool]:
    def real_resolver(c: Citation) -> bool:
        return index.symbol_exists(c.path, c.symbol)

    @tool
    def list_candidates() -> str:
        """List every finding that hasn't been assigned a verdict yet -- what needs triaging."""
        rows = finding_store.list_untriaged()
        if not rows:
            return "No untriaged candidates."
        lines = [
            f"#{r['id']} {r['symbol']} [{r['vulnerability_class']}] via {r['technique']}: {r['description']}"
            for r in rows
        ]
        return "\n".join(lines)

    @tool
    def get_candidate(finding_id: int) -> str:
        """Get full details for one candidate finding by id."""
        row = finding_store.get(finding_id)
        if row is None:
            return f"No finding with id {finding_id}."
        return (
            f"id={row['id']} path={row['normalized_path']} symbol={row['symbol']} "
            f"class={row['vulnerability_class']} technique={row['technique']}\n"
            f"description: {row['description']}\n"
            f"current verdict: {row['verdict'] or '(untriaged)'}"
        )

    @tool
    def assign_verdict(
        finding_id: int,
        verdict: str,
        citations: list[dict[str, str]],
        investigation_report: str,
    ) -> str:
        """Assign a verdict to a candidate: true-positive, false-positive, needs-review,
        not-applicable, or code-quality. `citations` must be a list of objects with
        path, symbol, and claim (what the citation establishes, e.g. "reachability",
        "trust-boundary crossing", or "impact") -- each is checked against the real
        index; true-positive requires every citation to resolve to real code, or the
        verdict is automatically demoted to needs-review. investigation_report must be
        non-empty and explain your reasoning; a bare label is rejected."""
        try:
            citation_objs = [Citation(c["path"], c["symbol"], c["claim"]) for c in citations]
            final = finding_store.assign_verdict(
                finding_id, verdict, citation_objs, investigation_report, real_resolver
            )
        except (ValueError, KeyError) as e:
            return f"assign_verdict rejected: {e}"
        note = " (demoted by the evidence gate)" if final != verdict else ""
        return f"Finding {finding_id} verdict recorded as {final}{note}."

    return [list_candidates, get_candidate, assign_verdict]
