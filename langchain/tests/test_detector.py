"""Detector proofs: the queue_candidate/record_rule_gap tool wrappers and
both SubAgent shapes. No LLM involved -- rule-sweep vs exploratory
*reasoning* can only be exercised live, but everything mechanical around
it (tool wiring, dedup, rule-gap persistence, filesystem-tool restriction,
front-loaded security-map digest) is checked here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.agents.detector import (
    build_detector_exploratory_subagent,
    build_detector_rule_sweep_subagent,
)
from foundry.codeguard.loader import load_rules
from foundry.detector.tools import build_detector_tools
from foundry.indexer.parser import index_file
from foundry.indexer.store import IndexStore
from foundry.substrate.db import connect
from foundry.substrate.finding_store import FindingStore

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "data" / "toy_target" / "vulnerable_app.py"
NORMALIZED_PATH = str(TARGET.resolve().relative_to(REPO_ROOT.resolve()))
RULES_DIR = REPO_ROOT / "data" / "codeguard" / "rules"


@pytest.fixture
def index(tmp_path) -> IndexStore:
    conn = connect(tmp_path / "detector_test.sqlite3")
    result = index_file(TARGET, REPO_ROOT)
    idx = IndexStore(conn)
    idx.write_index(NORMALIZED_PATH, result.functions, result.call_edges)
    return idx


@pytest.fixture
def findings(index: IndexStore) -> FindingStore:
    return FindingStore(index.conn)


# ---------------------------------------------------------------------------
# FR-042: rule-gap recording (the rule_gaps table has existed since the
# Substrate section; nothing used it until now)
# ---------------------------------------------------------------------------


def test_record_and_list_rule_gaps(findings):
    findings.record_rule_gap("abc123", "race-condition", "unsynchronized shared mutable state")
    gaps = findings.list_rule_gaps()
    assert len(gaps) == 1
    assert gaps[0]["finding_fingerprint"] == "abc123"
    assert gaps[0]["vulnerability_class"] == "race-condition"


def test_list_rule_gaps_empty_when_none_recorded(findings):
    assert findings.list_rule_gaps() == []


# ---------------------------------------------------------------------------
# Detector tools (structural, no LLM invoked)
# ---------------------------------------------------------------------------


def test_detector_tools_shape(findings):
    tools = build_detector_tools(findings)
    names = {t.name for t in tools}
    assert names == {"queue_candidate", "record_rule_gap"}


def test_queue_candidate_tool_dedups_like_the_underlying_store(findings):
    tools = build_detector_tools(findings)
    queue_tool = next(t for t in tools if t.name == "queue_candidate")

    first = queue_tool.invoke(
        {
            "normalized_path": NORMALIZED_PATH,
            "symbol": "get_user_by_name",
            "vulnerability_class": "sql-injection",
            "description": "candidate",
            "technique": "codeguard-0-input-validation-injection",
        }
    )
    assert "new candidate" in first

    second = queue_tool.invoke(
        {
            "normalized_path": NORMALIZED_PATH,
            "symbol": "get_user_by_name",
            "vulnerability_class": "sql-injection",
            "description": "same candidate, re-detected",
            "technique": "codeguard-0-input-validation-injection",
        }
    )
    assert "deduplicated" in second


def test_record_rule_gap_tool(findings):
    tools = build_detector_tools(findings)
    gap_tool = next(t for t in tools if t.name == "record_rule_gap")
    result = gap_tool.invoke(
        {
            "finding_fingerprint": "abc123",
            "vulnerability_class": "logic-flaw",
            "pattern": "off-by-one in access-window check",
        }
    )
    assert "recorded" in result.lower()
    assert len(findings.list_rule_gaps()) == 1


# ---------------------------------------------------------------------------
# SubAgent wrapping (structural checks, no LLM invoked)
# ---------------------------------------------------------------------------


def test_build_detector_rule_sweep_subagent_shape(findings, index):
    rules = load_rules(RULES_DIR, categories=("core",))
    subagent = build_detector_rule_sweep_subagent(findings, index, rules)
    assert subagent["name"] == "detector-rule-sweep"
    assert "middleware" in subagent
    # 5 index tools + 2 codeguard tools + 2 detector tools
    assert len(subagent["tools"]) == 9


def test_build_detector_exploratory_subagent_shape(findings, index):
    subagent = build_detector_exploratory_subagent(findings, index, security_map_digest="## Test\nsome digest")
    assert subagent["name"] == "detector-exploratory"
    assert "middleware" in subagent
    # 5 index tools + 2 detector tools (no codeguard tools -- free-form, not rule-bound)
    assert len(subagent["tools"]) == 7


def test_exploratory_subagent_front_loads_security_map_digest(findings, index):
    """FR-035: the digest is meant to be front-loaded directly into the
    prompt, not fetched via a tool -- confirm it actually lands in the
    system prompt text."""
    digest = "## Attack Surface\nunauthenticated GET /users"
    subagent = build_detector_exploratory_subagent(findings, index, security_map_digest=digest)
    assert digest in subagent["system_prompt"]
