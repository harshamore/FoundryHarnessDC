"""Coverage-Guide proofs: FR-067 (derive checklist), FR-068 (refuse to
invent goals), FR-069 (evidence-based check-off), FR-070 (directed tasks),
FR-071 (the coverage-complete flag, including the empty-checklist edge
case), and FR-074 (idempotent, not rebuilt from scratch). No LLM involved
-- every MUST-level requirement here is deterministic by design.
"""
from __future__ import annotations

import threading

import pytest

from foundry.agents.coverage_guide import build_coverage_guide_subagent
from foundry.coverage.store import CoverageStore
from foundry.coverage.tools import build_coverage_tools
from foundry.substrate.budget import BudgetCaps, BudgetGovernor
from foundry.substrate.db import connect
from foundry.substrate.finding_store import FindingStore
from foundry.substrate.work_queue import WorkQueue


@pytest.fixture
def coverage(tmp_path) -> CoverageStore:
    conn = connect(tmp_path / "coverage_test.sqlite3")
    return CoverageStore(conn)


# ---------------------------------------------------------------------------
# FR-067/FR-068: derive the checklist, refuse to invent goals
# ---------------------------------------------------------------------------


def test_build_checklist_creates_area_by_goal_items(coverage):
    open_count = coverage.build_checklist(
        areas=["fn_a", "fn_b"], goals=["sql-injection", "path-traversal"], bar_template="{area}::{goal}"
    )
    assert open_count == 4  # 2 areas x 2 goals
    items = coverage.open_items()
    pairs = {(r["area"], r["goal"]) for r in items}
    assert pairs == {
        ("fn_a", "sql-injection"),
        ("fn_a", "path-traversal"),
        ("fn_b", "sql-injection"),
        ("fn_b", "path-traversal"),
    }
    assert items[0]["bar"] == f"{items[0]['area']}::{items[0]['goal']}"


def test_build_checklist_rejects_empty_areas(coverage):
    with pytest.raises(ValueError, match="FR-068"):
        coverage.build_checklist(areas=[], goals=["sql-injection"], bar_template="{area}::{goal}")


def test_build_checklist_rejects_empty_goals(coverage):
    with pytest.raises(ValueError, match="FR-068"):
        coverage.build_checklist(areas=["fn_a"], goals=[], bar_template="{area}::{goal}")


# ---------------------------------------------------------------------------
# FR-074: idempotent -- re-running doesn't reset closed items or duplicate
# ---------------------------------------------------------------------------


def test_rebuilding_checklist_does_not_reset_closed_items(coverage):
    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="{area}::{goal}")
    item = coverage.open_items()[0]
    coverage.conn.execute(
        "UPDATE coverage_checklist SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
        (item["id"],),
    )

    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="{area}::{goal}")

    assert coverage.open_items() == []
    assert len(coverage.closed_items()) == 1  # not duplicated, still closed


# ---------------------------------------------------------------------------
# FR-069: evidence-based check-off, from both the finding store and the
# coverage log -- "found nothing" satisfies coverage exactly as well as a
# finding
# ---------------------------------------------------------------------------


def test_review_cycle_closes_items_with_finding_store_evidence(coverage):
    findings = FindingStore(coverage.conn)
    coverage.build_checklist(
        areas=["get_user_by_name"], goals=["sql-injection"], bar_template="check {area} for {goal}"
    )
    findings.queue_candidate(
        normalized_path="app.py",
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="codeguard-0-input-validation-injection",
    )

    result = coverage.review_cycle()
    assert len(result["closed_this_cycle"]) == 1
    assert result["still_open"] == []
    assert coverage.is_complete() is True


def test_review_cycle_closes_items_via_coverage_log_even_with_no_finding(coverage):
    """"We swept X for Y and found nothing" satisfies "X: Y" exactly as
    well as filing a finding (spec.md FR-069)."""
    coverage.build_checklist(areas=["get_db"], goals=["hardcoded-credentials"], bar_template="{area}::{goal}")
    coverage.record_sweep("get_db", "codeguard-1-hardcoded-credentials", note="checked, clean")

    result = coverage.review_cycle()
    assert len(result["closed_this_cycle"]) == 1
    assert coverage.is_complete() is True


def test_review_cycle_leaves_unattempted_items_open(coverage):
    coverage.build_checklist(
        areas=["fn_a", "fn_b"], goals=["sql-injection"], bar_template="{area}::{goal}"
    )
    findings = FindingStore(coverage.conn)
    findings.queue_candidate(
        normalized_path="app.py",
        symbol="fn_a",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )

    result = coverage.review_cycle()
    assert len(result["closed_this_cycle"]) == 1
    assert len(result["still_open"]) == 1
    assert coverage.is_complete() is False


# ---------------------------------------------------------------------------
# FR-070: directed tasks for gaps, deduplicated
# ---------------------------------------------------------------------------


