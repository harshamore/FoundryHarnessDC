"""Variant-Hunter (spec.md §6.2).

Given one confirmed true-positive, searches the rest of the target for
the same pattern: same vulnerable idiom, same misused API, same missing
check. Uses the index's similarity search (FR-023) and structural pattern
matching. Produces candidates tagged as variants of the seed finding.
Plugs in downstream of Triager; its candidates re-enter Triager.

[NEEDS CLARIFICATION §6.2]: high-leverage when one true-positive implies
a systemic pattern, near-zero-value when findings are one-offs. Depends
on FR-023 (semantic embeddings), itself a SHOULD, not a MUST, on the
Indexer.
"""

from __future__ import annotations

from typing import ClassVar

from foundry_harness.agents.base import AgentRole


class VariantHunter(AgentRole):
    role_name: ClassVar[str] = "variant-hunter"
    purpose: ClassVar[str] = (
        "Given one confirmed finding, search the rest of the target for "
        "the same pattern."
    )
    spec_section: ClassVar[str] = "§6.2"

    async def run(self) -> None:
        raise NotImplementedError
