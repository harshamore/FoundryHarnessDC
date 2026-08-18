"""Reporter proofs: FR-079 (never publish anything but true-positive),
FR-083 (never leak model/provider/internal identifiers), FR-078/080 (one
file per finding, updated not duplicated), and FR-081 (the deterministic
rollup). No LLM involved -- the SubAgent wrapping is checked structurally.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.agents.reporter import build_reporter_subagent
from foundry.coverage.store import CoverageStore
from foundry.indexer.parser import index_file
from foundry.indexer.store import IndexStore
from foundry.reporter.classification import find_forbidden_mentions, lookup_cwe
from foundry.reporter.store import ReporterStore
from foundry.reporter.tools import build_reporter_tools
from foundry.substrate.db import connect
from foundry.substrate.finding_store import Citation, FindingStore

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "data" / "toy_target" / "vulnerable_app.py"
NORMALIZED_PATH = str(TARGET.resolve().relative_to(REPO_ROOT.resolve()))


@pytest.fixture
def index(tmp_path) -> IndexStore:
    conn = connect(tmp_path / "reporter_test.sqlite3")
    result = index_file(TARGET, REPO_ROOT)
    idx = IndexStore(conn)
    idx.write_index(NORMALIZED_PATH, result.functions, result.call_edges)
    return idx


@pytest.fixture
def findings(index: IndexStore) -> FindingStore:
    return FindingStore(index.conn)


@pytest.fixture
def reporter(index: IndexStore, tmp_path) -> ReporterStore:
    return ReporterStore(index.conn, tmp_path / "reports")


@pytest.fixture
def true_positive_id(findings: FindingStore) -> int:
    fid, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="codeguard-0-input-validation-injection",
    )
    findings.assign_verdict(
        fid,
        "true-positive",
        [Citation(NORMALIZED_PATH, "get_user_by_name", "impact")],
        "grounded investigation",
        resolver=lambda c: True,
    )
    return fid


# ---------------------------------------------------------------------------
# classification.py: CWE lookup and the FR-083 denylist
# ---------------------------------------------------------------------------


def test_lookup_cwe_known_classes():
    assert lookup_cwe("sql-injection") == "CWE-89"
    assert lookup_cwe("path-traversal") == "CWE-22"
    assert lookup_cwe("hardcoded-credentials") == "CWE-798"


def test_lookup_cwe_unknown_class_returns_none():
    assert lookup_cwe("some-novel-class-nobody-mapped") is None


def test_find_forbidden_mentions_detects_model_names():
    assert "openai" in find_forbidden_mentions("This was found using OpenAI's model.")
    assert "gpt-5.6" in find_forbidden_mentions("Detected via gpt-5.6-luna.")


def test_find_forbidden_mentions_clean_text_passes():
    assert find_forbidden_mentions("A SQL injection was found in get_user_by_name.") == []


# ---------------------------------------------------------------------------
# FR-079: never publish anything but true-positive
# ---------------------------------------------------------------------------


def test_publish_accepts_true_positive(reporter, true_positive_id):
    path = reporter.publish_finding_report(
        true_positive_id, "SQL Injection", "Body.", "high", "CWE-89"
    )
    assert path.exists()
    assert "SQL Injection" in path.read_text()


@pytest.mark.parametrize("verdict", ["false-positive", "needs-review", "not-applicable", "code-quality"])
def test_publish_rejects_every_non_true_positive_verdict(reporter, findings, verdict):
    fid, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_db",
        vulnerability_class="code-quality",
        description="candidate",
        technique="exploratory",
    )
    findings.assign_verdict(fid, verdict, [], "some reasoning", resolver=lambda c: True)
    with pytest.raises(ValueError, match="FR-079"):
        reporter.publish_finding_report(fid, "Title", "Body.", "high", None)


def test_publish_rejects_unknown_finding_id(reporter):
    with pytest.raises(ValueError, match="no finding"):
        reporter.publish_finding_report(9999, "Title", "Body.", "high", None)


def test_publish_rejects_unknown_severity(reporter, true_positive_id):
    with pytest.raises(ValueError, match="unknown severity"):
        reporter.publish_finding_report(true_positive_id, "Title", "Body.", "catastrophic", None)


# ---------------------------------------------------------------------------
# FR-083: no model/provider/internal identifiers
# ---------------------------------------------------------------------------


def test_publish_rejects_report_naming_the_model(reporter, true_positive_id):
    with pytest.raises(ValueError, match="FR-083"):
        reporter.publish_finding_report(
            true_positive_id, "Title", "Found via gpt-5.6-luna using OpenAI's API.", "high", None
        )


def test_publish_rejects_title_naming_the_provider(reporter, true_positive_id):
    """The check covers the title too, not just the body."""
    with pytest.raises(ValueError, match="FR-083"):
        reporter.publish_finding_report(
            true_positive_id, "Found by Anthropic's Claude", "Clean body.", "high", None
        )


# ---------------------------------------------------------------------------
# FR-078/080: one file per finding, updated not duplicated
# ---------------------------------------------------------------------------


def test_republishing_overwrites_not_duplicates(reporter, true_positive_id):
    reporter.publish_finding_report(true_positive_id, "First title", "First body.", "low", "CWE-89")
    reporter.publish_finding_report(true_positive_id, "Updated title", "Updated body.", "critical", "CWE-89")

    published = reporter.list_published()
    assert len(published) == 1
    assert published[0]["severity"] == "critical"

    files = list(reporter.output_dir.glob("*.md"))
    assert len(files) == 1
    assert "Updated title" in files[0].read_text()
    assert "First title" not in files[0].read_text()


def test_report_filename_is_keyed_by_fingerprint(reporter, true_positive_id, findings):
    path = reporter.publish_finding_report(true_positive_id, "Title", "Body.", "medium", None)
    fingerprint = findings.get(true_positive_id)["fingerprint"]
    assert path.name == f"{fingerprint}.md"


# ---------------------------------------------------------------------------
# FR-081: the deterministic rollup
# ---------------------------------------------------------------------------


def test_rollup_counts_by_severity_and_exploited(reporter, findings, index):
    coverage = CoverageStore(index.conn)

    id1, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH, symbol="get_user_by_name",
        vulnerability_class="sql-injection", description="c", technique="t",
    )
    findings.assign_verdict(
        id1, "true-positive", [Citation(NORMALIZED_PATH, "get_user_by_name", "impact")],
        "report", resolver=lambda c: True,
    )
    reporter.publish_finding_report(id1, "Finding 1", "Body.", "critical", "CWE-89")

    id2, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH, symbol="read_uploaded_file",
        vulnerability_class="path-traversal", description="c", technique="t",
    )
    findings.assign_verdict(
        id2, "true-positive", [Citation(NORMALIZED_PATH, "read_uploaded_file", "impact")],
        "report", resolver=lambda c: True,
    )
    reporter.publish_finding_report(id2, "Finding 2", "Body.", "medium", "CWE-22")

    rollup = reporter.build_rollup(coverage)
    assert "critical: 1" in rollup
    assert "medium: 1" in rollup
    assert "2 confirmed finding(s) published" in rollup
    assert "get_user_by_name: 1 finding(s) (sql-injection)" in rollup
    assert "read_uploaded_file: 1 finding(s) (path-traversal)" in rollup


def test_rollup_includes_coverage_status(reporter, index):
    coverage = CoverageStore(index.conn)
    coverage.build_checklist(
        areas=["get_user_by_name"], goals=["sql-injection"], bar_template="{area}::{goal}"
    )
    rollup = reporter.build_rollup(coverage)
    assert "0 goal(s) credibly attempted and closed, 1 still open" in rollup
    assert "open: get_user_by_name / sql-injection" in rollup


def test_rollup_written_to_disk(reporter, index):
    coverage = CoverageStore(index.conn)
    reporter.build_rollup(coverage)
    rollup_path = reporter.output_dir / "rollup.md"
    assert rollup_path.exists()
    assert "Evaluation Rollup" in rollup_path.read_text()


# ---------------------------------------------------------------------------
# Tools and SubAgent wrapping (structural, no LLM invoked)
# ---------------------------------------------------------------------------


def test_reporter_tools_shape(findings, reporter):
    tools = build_reporter_tools(findings, reporter)
    names = {t.name for t in tools}
    assert names == {
        "list_true_positives",
        "get_finding_detail",
        "suggest_weakness_class",
        "publish_finding_report",
    }


def test_list_true_positives_tool_reports_none_when_empty(findings, reporter):
    tools = build_reporter_tools(findings, reporter)
    list_tool = next(t for t in tools if t.name == "list_true_positives")
    assert "No true-positive" in list_tool.invoke({})


def test_publish_finding_report_tool_rejects_cleanly_not_a_crash(findings, reporter, true_positive_id):
    tools = build_reporter_tools(findings, reporter)
    publish_tool = next(t for t in tools if t.name == "publish_finding_report")
    result = publish_tool.invoke({
        "finding_id": true_positive_id,
        "title": "Title",
        "report_body": "Detected via openai.",
        "severity": "high",
        "weakness_class": "CWE-89",
    })
    assert "rejected" in result
    assert reporter.list_published() == []  # nothing written


def test_suggest_weakness_class_tool(findings, reporter):
    tools = build_reporter_tools(findings, reporter)
    suggest_tool = next(t for t in tools if t.name == "suggest_weakness_class")
    assert suggest_tool.invoke({"vulnerability_class": "sql-injection"}) == "CWE-89"
    assert suggest_tool.invoke({"vulnerability_class": "something-novel"}) == "unmapped"


def test_build_reporter_subagent_shape(findings, reporter, index):
    subagent = build_reporter_subagent(findings, reporter, index)
    assert subagent["name"] == "reporter"
    assert "middleware" in subagent
    # 5 index tools + 4 reporter tools
    assert len(subagent["tools"]) == 9
