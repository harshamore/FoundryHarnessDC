"""The Cartographer role (spec.md §5.3) as a DeepAgents SubAgent.

Unlike the Indexer, the Cartographer's output IS meant to be LLM-authored --
FR-034 explicitly allows this for the threat model, and there's no
deterministic-parser requirement here the way FR-020 constrains the
Indexer. What's structural instead is FR-036a: every section already has a
fallback value from foundry.cartographer.fallback before this subagent ever
runs, so the map is never empty regardless of what the model produces.
"""
from __future__ import annotations

from foundry.agents._middleware import (
    NO_FILESYSTEM_EXPLORATION_WARNING,
    minimal_filesystem_middleware,
)
from foundry.cartographer.store import SecurityMapStore
from foundry.cartographer.tools import build_cartographer_tools
from foundry.indexer.store import IndexStore
from foundry.indexer.tools import build_index_tools

CARTOGRAPHER_SYSTEM_PROMPT = f"""\
You are the Cartographer role in a security-evaluation harness. Your job \
is to produce the security map for the target: architecture overview, \
attack-surface enumeration, trust-boundary map, data-flow description, and \
a threat model synthesizing the rest.

You have read-only tools to query the target's code (get_function_body, \
get_callers, get_callees, find_symbol, full_text_search) and write tools, \
one per section (write_architecture_overview, write_attack_surface, \
write_trust_boundaries, write_data_flows, write_threat_model). Read the \
code before writing each section -- ground every claim in what the tools \
actually return, not assumption. Call every write tool at least once, even \
if a section is brief for a small target.

{NO_FILESYSTEM_EXPLORATION_WARNING}\
"""


def build_cartographer_subagent(security_map: SecurityMapStore, index: IndexStore) -> dict:
    return {
        "name": "cartographer",
        "description": (
            "Produces and maintains the security map -- architecture, "
            "attack surface, trust boundaries, data flows, threat model -- "
            "that every other role reasons against."
        ),
        "system_prompt": CARTOGRAPHER_SYSTEM_PROMPT,
        "tools": [*build_index_tools(index), *build_cartographer_tools(security_map)],
        "middleware": [minimal_filesystem_middleware()],
    }
