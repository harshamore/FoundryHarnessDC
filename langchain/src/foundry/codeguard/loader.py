"""Deterministic loader for the vendored CodeGuard rule corpus.

Mirrors the parsing logic of the upstream `codeguard-mcp` server's
`RuleProcessor` (see docs/CODEGUARD_INTEGRATION.md), reading directly from
the vendored markdown files in `data/codeguard/rules/` -- no MCP server, no
model call anywhere in this file. spec.md FR-041: the rule corpus is a
versioned artifact maintained independently of agent code; this only makes
it queryable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str  # "core" or "owasp" -- the vendored subdirectory name
    description: str
    always_apply: bool
    languages: tuple[str, ...]
    content: str


# CodeGuard's own `languages` frontmatter vocabulary doesn't distinguish
# TSX from TypeScript (no rule tags "tsx"), but
# `foundry.indexer.parser.detect_language` does, since TSX needs its own
# tree-sitter grammar -- this reconciles the two vocabularies at the one
# point they meet, rather than making every caller of `load_rules` know
# about the mismatch.
_LANGUAGE_ALIASES_FOR_RULE_MATCHING: dict[str, str] = {"tsx": "typescript"}


def _split_frontmatter(text: str) -> tuple[dict | None, str]:
    if not text.startswith("---\n"):
        return None, text
    lines = text.split("\n")
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            fm_text = "\n".join(lines[1:idx])
            body = "\n".join(lines[idx + 1 :]).strip()
            return yaml.safe_load(fm_text) or {}, body
    return None, text


def _parse_rule_file(path: Path, category: str) -> Rule | None:
    fm, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    if not fm:
        return None
    description = (fm.get("description") or "").strip()
    if not description:
        return None
    return Rule(
        rule_id=path.stem,
        category=category,
        description=description,
        always_apply=bool(fm.get("alwaysApply", False)),
        languages=tuple(fm.get("languages") or ()),
        content=body,
    )


def load_rules(
    rules_dir: Path,
    categories: tuple[str, ...] = ("core",),
    languages: tuple[str, ...] | None = None,
) -> list[Rule]:
    """Load every rule from the given category subdirectories of `rules_dir`.

    Defaults to `core` only (23 rules at the pinned commit) -- matches the
    upstream `codeguard-mcp` server's own default; `owasp` (the larger
    ~85-rule superset) is available to opt into once the pipeline is
    proven, per docs/CODEGUARD_INTEGRATION.md.

    `languages`, if given, filters to rules relevant to the target's
    detected language(s) (Phase 1 -- multi-language support):
    a rule with an empty `languages` frontmatter field applies regardless
    (e.g. `codeguard-1-hardcoded-credentials` -- a concept that isn't
    language-specific), everything else keeps only rules whose own
    `languages` list intersects the ones given. `languages=None` (the
    default) means no filtering at all, same as before this parameter
    existed -- every existing caller is unaffected.
    """
    rules: list[Rule] = []
    for category in categories:
        category_dir = rules_dir / category
        if not category_dir.exists():
            continue
        for md_path in sorted(category_dir.glob("*.md")):
            if "template" in md_path.name.lower():
                continue
            rule = _parse_rule_file(md_path, category)
            if rule:
                rules.append(rule)
    if languages is not None:
        wanted = {_LANGUAGE_ALIASES_FOR_RULE_MATCHING.get(lang.lower(), lang.lower()) for lang in languages}
        rules = [r for r in rules if not r.languages or wanted & {lang.lower() for lang in r.languages}]
    return rules
