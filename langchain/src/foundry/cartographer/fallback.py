"""Deterministic fallback for the security map (spec.md FR-036a).

"If any of FR-030-FR-034 fails to produce non-empty output, the
Cartographer MUST write a minimal fallback for that section consisting of
mechanically-derivable facts (file tree, function index from FR-022,
configured testbed endpoints) so that downstream roles have something to
cite. An empty security map is a Cartographer failure, not graceful
degradation."

No model dependency anywhere in this file -- it runs entirely off the
Indexer's already-persisted index, so a security map with *something* in
every section exists before any LLM call is made, and stays there if an
LLM-authored section ever comes back empty.
"""
from __future__ import annotations

from foundry.indexer.store import IndexStore


def fallback_architecture_overview(target_path: str, index: IndexStore) -> str:
    functions = index.list_functions(file=target_path)
    return (
        f"[fallback] Single-file target: {target_path}. "
        f"{len(functions)} top-level function(s) found by the Indexer: {', '.join(functions)}."
    )


def fallback_attack_surface(target_path: str, index: IndexStore) -> str:
    functions = index.list_functions(file=target_path)
    return (
        "[fallback] No entry-point classification performed -- that "
        "requires reasoning about what's externally reachable, which this "
        "deterministic fallback does not attempt. Full function index for "
        f"manual review: {', '.join(functions)}."
    )


def fallback_trust_boundaries() -> str:
    return (
        "[fallback] No trust-boundary analysis performed -- this requires "
        "reasoning about validation logic that the deterministic fallback "
        "cannot perform. Treat this section as absent, not as 'no "
        "boundaries exist'."
    )


def fallback_data_flows() -> str:
    return (
        "[fallback] No data-flow analysis performed -- same caveat as "
        "trust_boundaries: absent, not 'nothing sensitive flows through "
        "this target'."
    )


def fallback_threat_model() -> str:
    return (
        "[fallback] No threat model synthesized -- it depends on the "
        "sections above, which are themselves fallbacks here."
    )