def test_queue_directed_tasks_one_per_open_item(coverage):
    coverage.build_checklist(
        areas=["fn_a", "fn_b"], goals=["sql-injection"], bar_template="check {area} for {goal}"
    )
    work_queue = WorkQueue(coverage.conn)

    queued = coverage.queue_directed_tasks(work_queue)
    assert queued == 2

    pending = coverage.conn.execute(
        "SELECT task_type FROM work_queue WHERE status = 'pending'"
    ).fetchall()
    assert {r["task_type"] for r in pending} == {
        "directed_detection:fn_a:sql-injection",
        "directed_detection:fn_b:sql-injection",
    }


def test_queue_directed_tasks_does_not_duplicate_on_repeat_calls(coverage):
    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="{area}::{goal}")
    work_queue = WorkQueue(coverage.conn)

    first = coverage.queue_directed_tasks(work_queue)
    second = coverage.queue_directed_tasks(work_queue)

    assert first == 1
    assert second == 0  # already pending, not re-queued
    total = coverage.conn.execute("SELECT COUNT(*) AS n FROM work_queue").fetchone()["n"]
    assert total == 1


def test_queue_directed_tasks_skips_items_that_became_closed(coverage):
    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="{area}::{goal}")
    work_queue = WorkQueue(coverage.conn)
    coverage.queue_directed_tasks(work_queue)

    findings = FindingStore(coverage.conn)
    findings.queue_candidate(
        normalized_path="app.py",
        symbol="fn_a",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )
    coverage.review_cycle()

    assert coverage.queue_directed_tasks(work_queue) == 0  # closed now, nothing left to queue


# ---------------------------------------------------------------------------
# FR-071: coverage-complete flag, including the empty-checklist edge case
# ---------------------------------------------------------------------------


def test_is_complete_false_before_any_checklist_built(coverage):
    assert coverage.is_complete() is False  # not "vacuously complete", "never built"


def test_is_complete_false_while_items_open(coverage):
    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="{area}::{goal}")
    assert coverage.is_complete() is False


def test_clear_checklist_resets_to_incomplete(coverage):
    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="{area}::{goal}")
    findings = FindingStore(coverage.conn)
    findings.queue_candidate(
        normalized_path="app.py",
        symbol="fn_a",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )
    coverage.review_cycle()
    assert coverage.is_complete() is True

    coverage.clear_checklist()  # FR-071: operator changed the goals
    assert coverage.is_complete() is False
    assert coverage.open_items() == []
    assert coverage.closed_items() == []


# ---------------------------------------------------------------------------
# Constitution VI integration: the real BudgetGovernor, wired to a real
# coverage-complete flag instead of a hand-typed True/False
# ---------------------------------------------------------------------------


def test_budget_governor_wired_to_real_coverage_flag(coverage):
    gov = BudgetGovernor(coverage.conn, BudgetCaps(yield_threshold=0.5))
    gov.record_spend(10.0, "detector sweep")

    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="{area}::{goal}")
    stop, reason = gov.should_stop(coverage_complete=coverage.is_complete())
    assert stop is False  # coverage incomplete, must not stop on yield alone

    findings = FindingStore(coverage.conn)
    findings.queue_candidate(
        normalized_path="app.py",
        symbol="fn_a",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )
    coverage.review_cycle()
    stop, reason = gov.should_stop(coverage_complete=coverage.is_complete())
    assert stop is True  # now coverage complete and yield (0 true-positives / $10) is below threshold


# ---------------------------------------------------------------------------
# Concurrency (same pattern proven elsewhere; one check here for consistency)
# ---------------------------------------------------------------------------


def test_concurrent_record_sweep_on_shared_connection_does_not_collide(coverage):
    errors: list[str] = []
    lock = threading.Lock()

    def sweep(i: int) -> None:
        try:
            coverage.record_sweep(f"area_{i}", "exploratory", note="ok")
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=sweep, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]

    assert errors == []
    total = coverage.conn.execute("SELECT COUNT(*) AS n FROM coverage_log").fetchone()["n"]
    assert total == 10


# ---------------------------------------------------------------------------
# Tools and SubAgent wrapping (structural, no LLM invoked)
# ---------------------------------------------------------------------------


def test_get_coverage_report_tool_reports_empty_state(coverage):
    tools = build_coverage_tools(coverage)
    report_tool = next(t for t in tools if t.name == "get_coverage_report")
    result = report_tool.invoke({})
    assert "0 closed, 0 still open" in result


def test_get_coverage_report_tool_reports_populated_state(coverage):
    coverage.build_checklist(areas=["fn_a"], goals=["sql-injection"], bar_template="check {area} for {goal}")
    tools = build_coverage_tools(coverage)
    report_tool = next(t for t in tools if t.name == "get_coverage_report")
    result = report_tool.invoke({})
    assert "0 closed, 1 still open" in result
    assert "fn_a / sql-injection" in result


def test_build_coverage_guide_subagent_shape(coverage):
    subagent = build_coverage_guide_subagent(coverage)
    assert subagent["name"] == "coverage-guide"
    assert "middleware" in subagent
    assert len(subagent["tools"]) == 1  # only get_coverage_report -- no write tool at all
