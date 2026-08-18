"""Phase 2 proofs: evaluate_cycle/has_directed_work_available
(src/foundry/orchestration/loop_control.py) -- the decision logic behind
the real "detect -> triage -> check coverage -> detect the gaps -> repeat"
loop. Pure and deterministic, same as CoverageStore/BudgetGovernor
themselves -- no agent, no model, no concurrency involved here at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.coverage.store import CoverageStore
from foundry.orchestration.loop_control import evaluate_cycle, has_directed_work_available
from foundry.substrate.budget import BudgetCaps, BudgetGovernor
from foundry.substrate.db import connect
from foundry.substrate.finding_store import FindingStore


@pytest.fixture
def conn(tmp_path: Path):
    return connect(tmp_path / "loop_control_test.sqlite3")


@pytest.fixture
def coverage_store(conn) -> CoverageStore:
    return CoverageStore(conn)


@pytest.fixture
def budget_governor(conn) -> BudgetGovernor:
    return BudgetGovernor(conn, BudgetCaps(yield_threshold=0.0))


def test_evaluate_cycle_does_not_stop_while_checklist_items_remain_open(coverage_store, budget_governor):
    coverage_store.build_checklist(areas=["get_db"], goals=["sql-injection"], bar_template="{area}::{goal}")
    outcome = evaluate_cycle(coverage_store, budget_governor, cycle=1)
    assert outcome.coverage_complete is False
    assert outcome.should_stop is False
    assert outcome.still_open == 1
    assert outcome.closed_this_cycle == 0


def test_evaluate_cycle_closes_items_with_real_evidence(coverage_store, budget_governor, conn):
    coverage_store.build_checklist(areas=["get_db"], goals=["sql-injection"], bar_template="{area}::{goal}")
    findings = FindingStore(conn)
    findings.queue_candidate(
        normalized_path="app.py",
        symbol="get_db",
        vulnerability_class="sql-injection",
        description="found it",
        technique="exploratory",
    )
    outcome = evaluate_cycle(coverage_store, budget_governor, cycle=1)
    assert outcome.closed_this_cycle == 1
    assert outcome.still_open == 0
    assert outcome.coverage_complete is True


def test_evaluate_cycle_stops_once_coverage_complete_and_yield_below_threshold(coverage_store, conn):
    # BudgetGovernor.trailing_yield() returns +inf with zero spend recorded
    # ("no spend yet: never trips the low-yield stop"), and should_stop()'s
    # comparison is a strict less-than -- yield_threshold=0.0 (this file's
    # default fixture) means an exact 0.0 yield does not trip it either.
    # Record real spend with no confirmed true-positives (yield=0.0) against
    # a positive threshold, so it's genuinely below, not merely equal.
    governor = BudgetGovernor(conn, BudgetCaps(yield_threshold=0.5))
    coverage_store.build_checklist(areas=["a"], goals=["g"], bar_template="{area}::{goal}")
    coverage_store.record_sweep("a", "g", note="checked, clean")
    governor.record_spend(10.0, "detection sweep")
    outcome = evaluate_cycle(coverage_store, governor, cycle=1)
    assert outcome.coverage_complete is True
    assert outcome.should_stop is True
    assert "coverage complete" in outcome.stop_reason


def test_evaluate_cycle_never_stops_on_yield_alone_while_coverage_incomplete(conn):
    """Constitution VI's conjunction, exercised through evaluate_cycle: a
    hard spend cap is the only thing that can stop a run before coverage
    is complete."""
    coverage = CoverageStore(conn)
    coverage.build_checklist(areas=["a", "b"], goals=["g"], bar_template="{area}::{goal}")
    coverage.record_sweep("a", "g", note="checked")  # only one of two closes
    governor = BudgetGovernor(conn, BudgetCaps(yield_threshold=999.0))  # impossibly high -- would stop if checked alone
    outcome = evaluate_cycle(coverage, governor, cycle=1)
    assert outcome.coverage_complete is False
    assert outcome.should_stop is False


def test_evaluate_cycle_hard_spend_cap_stops_even_with_coverage_incomplete(conn):
    coverage = CoverageStore(conn)
    coverage.build_checklist(areas=["a"], goals=["g"], bar_template="{area}::{goal}")  # left open on purpose
    governor = BudgetGovernor(conn, BudgetCaps(max_spend_usd=1.0))
    governor.record_spend(5.0, "over budget")
    outcome = evaluate_cycle(coverage, governor, cycle=1)
    assert outcome.coverage_complete is False
    assert outcome.should_stop is True
    assert "hard spend cap" in outcome.stop_reason


def test_evaluate_cycle_reports_the_cycle_number_passed_in(coverage_store, budget_governor):
    outcome = evaluate_cycle(coverage_store, budget_governor, cycle=7)
    assert outcome.cycle == 7


def test_has_directed_work_available_true_when_items_open(coverage_store):
    coverage_store.build_checklist(areas=["a"], goals=["g"], bar_template="{area}::{goal}")
    assert has_directed_work_available(coverage_store) is True


def test_has_directed_work_available_false_when_all_closed(coverage_store):
    coverage_store.build_checklist(areas=["a"], goals=["g"], bar_template="{area}::{goal}")
    coverage_store.record_sweep("a", "g", note="checked, clean")
    coverage_store.review_cycle()
    assert has_directed_work_available(coverage_store) is False


def test_has_directed_work_available_false_when_no_checklist_built_yet(coverage_store):
    assert has_directed_work_available(coverage_store) is False
