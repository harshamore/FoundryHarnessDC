"""LangChain tool wrappers for the Cartographer's writes -- one tool per
security-map section (spec.md FR-030-034), so the model's authored content
is captured through a structured call, not parsed out of free text.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.cartographer.store import SecurityMapStore


def build_cartographer_tools(store: SecurityMapStore) -> list[BaseTool]:
    @tool
    def write_architecture_overview(content: str) -> str:
        """Record the architecture overview: major components, their responsibilities, and how they communicate (FR-030)."""
        store.write_section("architecture_overview", content, source="llm")
        return "Recorded architecture_overview."

    @tool
    def write_attack_surface(content: str) -> str:
        """Record the attack-surface enumeration: every entry point reachable by an actor outside the trust boundary, with the auth required at each (FR-031)."""
        store.write_section("attack_surface", content, source="llm")
        return "Recorded attack_surface."

    @tool
    def write_trust_boundaries(content: str) -> str:
        """Record the trust-boundary map: where untrusted input becomes trusted, and what validation (if any) guards each crossing (FR-032)."""
        store.write_section("trust_boundaries", content, source="llm")
        return "Recorded trust_boundaries."

    @tool
    def write_data_flows(content: str) -> str:
        """Record the data-flow description for sensitive data classes (credentials, secrets, user data): where each enters, passes through, is stored, and leaves (FR-033)."""
        store.write_section("data_flows", content, source="llm")
        return "Recorded data_flows."

    @tool
    def write_threat_model(content: str) -> str:
        """Record the threat model synthesizing the sections above: attacker positions, attack goals, and threat categories per entry point and trust boundary (FR-034)."""
        store.write_section("threat_model", content, source="llm")
        return "Recorded threat_model."

    return [
        write_architecture_overview,
        write_attack_surface,
        write_trust_boundaries,
        write_data_flows,
        write_threat_model,
    ]
