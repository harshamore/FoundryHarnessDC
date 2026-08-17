"""Indexer proofs: FR-020 (deterministic parser-based inventory), FR-021
(call graph), FR-022 (query interface), and the real evidence-gate resolver
that replaces the Substrate section's fake symbol table. No LLM involved --
the SubAgent/tool wrapping is checked structurally, not by invoking a model.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from foundry.agents.indexer import build_indexer_subagent
from foundry.indexer.parser import index_file
from foundry.indexer.store import IndexStore
from foundry.indexer.tools import build_index_tools
from foundry.substrate.db import connect
from foundry.substrate.finding_store import Citation, FindingStore

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "data" / "toy_target" / "vulnerable_app.py"
NORMALIZED_PATH = str(TARGET.resolve().relative_to(REPO_ROOT.resolve()))

EXPECTED_FUNCTIONS = {
    "get_db",
    "get_user_by_name",
    "read_uploaded_file",
    "users_endpoint",
    "files_endpoint",
}


@pytest.fixture
def store(tmp_path) -> IndexStore:
    conn = connect(tmp_path / "index_test.sqlite3")
    result = index_file(TARGET, REPO_ROOT)
    s = IndexStore(conn)
    s.write_index(NORMALIZED_PATH, result.functions, result.call_edges)
    return s


# ---------------------------------------------------------------------------
# FR-020: deterministic parser-based function inventory
# ---------------------------------------------------------------------------


def test_parser_finds_all_functions():
    result = index_file(TARGET, REPO_ROOT)
    names = {fn.name for fn in result.functions}
    assert EXPECTED_FUNCTIONS <= names


def test_parser_is_deterministic():
    # Two independent parses of the same file produce identical results --
    # there is no model call or nondeterminism anywhere in FR-020's inventory.
    a = index_file(TARGET, REPO_ROOT)
    b = index_file(TARGET, REPO_ROOT)
    assert {f.name for f in a.functions} == {f.name for f in b.functions}
    assert set(a.call_edges) == set(b.call_edges)


# ---------------------------------------------------------------------------
# FR-021: call graph, direct static calls
# ---------------------------------------------------------------------------


def test_call_graph_direct_calls_captured():
    result = index_file(TARGET, REPO_ROOT)
    edges = {(e.caller, e.callee) for e in result.call_edges}
    assert ("get_user_by_name", "get_db") in edges
    assert ("users_endpoint", "get_user_by_name") in edges
    assert ("files_endpoint", "read_uploaded_file") in edges


# ---------------------------------------------------------------------------
# FR-022: query interface
# ---------------------------------------------------------------------------


def test_get_function_body_returns_real_source(store):
    body = store.get_function_body("get_user_by_name")
    assert body is not None
    assert "def get_user_by_name" in body
    assert "SELECT id, username, email" in body


def test_get_function_body_unknown_symbol_returns_none(store):
    assert store.get_function_body("this_function_does_not_exist") is None


def test_get_callers_and_get_callees_are_consistent(store):
    assert "users_endpoint" in store.get_callers("get_user_by_name")
    assert "get_user_by_name" in store.get_callees("users_endpoint")


def test_find_symbol_reports_location(store):
    row = store.find_symbol("get_user_by_name")
    assert row is not None
    assert row["file"] == NORMALIZED_PATH
    assert row["lineno"] > 0


def test_full_text_search_finds_substring(store):
    matches = store.full_text_search("SELECT id, username, email")
    assert "get_user_by_name" in matches


# ---------------------------------------------------------------------------
# Concurrent reads on one shared connection -- Python's sqlite3.Connection
# is not safe for truly simultaneous access from multiple threads even for
# plain SELECTs (reproduced live as InterfaceError / a nonsensical
# IndexError from sqlite3.Row.__getitem__ when DeepAgents dispatched
# several read-only tool calls concurrently from one LLM turn)
# ---------------------------------------------------------------------------


def test_concurrent_reads_on_shared_connection_do_not_corrupt(store):
    errors: list[tuple[int, str]] = []
    lock = threading.Lock()

    def read_stuff(i: int) -> None:
        try:
            for _ in range(50):
                store.full_text_search("def")
                store.get_function_body("get_user_by_name")
                store.get_callers("get_user_by_name")
                store.find_symbol("read_uploaded_file")
        except Exception as e:  # noqa: BLE001 -- capturing for the assertion below
            with lock:
                errors.append((i, f"{type(e).__name__}: {e}"))

    threads = [threading.Thread(target=read_stuff, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]

    assert errors == []


# ---------------------------------------------------------------------------
# FR-025/026: atomic, idempotent re-index
# ---------------------------------------------------------------------------


def test_reindexing_same_file_does_not_duplicate(tmp_path):
    conn = connect(tmp_path / "reindex_test.sqlite3")
    s = IndexStore(conn)
    result = index_file(TARGET, REPO_ROOT)

    s.write_index(NORMALIZED_PATH, result.functions, result.call_edges)
    first_count = len(s.list_functions(file=NORMALIZED_PATH))

    s.write_index(NORMALIZED_PATH, result.functions, result.call_edges)
    second_count = len(s.list_functions(file=NORMALIZED_PATH))

    assert first_count == second_count == len(result.functions)


# ---------------------------------------------------------------------------
# Constitution I: the real resolver, replacing the Substrate section's fake one
# ---------------------------------------------------------------------------


def test_real_resolver_wired_into_evidence_gate(store):
    findings = FindingStore(store.conn)  # same connection, shared schema
    finding_id, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="get_user_by_name",
        vulnerability_class="sql-injection",
        description="candidate",
        technique="exploratory",
    )

    def real_resolver(c: Citation) -> bool:
        return store.symbol_exists(c.path, c.symbol)

    # Clean citations against REAL function names the parser found.
    verdict = findings.assign_verdict(
        finding_id,
        "true-positive",
        [
            Citation(NORMALIZED_PATH, "users_endpoint", "reachability"),
            Citation(NORMALIZED_PATH, "get_user_by_name", "impact"),
        ],
        "grounded in the real index",
        real_resolver,
    )
    assert verdict == "true-positive"

    # A fabricated citation still gets demoted -- same mechanism as the
    # Substrate section's fake resolver, now checked against real parsed code.
    finding_id2, _, _ = findings.queue_candidate(
        normalized_path=NORMALIZED_PATH,
        symbol="read_uploaded_file",
        vulnerability_class="path-traversal",
        description="candidate",
        technique="exploratory",
    )
    verdict2 = findings.assign_verdict(
        finding_id2,
        "true-positive",
        [Citation(NORMALIZED_PATH, "sanitize_path_properly", "reachability")],
        "fabricated",
        real_resolver,
    )
    assert verdict2 == "needs-review"


# ---------------------------------------------------------------------------
# Tool / SubAgent wrapping (structural checks, no LLM invoked)
# ---------------------------------------------------------------------------


def test_index_tools_wrap_store_correctly(store):
    tools = build_index_tools(store)
    names = {t.name for t in tools}
    assert names == {"get_function_body", "get_callers", "get_callees", "find_symbol", "full_text_search"}

    get_function_body_tool = next(t for t in tools if t.name == "get_function_body")
    result = get_function_body_tool.invoke({"name": "get_user_by_name"})
    assert "def get_user_by_name" in result


def test_build_indexer_subagent_shape(store):
    subagent = build_indexer_subagent(store)
    assert subagent["name"] == "indexer"
    assert "system_prompt" in subagent
    assert len(subagent["tools"]) == 5


def test_indexer_subagent_restricts_default_filesystem_tools(store):
    """Regression test: a subagent otherwise gets DeepAgents' default
    filesystem middleware (ls/read_file/write_file/edit_file/delete/glob/
    grep/execute) bound to an empty virtual filesystem regardless of the
    `tools` list -- observed live as the model calling `ls /` instead of
    the real index tools it was given, and reporting "no code discoverable"
    for every section. build_indexer_subagent must override this down to
    just the one tool the framework requires (read_file cannot be
    excluded), not the full default set."""
    subagent = build_indexer_subagent(store)
    assert "middleware" in subagent
    fs_middleware = subagent["middleware"][0]
    tool_names = {t.name for t in fs_middleware.tools}
    assert tool_names == {"read_file"}
    assert "ls" not in tool_names
    assert "glob" not in tool_names
