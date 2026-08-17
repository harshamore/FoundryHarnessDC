"""Cartographer proofs: FR-036a (the fallback guarantee) and the security
map store's persistence/digest behavior. No LLM involved -- the SubAgent
wrapping is checked structurally, not by invoking a model.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from foundry.agents.cartographer import build_cartographer_subagent
from foundry.cartographer.fallback import (
    fallback_architecture_overview,
    fallback_attack_surface,
    fallback_data_flows,
    fallback_threat_model,
    fallback_trust_boundaries,
)
from foundry.cartographer.store import SECTIONS, SecurityMapStore
from foundry.indexer.parser import index_file
from foundry.indexer.store import IndexStore
from foundry.substrate.db import connect

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "data" / "toy_target" / "vulnerable_app.py"
NORMALIZED_PATH = str(TARGET.resolve().relative_to(REPO_ROOT.resolve()))


@pytest.fixture
def index(tmp_path) -> IndexStore:
    conn = connect(tmp_path / "cartographer_test.sqlite3")
    result = index_file(TARGET, REPO_ROOT)
    idx = IndexStore(conn)
    idx.write_index(NORMALIZED_PATH, result.functions, result.call_edges)
    return idx


@pytest.fixture
def security_map(index: IndexStore) -> SecurityMapStore:
    return SecurityMapStore(index.conn)


# ---------------------------------------------------------------------------
# FR-036a: the fallback guarantee -- no section is ever empty
# ---------------------------------------------------------------------------


def test_all_fallbacks_produce_nonempty_content(index):
    assert fallback_architecture_overview(NORMALIZED_PATH, index).strip()
    assert fallback_attack_surface(NORMALIZED_PATH, index).strip()
    assert fallback_trust_boundaries().strip()
    assert fallback_data_flows().strip()
    assert fallback_threat_model().strip()


def test_map_is_complete_after_writing_only_fallbacks(security_map, index):
    assert security_map.is_complete() is False  # nothing written yet

    security_map.write_section(
        "architecture_overview", fallback_architecture_overview(NORMALIZED_PATH, index), source="fallback"
    )
    security_map.write_section(
        "attack_surface", fallback_attack_surface(NORMALIZED_PATH, index), source="fallback"
    )
    security_map.write_section("trust_boundaries", fallback_trust_boundaries(), source="fallback")
    security_map.write_section("data_flows", fallback_data_flows(), source="fallback")
    security_map.write_section("threat_model", fallback_threat_model(), source="fallback")

    assert security_map.is_complete() is True
    for section in SECTIONS:
        assert security_map.get_source(section) == "fallback"


def test_fallback_architecture_overview_cites_real_functions(index):
    content = fallback_architecture_overview(NORMALIZED_PATH, index)
    assert "get_user_by_name" in content
    assert "read_uploaded_file" in content


# ---------------------------------------------------------------------------
# SecurityMapStore: persistence, replace-not-duplicate, validation
# ---------------------------------------------------------------------------


def test_write_and_read_round_trip(security_map):
    security_map.write_section("architecture_overview", "a small Flask app", source="fallback")
    assert security_map.get_section("architecture_overview") == "a small Flask app"


def test_rewriting_a_section_replaces_not_duplicates(security_map):
    security_map.write_section("architecture_overview", "fallback version", source="fallback")
    security_map.write_section("architecture_overview", "llm-authored version", source="llm")

    assert security_map.get_section("architecture_overview") == "llm-authored version"
    assert security_map.get_source("architecture_overview") == "llm"

    rows = security_map.conn.execute(
        "SELECT COUNT(*) AS n FROM security_map WHERE section = 'architecture_overview'"
    ).fetchone()
    assert rows["n"] == 1  # replaced, not duplicated


def test_unknown_section_rejected(security_map):
    with pytest.raises(ValueError):
        security_map.write_section("not_a_real_section", "content", source="fallback")


def test_unknown_source_rejected(security_map):
    with pytest.raises(ValueError):
        security_map.write_section("architecture_overview", "content", source="not_llm_or_fallback")


# ---------------------------------------------------------------------------
# FR-035: the digest
# ---------------------------------------------------------------------------


def test_digest_includes_only_written_sections(security_map):
    security_map.write_section("architecture_overview", "overview text", source="fallback")
    digest = security_map.digest()
    assert "Architecture Overview" in digest
    assert "overview text" in digest
    assert "Attack Surface" not in digest  # not written yet


def test_digest_truncates_long_sections(security_map):
    long_content = "x" * 2000
    security_map.write_section("architecture_overview", long_content, source="fallback")
    digest = security_map.digest(max_chars_per_section=100)
    assert len(digest) < 2000
    assert "…" in digest


# ---------------------------------------------------------------------------
# Concurrent writes on one shared connection (DeepAgents can dispatch
# several tool calls from a single LLM turn on real threads -- reproduces
# the exact "cannot start a transaction within a transaction" bug hit when
# the Cartographer subagent's five write tools were called concurrently)
# ---------------------------------------------------------------------------


def test_concurrent_section_writes_on_shared_connection_do_not_collide(security_map):
    errors: list[tuple[str, str]] = []
    lock = threading.Lock()

    def write(section: str) -> None:
        try:
            security_map.write_section(section, f"content for {section}", source="llm")
        except Exception as e:  # noqa: BLE001 -- capturing for the assertion below
            with lock:
                errors.append((section, f"{type(e).__name__}: {e}"))

    threads = [threading.Thread(target=write, args=(s,)) for s in SECTIONS]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]

    assert errors == []
    assert security_map.is_complete() is True
    for section in SECTIONS:
        assert security_map.get_section(section) == f"content for {section}"


# ---------------------------------------------------------------------------
# SubAgent wrapping (structural check, no LLM invoked)
# ---------------------------------------------------------------------------


def test_build_cartographer_subagent_shape(security_map, index):
    subagent = build_cartographer_subagent(security_map, index)
    assert subagent["name"] == "cartographer"
    assert "system_prompt" in subagent
    # 5 read-only index tools + 5 section-write tools
    assert len(subagent["tools"]) == 10
