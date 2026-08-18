"""Deterministic weakness-classification lookup (spec.md FR-076) and the
FR-083 redaction check -- no LLM dependency in either.

FR-076 leaves the taxonomy choice open in the spec itself
([NEEDS CLARIFICATION: CWE, an organization-internal taxonomy, or none?]).
This build uses CWE: it's the taxonomy a security reviewer receiving these
reports is most likely to already recognize, and this toy target's known
vulnerability classes map cleanly onto well-known CWE IDs.
"""
from __future__ import annotations

# Deterministic floor, not a ceiling: covers the vulnerability classes this
# harness's own Detector/Triager sections actually produce for the toy
# target. Anything not in here is left for the Reporter subagent to
# classify itself using its own judgment.
KNOWN_CWE_MAPPING: dict[str, str] = {
    "sql-injection": "CWE-89",
    "path-traversal": "CWE-22",
    "hardcoded-credentials": "CWE-798",
}


def lookup_cwe(vulnerability_class: str) -> str | None:
    return KNOWN_CWE_MAPPING.get(vulnerability_class)


# FR-083: "Finding reports MUST NOT name the LLM model or provider, the
# system's internal agent identifiers, or internal hostnames." Rationale in
# the spec: "reports are forwarded outside the operating team. Internal
# implementation details leak operational information and date the report."
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "gpt-5.6",
    "gpt-5",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "deepagents",
    "langchain",
    "langgraph",
    "subagent",
    "localhost",
    "127.0.0.1",
    ".internal",
)


def find_forbidden_mentions(text: str) -> list[str]:
    """Which forbidden substrings (if any) appear in `text`, case-insensitive.
    An empty list means the text passes FR-083."""
    lowered = text.lower()
    return [s for s in _FORBIDDEN_SUBSTRINGS if s in lowered]
