"""LangChain tool wrappers around IndexStore -- the query interface
spec.md FR-022 requires, made callable by an LLM agent.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.indexer.store import IndexStore


def build_index_tools(store: IndexStore) -> list[BaseTool]:
    @tool
    def get_function_body(name: str, file: str | None = None) -> str:
        """Return the full source of the function with this name. If the same
        name is defined in more than one indexed file, this reports the
        conflicting files instead of guessing -- call again with `file` set
        to one of them (get find_symbol's or full_text_search's output for
        the exact path)."""
        try:
            body = store.get_function_body(name, file=file)
        except ValueError as e:
            return str(e)
        if body is not None:
            return body
        return f"No function named '{name}' in {file}." if file else f"No function named '{name}' in the index."

    @tool
    def get_callers(name: str, file: str | None = None) -> str:
        """List every function that calls the function with this name.
        Optional `file` narrows this to calls recorded while parsing that
        specific file -- useful when the same name exists in more than one
        file, though it does not resolve which file the called function is
        actually defined in (no cross-file import resolution is done)."""
        callers = store.get_callers(name, file=file)
        return ", ".join(callers) if callers else f"No known callers of '{name}'."

    @tool
    def get_callees(name: str, file: str | None = None) -> str:
        """List every function/method the function with this name calls.
        Optional `file` narrows this to calls recorded while parsing that
        specific file -- useful when the same name exists in more than one
        file."""
        callees = store.get_callees(name, file=file)
        return ", ".join(callees) if callees else f"'{name}' calls nothing tracked in the index."

    @tool
    def find_symbol(name: str, file: str | None = None) -> str:
        """Look up where a function is defined: file and line range. If the
        same name is defined in more than one indexed file, lists every
        match rather than guessing -- pass `file` to narrow it down."""
        rows = store.find_symbol(name, file=file)
        if not rows:
            return f"No symbol named '{name}' found."
        if len(rows) == 1:
            r = rows[0]
            return f"{name} is defined in {r['file']} at lines {r['lineno']}-{r['end_lineno']}."
        lines = [f"'{name}' is defined in more than one file:"]
        lines.extend(f"  {r['file']} at lines {r['lineno']}-{r['end_lineno']}" for r in rows)
        return "\n".join(lines)

    @tool
    def full_text_search(query: str) -> str:
        """Search all indexed function bodies for a substring; returns matching
        (file, function name) pairs."""
        matches = store.full_text_search(query)
        return ", ".join(f"{file}::{name}" for file, name in matches) if matches else f"No function body contains '{query}'."

    return [get_function_body, get_callers, get_callees, find_symbol, full_text_search]
