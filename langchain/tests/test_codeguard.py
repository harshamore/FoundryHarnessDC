"""CodeGuard rule-loader proofs: FR-041 (versioned corpus, queryable
independently of agent code). No LLM involved -- the tool wrapping is
checked structurally, not by invoking a model. Requires
`scripts/fetch_codeguard_rules.py` to have already vendored the corpus
(same precondition the README's quickstart already documents).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.codeguard.loader import Rule, load_rules
from foundry.codeguard.tools import build_codeguard_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "data" / "codeguard" / "rules"

pytestmark = pytest.mark.skipif(
    not RULES_DIR.exists(),
    reason="data/codeguard/rules/ not vendored -- run scripts/fetch_codeguard_rules.py first",
)


def test_loads_all_core_rules():
    rules = load_rules(RULES_DIR, categories=("core",))
    assert len(rules) == 23  # count at the pinned commit, see docs/CODEGUARD_INTEGRATION.md


def test_expected_toy_target_rules_present():
    rules = load_rules(RULES_DIR, categories=("core",))
    ids = {r.rule_id for r in rules}
    assert "codeguard-0-input-validation-injection" in ids  # SQL injection
    assert "codeguard-1-hardcoded-credentials" in ids  # hardcoded Stripe-shaped key
    assert "codeguard-0-file-handling-and-uploads" in ids  # path traversal


def test_rule_content_is_parsed_correctly():
    rules = load_rules(RULES_DIR, categories=("core",))
    rule = next(r for r in rules if r.rule_id == "codeguard-1-hardcoded-credentials")
    assert rule.description == "No Hardcoded Credentials"
    assert rule.always_apply is True
    assert "NEVER" in rule.content


def test_template_files_are_skipped():
    rules = load_rules(RULES_DIR, categories=("core",))
    assert all("template" not in r.rule_id.lower() for r in rules)


def test_owasp_category_not_loaded_by_default():
    rules = load_rules(RULES_DIR)  # default categories=("core",)
    assert all(r.category == "core" for r in rules)


def test_owasp_category_loadable_when_requested():
    rules = load_rules(RULES_DIR, categories=("core", "owasp"))
    assert any(r.category == "owasp" for r in rules)
    assert len(rules) > 23  # more than core alone


def test_missing_category_directory_returns_empty_not_error(tmp_path):
    rules = load_rules(tmp_path, categories=("nonexistent",))
    assert rules == []


# ---------------------------------------------------------------------------
# Phase 1: language-filtered rule-sweep
# ---------------------------------------------------------------------------


def test_languages_none_means_no_filtering_same_as_before():
    unfiltered = load_rules(RULES_DIR, categories=("core",))
    explicit_none = load_rules(RULES_DIR, categories=("core",), languages=None)
    assert unfiltered == explicit_none


def test_language_agnostic_rules_always_included():
    """A rule with an empty `languages` field (e.g. hardcoded-credentials --
    not a language-specific concept) applies no matter which language is
    asked for."""
    rules = load_rules(RULES_DIR, categories=("core",), languages=("go",))
    ids = {r.rule_id for r in rules}
    assert "codeguard-1-hardcoded-credentials" in ids  # empty languages field


def test_language_filter_excludes_rules_not_tagged_for_that_language():
    all_rules = load_rules(RULES_DIR, categories=("core",))
    go_rules = load_rules(RULES_DIR, categories=("core",), languages=("go",))
    assert len(go_rules) < len(all_rules)  # a real subset, not a no-op
    for rule in go_rules:
        assert not rule.languages or "go" in rule.languages


def test_language_filter_is_case_insensitive():
    upper = load_rules(RULES_DIR, categories=("core",), languages=("Go",))
    lower = load_rules(RULES_DIR, categories=("core",), languages=("go",))
    assert {r.rule_id for r in upper} == {r.rule_id for r in lower}


def test_tsx_is_matched_against_typescript_tagged_rules():
    """CodeGuard's own `languages` vocabulary doesn't have a separate "tsx"
    tag (only "typescript") -- the loader must reconcile this, not require
    every caller to know about the mismatch."""
    typescript_rules = load_rules(RULES_DIR, categories=("core",), languages=("typescript",))
    tsx_rules = load_rules(RULES_DIR, categories=("core",), languages=("tsx",))
    assert {r.rule_id for r in typescript_rules} == {r.rule_id for r in tsx_rules}
    assert len(tsx_rules) > 0


def test_multiple_languages_are_unioned():
    go_only = load_rules(RULES_DIR, categories=("core",), languages=("go",))
    python_only = load_rules(RULES_DIR, categories=("core",), languages=("python",))
    combined = load_rules(RULES_DIR, categories=("core",), languages=("go", "python"))
    assert {r.rule_id for r in combined} == {r.rule_id for r in go_only} | {r.rule_id for r in python_only}


# ---------------------------------------------------------------------------
# Tool wrapping (structural check, no LLM invoked)
# ---------------------------------------------------------------------------


def test_codeguard_tools_wrap_rules_correctly():
    rules = load_rules(RULES_DIR, categories=("core",))
    tools = build_codeguard_tools(rules)
    names = {t.name for t in tools}
    assert names == {"list_rules", "get_rule"}

    list_tool = next(t for t in tools if t.name == "list_rules")
    listing = list_tool.invoke({})
    assert "codeguard-1-hardcoded-credentials" in listing

    get_tool = next(t for t in tools if t.name == "get_rule")
    result = get_tool.invoke({"rule_id": "codeguard-1-hardcoded-credentials"})
    assert "NEVER" in result


def test_get_rule_tool_reports_unknown_id_cleanly():
    tools = build_codeguard_tools([Rule("known-id", "core", "desc", True, (), "content")])
    get_tool = next(t for t in tools if t.name == "get_rule")
    result = get_tool.invoke({"rule_id": "made-up-id"})
    assert "No rule named" in result
