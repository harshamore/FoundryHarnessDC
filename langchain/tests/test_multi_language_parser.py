"""Phase 1 proofs: the tree-sitter-based multi-language parser
(src/foundry/indexer/parser.py) for JavaScript/TypeScript/TSX/Java/Go, and
that it plugs into the same IndexStore/evidence-gate machinery the
Python-only Phase 0 build already proved -- no LLM involved anywhere here,
same as the Python parser tests.

Fixtures live in data/multi_lang_toy_target/, one small deliberately-
vulnerable file per language, same spirit as data/toy_target/vulnerable_app.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.indexer.parser import LANGUAGE_BY_EXTENSION, detect_language, index_file
from foundry.indexer.store import IndexStore
from foundry.substrate.db import connect
from foundry.substrate.finding_store import Citation, FindingStore

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "data" / "multi_lang_toy_target"


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("app.js", "javascript"),
        ("app.jsx", "javascript"),
        ("app.mjs", "javascript"),
        ("app.cjs", "javascript"),
        ("app.ts", "typescript"),
        ("app.tsx", "tsx"),
        ("App.java", "java"),
        ("main.go", "go"),
        ("app.py", "python"),
    ],
)
def test_detect_language_by_extension(filename, expected):
    assert detect_language(Path(filename)) == expected


def test_detect_language_returns_none_for_unsupported_extension():
    assert detect_language(Path("app.rb")) is None


def test_index_file_raises_for_unsupported_extension(tmp_path):
    unsupported = tmp_path / "app.rb"
    unsupported.write_text("def foo; end")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        index_file(unsupported, tmp_path)


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


def test_javascript_functions_and_call_graph():
    result = index_file(FIXTURE_DIR / "app.js", REPO_ROOT)
    names = {fn.name for fn in result.functions}
    assert names == {
        "buildUserQuery",
        "getUserByName",
        "UserController.getUser",
        "UserController.listAdmins",
        "AdminController.getUser",
    }

    edges = {(e.caller, e.callee) for e in result.call_edges}
    assert ("getUserByName", "buildUserQuery") in edges
    assert ("UserController.getUser", "getUserByName") in edges
    assert ("AdminController.getUser", "getUserByName") in edges


def test_javascript_same_named_methods_are_class_qualified_not_collided():
    result = index_file(FIXTURE_DIR / "app.js", REPO_ROOT)
    getters = [fn for fn in result.functions if fn.name.endswith(".getUser")]
    assert {fn.name for fn in getters} == {"UserController.getUser", "AdminController.getUser"}
    # Each keeps its own source -- proof they weren't merged/overwritten.
    for fn in getters:
        assert fn.name.split(".")[0] in fn.source or "req.params.name" in fn.source


def test_javascript_vulnerability_visible_in_extracted_source():
    result = index_file(FIXTURE_DIR / "app.js", REPO_ROOT)
    by_name = {fn.name: fn for fn in result.functions}
    assert "+ username +" in by_name["buildUserQuery"].source


# ---------------------------------------------------------------------------
# TypeScript / TSX
# ---------------------------------------------------------------------------


def test_typescript_functions_and_call_graph():
    result = index_file(FIXTURE_DIR / "app.ts", REPO_ROOT)
    names = {fn.name for fn in result.functions}
    assert names == {"buildUserQuery", "getUserByName", "UserService.getUser", "AdminService.getUser"}

    edges = {(e.caller, e.callee) for e in result.call_edges}
    assert ("getUserByName", "buildUserQuery") in edges
    assert ("UserService.getUser", "getUserByName") in edges
    assert ("AdminService.getUser", "getUserByName") in edges


def test_tsx_parses_real_implementations_not_just_ambient_signatures():
    """TSX's (and TypeScript's) own bundled tags query only covers ambient
    .d.ts-style signatures -- this must be going through the javascript
    tags-query override (TAGS_QUERY_LANGUAGE_OVERRIDE) to see the real
    function bodies at all."""
    result = index_file(FIXTURE_DIR / "UserProfile.tsx", REPO_ROOT)
    names = {fn.name for fn in result.functions}
    assert {"renderGreeting", "greet", "UserProfile"} <= names
    edges = {(e.caller, e.callee) for e in result.call_edges}
    assert ("renderGreeting", "greet") in edges
    assert ("UserProfile", "renderGreeting") in edges


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


def test_java_functions_and_call_graph():
    result = index_file(FIXTURE_DIR / "UserService.java", REPO_ROOT)
    names = {fn.name for fn in result.functions}
    assert names == {
        "UserService.buildUserQuery",
        "UserService.getUserByName",
        "AdminService.getUserByName",
    }
    edges = {(e.caller, e.callee) for e in result.call_edges}
    assert ("UserService.getUserByName", "buildUserQuery") in edges


def test_java_same_named_methods_across_classes_are_qualified():
    result = index_file(FIXTURE_DIR / "UserService.java", REPO_ROOT)
    names = {fn.name for fn in result.functions}
    assert "UserService.getUserByName" in names
    assert "AdminService.getUserByName" in names
    assert "getUserByName" not in names  # never the bare, unqualified name


# ---------------------------------------------------------------------------
# Go -- no class/interface scope in the bundled tags query, so this is
# specifically what proves the _dedupe_names fallback, not qualification.
# ---------------------------------------------------------------------------


def test_go_functions_and_call_graph():
    result = index_file(FIXTURE_DIR / "main.go", REPO_ROOT)
    names = {fn.name for fn in result.functions}
    assert {"buildUserQuery", "getUserByName"} <= names
    edges = {(e.caller, e.callee) for e in result.call_edges}
    assert ("getUserByName", "buildUserQuery") in edges


def test_go_same_named_receiver_methods_are_deduped_not_dropped_or_crashed():
    """UserService.String() and AdminService.String() -- Go's bundled tags
    query has no receiver-type scope to qualify against, so both come back
    as bare "String". _dedupe_names must keep both (as "String" and
    "String#2"), not silently drop one or raise."""
    result = index_file(FIXTURE_DIR / "main.go", REPO_ROOT)
    string_methods = [fn for fn in result.functions if fn.name.startswith("String")]
    assert len(string_methods) == 2
    assert {fn.name for fn in string_methods} == {"String", "String#2"}
    # Different source -- proves they're genuinely two distinct functions,
    # not the same one duplicated.
    sources = {fn.source for fn in string_methods}
    assert len(sources) == 2


# ---------------------------------------------------------------------------
# Integration: the whole fixture directory through the real IndexStore --
# ties Phase 0's file-disambiguation fix and Phase 1's multi-language
# parser together the way a real multi-file, multi-language target would
# actually be indexed.
# ---------------------------------------------------------------------------


FIXTURE_FILES = ["app.js", "app.ts", "UserProfile.tsx", "UserService.java", "main.go"]


@pytest.fixture
def multi_lang_store(tmp_path) -> IndexStore:
    conn = connect(tmp_path / "multi_lang_test.sqlite3")
    store = IndexStore(conn)
    for filename in FIXTURE_FILES:
        result = index_file(FIXTURE_DIR / filename, REPO_ROOT)
        normalized = str((FIXTURE_DIR / filename).resolve().relative_to(REPO_ROOT.resolve()))
        store.write_index(normalized, result.functions, result.call_edges)
    return store


def test_whole_fixture_directory_indexes_without_error(multi_lang_store):
    # Every file's functions actually landed -- this would have raised a
    # sqlite3.IntegrityError at write_index() if _dedupe_names weren't
    # doing its job for main.go's two "String" methods.
    all_names = multi_lang_store.list_functions()
    assert "buildUserQuery" in all_names  # from multiple files -- ambiguous by design
    assert "String" in all_names and "String#2" in all_names


def test_get_function_body_disambiguates_across_languages_by_file(multi_lang_store):
    """buildUserQuery exists in app.js, app.ts, and main.go -- genuinely
    ambiguous without file=, same mechanism Phase 0 proved for same-language
    collisions, now exercised across different languages too."""
    with pytest.raises(ValueError, match="more than one file"):
        multi_lang_store.get_function_body("buildUserQuery")

    js_path = "data/multi_lang_toy_target/app.js"
    body = multi_lang_store.get_function_body("buildUserQuery", file=js_path)
    assert "SELECT id, username, email" in body


def test_real_evidence_gate_resolver_works_against_non_python_functions(multi_lang_store):
    """Constitution I's evidence gate is language-agnostic by construction
    -- symbol_exists() just checks (file, name) existence, so a citation
    naming a real TypeScript function resolves exactly like a Python one."""
    findings = FindingStore(multi_lang_store.conn)
    ts_path = "data/multi_lang_toy_target/app.ts"

    finding_id, _, _ = findings.queue_candidate(
        normalized_path=ts_path,
        symbol="getUserByName",
        vulnerability_class="sql-injection",
        description="candidate in a TypeScript file",
        technique="exploratory",
    )

    def real_resolver(c: Citation) -> bool:
        return multi_lang_store.symbol_exists(c.path, c.symbol)

    verdict = findings.assign_verdict(
        finding_id,
        "true-positive",
        [Citation(ts_path, "getUserByName", "impact"), Citation(ts_path, "buildUserQuery", "reachability")],
        "grounded in the real TypeScript index",
        real_resolver,
    )
    assert verdict == "true-positive"

    # A fabricated citation against a real language still gets demoted.
    finding_id2, _, _ = findings.queue_candidate(
        normalized_path=ts_path,
        symbol="getUserByName",
        vulnerability_class="sql-injection",
        description="fabricated citation",
        technique="exploratory",
    )
    verdict2 = findings.assign_verdict(
        finding_id2,
        "true-positive",
        [Citation(ts_path, "sanitizeInputProperly", "reachability")],
        "fabricated",
        real_resolver,
    )
    assert verdict2 == "needs-review"
