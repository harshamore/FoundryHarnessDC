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
