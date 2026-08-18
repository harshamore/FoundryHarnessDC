"""The Indexer role (spec.md §5.2) as a DeepAgents SubAgent.

Indexing itself is deterministic (see foundry.indexer.parser) -- FR-020
prohibits an LLM from being the sole source of the function inventory. This
subagent wraps the *query interface* (FR-022) so downstream roles -- and,
in this section's demo, a small main agent -- can answer questions about
the target grounded in that deterministic index, not model recall.
"""
from __future__ import annotations

from deepagents.middleware.subagents import SubAgent

from foundry.agents._middleware import (
    NO_FILESYSTEM_EXPLORATION_WARNING,
    minimal_filesystem_middleware,
)
from foundry.indexer.store import IndexStore
from foundry.indexer.tools import build_index_tools

INDEXER_SYSTEM_PROMPT = f"""\
You are the Indexer role in a security-evaluation harness. You have tools \
to query a pre-built code index for one target: get_function_body, \
get_callers, get_callees, find_symbol, full_text_search. You do not have \
raw file access -- answer only from what these tools return, and say so \
plainly when a tool reports nothing found rather than guessing.

If the target has more than one file, the same function name can exist in \
more than one of them -- get_function_body/find_symbol/get_callers/ \
get_callees all accept an optional file argument to disambiguate. If a \
tool reports a name is ambiguous, don't guess which file was meant -- call \
find_symbol or full_text_search first to see the candidates, then call \
again with file set.

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""


def build_indexer_subagent(store: IndexStore) -> SubAgent:
    return {
        "name": "indexer",
        "description": (
            "Answers questions about the target's code structure -- function "
            "locations, call relationships, text search -- grounded in the "
            "deterministic index, not model recall."
        ),
        "system_prompt": INDEXER_SYSTEM_PROMPT,
        "tools": build_index_tools(store),
        "middleware": [minimal_filesystem_middleware()],
    }
