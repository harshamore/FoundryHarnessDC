"""Substrate proofs: atomic claim, heartbeat reclaim, fingerprint stability,
evidence-gate demotion, and the coverage-before-yield conjunction.

These exercise Constitution I, III, IV, VI, and VIII mechanically — no LLM
involved. If these fail, no amount of prompt engineering downstream fixes it.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from foundry.substrate.budget import BudgetCaps, BudgetGovernor
from foundry.substrate.db import connect
from foundry.substrate.finding_store import Citation, FindingStore, fingerprint
from foundry.substrate.work_queue import WorkQueue


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite3"


def _conn(db_path: Path) -> sqlite3.Connection:
    return connect(db_path)


# ---------------------------------------------------------------------------
# Constitution VIII: fingerprints are stable under edit
# ---------------------------------------------------------------------------


def test_fingerprint_is_deterministic():
    a = fingerprint("src/app.py", "get_user_by_name", "sql-injection")
    b = fingerprint("src/app.py", "get_user_by_name", "sql-injection")
    assert a == b


def test_fingerprint_changes_on_symbol_or_class_change():
    base = fingerprint("src/app.py", "get_user_by_name", "sql-injection")
    diff_symbol = fingerprint("src/app.py", "other_fn", "sql-injection")
    diff_class = fingerprint("src/app.py", "get_user_by_name", "path-traversal")
    assert base != diff_symbol
    assert base != diff_class


def test_requeueing_same_identity_deduplicates_despite_edited_description(db_path):
    conn = _conn(db_path)
    store = FindingStore(conn)

    id1, fp1, was_new1 = store.queue_candidate(
        normalized_path="src/app.py",
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="Detected on first sweep",
        technique="codeguard-rule:input-validation-injection",
    )
    # Simulate a re-run after an unrelated nearby edit shifted line numbers:
    # only the description text differs, identity fields are unchanged.
    id2, fp2, was_new2 = store.queue_candidate(
        normalized_path="src/app.py",
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="Detected on second sweep, function now 4 lines lower",
        technique="codeguard-rule:input-validation-injection",
    )

    assert was_new1 is True
    assert was_new2 is False  # FR-045: deduplicated, not re-filed
    assert id1 == id2
    assert fp1 == fp2


# ---------------------------------------------------------------------------
# Constitution I: evidence over assertion
# ---------------------------------------------------------------------------


def test_true_positive_accepted_when_all_citations_resolve(db_path):
    conn = _conn(db_path)
    store = FindingStore(conn)
    finding_id, _, _ = store.queue_candidate(
        normalized_path="src/app.py",
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )

    def resolver(c: Citation) -> bool:
        return c.symbol in {"get_user_by_name", "users_endpoint"}

    citations = [
        Citation("src/app.py", "users_endpoint", "reachability"),
        Citation("src/app.py", "get_user_by_name", "impact"),
    ]

    verdict = store.assign_verdict(
        finding_id, "true-positive", citations, "clean investigation", resolver
    )
    assert verdict == "true-positive"


def test_true_positive_demoted_when_a_citation_fails_to_resolve(db_path):
    conn = _conn(db_path)
    store = FindingStore(conn)
    finding_id, _, _ = store.queue_candidate(
        normalized_path="src/app.py",
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )

    def resolver(c: Citation) -> bool:
        return c.symbol == "get_user_by_name"  # "made_up_function" will not resolve

    citations = [
        Citation("src/app.py", "made_up_function", "reachability"),
        Citation("src/app.py", "get_user_by_name", "impact"),
    ]

    verdict = store.assign_verdict(
        finding_id, "true-positive", citations, "fabricated citation", resolver
    )
    assert verdict == "needs-review"  # FR-088: demoted, not rejected outright

    row = store.get(finding_id)
    assert "evidence-gate" in row["investigation_report"]


def test_true_positive_rejected_with_no_citations(db_path):
    conn = _conn(db_path)
    store = FindingStore(conn)
    finding_id, _, _ = store.queue_candidate(
        normalized_path="src/app.py",
        symbol="fn",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )
    verdict = store.assign_verdict(
        finding_id, "true-positive", [], "just trust me", resolver=lambda c: True
    )
    assert verdict == "needs-review"


# ---------------------------------------------------------------------------
# Constitution IV: claims are atomic and mortal
# ---------------------------------------------------------------------------


def test_concurrent_claims_never_double_claim(db_path):
    n_tasks = 25
    n_workers = 8

    setup_conn = _conn(db_path)
    setup_queue = WorkQueue(setup_conn, lease_seconds=60)
    task_ids = {setup_queue.enqueue("index_function", {"i": i}) for i in range(n_tasks)}
    setup_conn.close()

    claimed_by: dict[int, list[str]] = {}
    lock = threading.Lock()

    def worker(worker_id: str) -> None:
        conn = _conn(db_path)
        queue = WorkQueue(conn, lease_seconds=60)
        while True:
            task = queue.claim_next(worker_id, task_type="index_function")
            if task is None:
                break
            with lock:
                claimed_by.setdefault(task.id, []).append(worker_id)
            queue.release(task.id, worker_id, status="done")
        conn.close()

    threads = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert set(claimed_by.keys()) == task_ids  # every task claimed exactly once, none lost
    assert all(len(workers) == 1 for workers in claimed_by.values())  # never double-claimed


def test_concurrent_queue_candidate_on_shared_connection_does_not_collide(db_path):
    """A different concurrency shape than the test above: many threads
    sharing ONE connection object, not one connection each. This is what
    DeepAgents produces when an LLM turn dispatches several tool calls at
    once (e.g. a Detector subagent's exploratory hunting queuing several
    candidates "simultaneously") -- reproduces the exact "cannot start a
    transaction within a transaction" bug hit when the Cartographer
    subagent's write tools were called concurrently on a shared connection.
    """
    conn = _conn(db_path)
    store = FindingStore(conn)

    errors: list[tuple[int, str]] = []
    results: list[tuple[int, str, bool]] = []
    lock = threading.Lock()

    def queue(i: int) -> None:
        try:
            # Half the threads target the SAME finding (must dedup to one
            # row); half target distinct findings (must all succeed).
            symbol = "shared_symbol" if i % 2 == 0 else f"distinct_symbol_{i}"
            result = store.queue_candidate(
                normalized_path="app.py",
                symbol=symbol,
                vulnerability_class="x",
                description=f"from thread {i}",
                technique="t",
            )
            with lock:
                results.append(result)
        except Exception as e:  # noqa: BLE001 -- capturing for the assertion below
            with lock:
                errors.append((i, f"{type(e).__name__}: {e}"))

    n_threads = 20
    threads = [threading.Thread(target=queue, args=(i,)) for i in range(n_threads)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]

    assert errors == []
    distinct_ids = {r[0] for r in results}
    assert len(distinct_ids) == 1 + (n_threads // 2)  # one shared id + one per distinct symbol


# ---------------------------------------------------------------------------
# task_type_prefix claiming -- lets a consumer claim "any task of this
# family" (e.g. Coverage-Guide's directed-detection tasks, each queued with
# a distinct task_type encoding its own area/goal) without knowing the
# exact type up front.
# ---------------------------------------------------------------------------


def test_claim_next_by_prefix_matches_any_task_with_that_prefix(db_path):
    conn = _conn(db_path)
    queue = WorkQueue(conn)
    id1 = queue.enqueue("directed_detection:auth:injection", {"area": "auth"})
    id2 = queue.enqueue("directed_detection:files:traversal", {"area": "files"})
    queue.enqueue("other_task_type", {})

    first = queue.claim_next("worker", task_type_prefix="directed_detection:")
    second = queue.claim_next("worker", task_type_prefix="directed_detection:")
    third = queue.claim_next("worker", task_type_prefix="directed_detection:")

    assert {first.id, second.id} == {id1, id2}  # both directed tasks claimed, in some order
    assert third is None  # the non-matching task_type is never claimed by prefix


def test_claim_next_by_prefix_does_not_match_unrelated_task_type(db_path):
    conn = _conn(db_path)
    queue = WorkQueue(conn)
    queue.enqueue("other_task_type", {})

    assert queue.claim_next("worker", task_type_prefix="directed_detection:") is None


def test_claim_next_exact_type_wins_when_both_type_and_prefix_given(db_path):
    conn = _conn(db_path)
    queue = WorkQueue(conn)
    exact_id = queue.enqueue("probe", {})
    queue.enqueue("probe_extra", {})  # would also match prefix="probe"

    claimed = queue.claim_next("worker", task_type="probe", task_type_prefix="probe")
    assert claimed.id == exact_id


# ---------------------------------------------------------------------------
# Constitution III: liveness by heartbeat, never by clock
# ---------------------------------------------------------------------------


def test_stale_lease_is_reclaimable(db_path):
    conn_a = _conn(db_path)
    queue_a = WorkQueue(conn_a, lease_seconds=0)  # lease expires immediately
    task_id = queue_a.enqueue("probe", {})

    claimed = queue_a.claim_next("agent-a", task_type="probe")
    assert claimed is not None
    time.sleep(1.1)  # let the already-expired lease age past the datetime('now') boundary

    conn_b = _conn(db_path)
    queue_b = WorkQueue(conn_b, lease_seconds=60)
    reclaimed = queue_b.claim_next("agent-b", task_type="probe")
    assert reclaimed is not None
    assert reclaimed.id == task_id  # stale claim was reclaimed, not stranded


def test_fresh_lease_is_not_reclaimable(db_path):
    conn_a = _conn(db_path)
    queue_a = WorkQueue(conn_a, lease_seconds=60)
    queue_a.enqueue("probe", {})
    claimed = queue_a.claim_next("agent-a", task_type="probe")
    assert claimed is not None

    conn_b = _conn(db_path)
    queue_b = WorkQueue(conn_b, lease_seconds=60)
    reclaimed = queue_b.claim_next("agent-b", task_type="probe")
    assert reclaimed is None  # agent-a is still heartbeating; nothing to steal


# ---------------------------------------------------------------------------
# Constitution VI: coverage before yield
# ---------------------------------------------------------------------------


def test_low_yield_alone_does_not_stop_when_coverage_incomplete(db_path):
    conn = _conn(db_path)
    gov = BudgetGovernor(conn, BudgetCaps(yield_threshold=0.5))
    gov.record_spend(100.0, "detector sweep")
    stop, _reason = gov.should_stop(coverage_complete=False)
    assert stop is False


def test_stops_only_when_coverage_complete_and_yield_below_threshold(db_path):
    conn = _conn(db_path)
    gov = BudgetGovernor(conn, BudgetCaps(yield_threshold=0.5))
    gov.record_spend(100.0, "detector sweep")
    # zero true-positives recorded -> yield is 0, below threshold
    stop, _reason = gov.should_stop(coverage_complete=True)
    assert stop is True


def test_does_not_stop_when_yield_still_healthy(db_path):
    conn = _conn(db_path)
    store = FindingStore(conn)
    gov = BudgetGovernor(conn, BudgetCaps(yield_threshold=0.01))
    gov.record_spend(10.0, "detector sweep")
    finding_id, _, _ = store.queue_candidate(
        normalized_path="src/app.py",
        symbol="fn",
        vulnerability_class="sql-injection",
        description="c",
        technique="t",
    )
    store.assign_verdict(
        finding_id,
        "true-positive",
        [Citation("src/app.py", "fn", "impact")],
        "ok",
        resolver=lambda c: True,
    )
    stop, _reason = gov.should_stop(coverage_complete=True)
    assert stop is False
