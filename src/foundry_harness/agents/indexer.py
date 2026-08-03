"""Indexer (spec.md §5.2).

Purpose: build and maintain the code index -- the structural knowledge of
the target every other role queries. Symbols, call graph, file inventory,
embeddings.

Gates the rest of the fleet: the Orchestrator MUST NOT spawn any
non-Indexer role until this reports queryable (FR-003, FR-024). FR-020
requires the function inventory come from a deterministic parser
(tree-sitter, ctags, a language server, or equivalent) -- LLM extraction
may augment it but MUST NOT be the sole source, because an LLM-only
indexer can return an empty table while still satisfying the query
interface, releasing the gate on nothing.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class Indexer(AgentRole):
    role_name: ClassVar[str] = "indexer"
    purpose: ClassVar[str] = (
        "Build and maintain the code index: symbols, call graph, "
        "cross-references, embeddings. The structural knowledge every "
        "other role queries."
    )
    spec_section: ClassVar[str] = "§5.2"

    async def run(self) -> None:
        raise NotImplementedError

    async def build_function_inventory(self) -> None:
        """FR-020: deterministic parser required; LLM extraction may only
        augment, never be the sole source."""
        raise NotImplementedError

    async def build_call_graph(self) -> None:
        """FR-021: direct static calls at minimum. FR-021a: SHOULD
        resolve indirect/dynamic dispatch where the language permits."""
        raise NotImplementedError

    async def is_queryable(self) -> bool:
        """FR-024: True only once FR-020, FR-021, and the query interface
        (FR-022) are satisfied. Embeddings (FR-023) MAY complete after
        this gate releases."""
        raise NotImplementedError

    # Query interface (FR-022), consumed by every other role.
    async def get_function_body(self, symbol: str) -> str:
        raise NotImplementedError

    async def get_callers(self, symbol: str) -> list[str]:
        raise NotImplementedError

    async def get_callees(self, symbol: str) -> list[str]:
        raise NotImplementedError

    async def find_symbol(self, name: str) -> list[str]:
        raise NotImplementedError

    async def full_text_search(self, query: str) -> list[str]:
        raise NotImplementedError
