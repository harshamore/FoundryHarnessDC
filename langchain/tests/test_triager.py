"""Triager proofs: FR-054 (reject a verdict with no investigation report),
list_untriaged, the tool wrappers (including the live evidence-gate
demotion through the tool layer, not just FindingStore directly), and the
SubAgent shape. No LLM involved.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.agents.triager import build_triager_subagent
from foundry.indexer.parser import index_file
from foundry.indexer.store import IndexStore
from foundry.substrate.db import connect
from foundry.substrate.finding_store import Citation, FindingStore
from foundry.triager.tools import build_triager_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "data" / "toy_target" / "vulnerable_app.py"
NORMALIZED_PATH = str(TARGET.resolve().relative_to(REPO_ROOT.resolve()))


@pytest.fixture
def index(tmp_path) -> IndexStore:
    conn = connect(tmp_path / "triager_test.sqlite3")
    result = index_file(TARGET, REPO_ROOT)
    idx = IndexStore(conn)
    idx.write_index(NORMALIZED_PATH, result.functions, result.call_edges)
    return idx


@pytest.fixture
def findings(index: IndexStore) -> FindingStore:
    return FindingStore(index.conn)


# ---------------------------------------------------------------------------
# FR-054: a verdict without an investigation report is rejected
# ---------------------------------------------------------------------------


def test_assign_verdict_rejects_empty_investigation_report(findings):
    finding_id, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )
    with pytest.raises(ValueError, match="investigation_report"):
        findings.assign_verdict(
            finding_id, "true-positive", [], "", resolver=lambda c: True
        )


def test_assign_verdict_rejects_whitespace_only_investigation_report(findings):
    finding_id, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )
    with pytest.raises(ValueError, match="investigation_report"):
        findings.assign_verdict(
            finding_id, "true-positive", [], "   \n  ", resolver=lambda c: True
        )


# ---------------------------------------------------------------------------
# list_untriaged
# ---------------------------------------------------------------------------


def test_list_untriaged_returns_only_unverdicted(findings):
    id1, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate 1",
        technique="exploratory",
    )
    id2, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="read_uploaded_file",
        vulnerability_class="path-traversal",
        description="candidate 2",
        technique="exploratory",
    )
    assert {r["id"] for r in findings.list_untriaged()} == {id1, id2}

    findings.assign_verdict(id1, "false-positive", [], "not actually exploitable", resolver=lambda c: True)
    assert {r["id"] for r in findings.list_untriaged()} == {id2}


def test_list_untriaged_empty_when_nothing_queued(findings):
    assert findings.list_untriaged() == []


# ---------------------------------------------------------------------------
# Triager tools (structural, no LLM invoked) -- including the evidence gate
# exercised through the tool layer, not just FindingStore directly
# ---------------------------------------------------------------------------


def test_triager_tools_shape(findings, index):
    tools = build_triager_tools(findings, index)
    names = {t.name for t in tools}
    assert names == {"list_candidates", "get_candidate", "assign_verdict"}


def test_list_candidates_tool_reports_none_when_empty(findings, index):
    tools = build_triager_tools(findings, index)
    list_tool = next(t for t in tools if t.name == "list_candidates")
    assert "No untriaged" in list_tool.invoke({})


def test_get_candidate_tool_reports_missing_id_cleanly(findings, index):
    tools = build_triager_tools(findings, index)
    get_tool = next(t for t in tools if t.name == "get_candidate")
    result = get_tool.invoke({"finding_id": 9999})
    assert "No finding" in result


def test_assign_verdict_tool_accepts_citations_that_resolve(findings, index):
    finding_id, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="codeguard-0-input-validation-injection",
    )
    tools = build_triager_tools(findings, index)
    assign_tool = next(t for t in tools if t.name == "assign_verdict")

    result = assign_tool.invoke({
        "finding_id": finding_id,
        "verdict": "true-positive",
        "citations": [
            {"path": NORMALIZED_PATH, "symbol": "users_endpoint", "claim": "reachability"},
            {"path": NORMALIZED_PATH, "symbol": "get_user_by_name", "claim": "impact"},
        ],
        "investigation_report": "username flows unsanitized into an f-string SQL query",
    })
    assert "true-positive" in result
    assert findings.get(finding_id)["verdict"] == "true-positive"


def test_assign_verdict_tool_demotes_fabricated_citation(findings, index):
    """The live proof, through the tool an agent actually calls: a citation
    naming a symbol that was never defined anywhere gets auto-demoted,
    exactly like the Substrate/Indexer sections proved at the store level."""
    finding_id, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="read_uploaded_file",
        vulnerability_class="path-traversal",
        description="candidate",
        technique="exploratory",
    )
    tools = build_triager_tools(findings, index)
    assign_tool = next(t for t in tools if t.name == "assign_verdict")

    result = assign_tool.invoke({
        "finding_id": finding_id,
        "verdict": "true-positive",
        "citations": [
            {"path": NORMALIZED_PATH, "symbol": "sanitize_path_properly", "claim": "reachability"},
        ],
        "investigation_report": "confident but citing a function that doesn't exist",
    })
    assert "needs-review" in result
    assert "demoted" in result
    assert findings.get(finding_id)["verdict"] == "needs-review"


def test_assign_verdict_tool_reports_empty_report_cleanly_not_a_crash(findings, index):
    finding_id, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_db",
        vulnerability_class="code-quality",
        description="candidate",
        technique="exploratory",
    )
    tools = build_triager_tools(findings, index)
    assign_tool = next(t for t in tools if t.name == "assign_verdict")

    result = assign_tool.invoke({
        "finding_id": finding_id,
        "verdict": "code-quality",
        "citations": [],
        "investigation_report": "",
    })
    assert "rejected" in result
    assert findings.get(finding_id)["verdict"] is None  # unchanged, not silently accepted


# ---------------------------------------------------------------------------
# SubAgent wrapping (structural check, no LLM invoked)
# ---------------------------------------------------------------------------


def test_build_triager_subagent_shape(findings, index):
    subagent = build_triager_subagent(findings, index, security_map_digest="## Test\nsome digest")
    assert subagent["name"] == "triager"
    assert "middleware" in subagent
    # 5 index tools + 3 triager tools
    assert len(subagent["tools"]) == 8


def test_triager_subagent_front_loads_security_map_digest(findings, index):
    digest = "## Trust Boundaries\nusername -> SQL, unvalidated"
    subagent = build_triager_subagent(findings, index, security_map_digest=digest)
    assert digest in subagent["system_prompt"]
