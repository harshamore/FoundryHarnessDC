"""LangChain tool wrappers around IndexStore -- the query interface
spec.md FR-022 requires, made callable by an LLM agent.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.indexer.store import IndexStore


def build_index_tools(store: IndexStore) -> list[BaseTool]:
    @tool
    def get_function_body(name: str) -> str:
        """Return the full source of the function with this name."""
        body = store.get_function_body(name)
        return body if body is not None else f"No function named '{name}' in the index."

    @tool
    def get_callers(name: str) -> str:
        """List every function that calls the function with this name."""
        callers = store.get_callers(name)
        return ", ".join(callers) if callers else f"No known callers of '{name}'."

    @tool
    def get_callees(name: str) -> str:
        """List every function/method the function with this name calls."""
        callees = store.get_callees(name)
        return ", ".join(callees) if callees else f"'{name}' calls nothing tracked in the index."

    @tool
    def find_symbol(name: str) -> str:
        """Look up where a function is defined: file and line range."""
        row = store.find_symbol(name)
        if row is None:
            return f"No symbol named '{name}' found."
        return f"{name} is defined in {row['file']} at lines {row['lineno']}-{row['end_lineno']}."

    @tool
    def full_text_search(query: str) -> str:
        """Search all indexed function bodies for a substring; returns matching function names."""
        matches = store.full_text_search(query)
        return ", ".join(matches) if matches else f"No function body contains '{query}'."

    return [get_function_body, get_callers, get_callees, find_symbol, full_text_search]
