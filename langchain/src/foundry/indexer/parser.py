"""Deterministic multi-language indexer: function inventory and call graph.

spec.md FR-020: the function inventory MUST be produced by a deterministic
parser (tree-sitter, ctags, language-server, "or equivalent"); an LLM MAY
augment it but MUST NOT be the sole source. Python keeps its own `ast`-based
path (unchanged, proven since the Substrate section) since `ast` already
satisfies FR-020 for Python without an extra dependency. Every other
supported language (Phase 1's agreed v1 set -- JavaScript/TypeScript/TSX,
Java, Go) goes through tree-sitter instead, using `tree-sitter-language-
pack`'s bundled "tags" queries (the same @definition.function/
@definition.method/@reference.call convention ctags/nvim-treesitter use)
rather than hand-written per-language queries -- verified directly against
real parsed trees for every language in this set before being relied on
here, not assumed to work from the package's docs alone. No model call
anywhere in this file, for either path.

FR-021: call graph covering at minimum direct static calls -- for the
tree-sitter path, a call is attributed to its innermost enclosing
function/method definition by source-byte-range containment, mirroring
what the `ast` path already does by walking each function's own body
statements.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node, Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser, get_tags_query


@dataclass(frozen=True)
class FunctionDef:
    name: str
    file: str  # path normalized relative to the repo root
    lineno: int
    end_lineno: int
    source: str


@dataclass(frozen=True)
class CallEdge:
    caller: str
    callee: str


@dataclass(frozen=True)
class IndexResult:
    functions: list[FunctionDef]
    call_edges: list[CallEdge]


# Extension -> tree-sitter-language-pack language name. Deliberately a
# fixed, explicit set (Phase 1's agreed v1 languages) rather than the ~371
# languages tree_sitter_language_pack can detect -- broader support is
# architecturally additive later (add an entry here, plus a
# TAGS_QUERY_LANGUAGE_OVERRIDE entry if that language's own bundled tags
# query doesn't cover real implementations), not a redesign, but each one
# needs its own verification before being trusted, same as these four were.
LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
}

# TypeScript/TSX's own bundled tags query only covers ambient signatures
# (function_signature/method_signature -- .d.ts-style declarations), not
# real function/method bodies. Verified directly: a TS/TSX parse tree's
# concrete function_declaration/method_definition/call_expression nodes are
# the same node type *names* JavaScript's grammar produces (TS's grammar
# extends JS's) -- so JavaScript's tags query text, which does cover real
# implementations, compiles and matches correctly when run against a
# TS/TSX-parsed tree. The query object must still be built from the
# *parsing* language's own `Language` (see `get_language(language)` below,
# not `get_language(query_language)`) -- node type names are shared text,
# but each grammar's internal type IDs are its own, and a query compiled
# against the wrong Language object silently matches nothing (verified:
# compiling the JS query against `get_language("javascript")` and running
# it on a TypeScript-parsed tree returns zero matches, even though it
# matches correctly when compiled against `get_language("typescript")`).
TAGS_QUERY_LANGUAGE_OVERRIDE: dict[str, str] = {
    "typescript": "javascript",
    "tsx": "javascript",
}


def detect_language(path: Path) -> str | None:
    """The tree-sitter-language-pack language name for `path`'s extension,
    or None if it's not one of Phase 1's supported languages."""
    return LANGUAGE_BY_EXTENSION.get(path.suffix.lower())


def _callee_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        # Best-effort: the attribute/method name only, no receiver-type
        # resolution (FR-021a "SHOULD resolve indirect dispatch" is a stretch
        # goal, not attempted here).
        return func.attr
    return None


def _dedupe_names(functions: list[FunctionDef]) -> list[FunctionDef]:
    """Two functions with the same name in the same file are a real
    possibility once anything past a single flat module is in scope (two
    classes each defining `toString`, a redefinition, Go methods on two
    different receiver types both named `String` -- the tree-sitter path's
    class-qualification below doesn't cover every language equally, e.g.
    Go's bundled tags query has no class/interface scope to qualify
    against). `functions` is UNIQUE(file, name) (see indexer/store.py), so
    silently keeping only one -- or letting the later INSERT raise -- would
    either lose a real finding surface or crash indexing. Disambiguate
    instead: first occurrence keeps its name, later ones get a stable
    `#2`, `#3`, ... suffix, in source order."""
    seen: dict[str, int] = {}
    deduped: list[FunctionDef] = []
    for fn in functions:
        count = seen.get(fn.name, 0) + 1
        seen[fn.name] = count
        if count == 1:
            deduped.append(fn)
        else:
            deduped.append(
                FunctionDef(
                    name=f"{fn.name}#{count}",
                    file=fn.file,
                    lineno=fn.lineno,
                    end_lineno=fn.end_lineno,
                    source=fn.source,
                )
            )
    return deduped


def _index_file_python(path: Path, repo_root: Path) -> IndexResult:
    """Parse one Python file into a function inventory and a direct-call
    graph, using Python's own `ast` module -- already satisfies FR-020 for
    Python without an extra dependency, unchanged since the Substrate
    section."""
    source_text = path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(path))
    normalized_path = str(path.resolve().relative_to(repo_root.resolve()))
    source_lines = source_text.splitlines()

    function_nodes: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_nodes.append((node.name, node))

    functions: list[FunctionDef] = []
    edges: list[CallEdge] = []

    for name, node in function_nodes:
        # Include any decorators in the extracted range, so `get_function_body`
        # shows e.g. `@app.route("/users")` above the `def` line. FR-031
        # (attack-surface enumeration) needs route/exposure metadata exactly
        # like this, and it lives only in decorators -- excluding them (as
        # the call-graph walk below deliberately still does, for a different
        # reason) meant a Cartographer reading only `source` could never see
        # it, even though the information exists in the file. `node.lineno`
        # itself already points at the `def` line, not the decorator, so this
        # is the one place decorators need to be added back in by hand.
        start_line = node.decorator_list[0].lineno if node.decorator_list else node.lineno
        end = getattr(node, "end_lineno", node.lineno)
        body_source = "\n".join(source_lines[start_line - 1 : end])
        functions.append(
            FunctionDef(
                name=name, file=normalized_path, lineno=start_line, end_lineno=end, source=body_source
            )
        )
        # Walk only the function's own body statements -- not `decorator_list`
        # or argument defaults, which execute at def-time, not call-time, and
        # would otherwise show up as misleading "calls" (e.g. a Flask
        # `@app.route(...)` decorator recorded as the function calling
        # `route`).
        for stmt in node.body:
            for inner in ast.walk(stmt):
                if isinstance(inner, ast.Call):
                    callee = _callee_name(inner)
                    if callee:
                        edges.append(CallEdge(caller=name, callee=callee))

    return IndexResult(functions=_dedupe_names(functions), call_edges=edges)


def _index_file_tree_sitter(path: Path, repo_root: Path, language: str) -> IndexResult:
    """Parse one file in a non-Python supported language via tree-sitter,
    using the bundled tags query's @definition.function/@definition.method/
    @definition.class/@definition.interface/@reference.call captures (see
    TAGS_QUERY_LANGUAGE_OVERRIDE above for why the query text's language
    and the parse language can differ).

    Known, deliberate scope limits, not silently glossed over:
    - No decorator/annotation inclusion for non-Python languages (Python's
      FR-031 route-exposure fix does this; replicating it per-language
      grammar is a follow-up, not attempted here).
    - Go methods are never class-qualified (Go's bundled tags query has no
      class/interface scope) -- `_dedupe_names` is the safety net for the
      resulting same-file collisions (e.g. two receiver types both
      implementing `String()`), not true disambiguation by receiver type.
    """
    source_bytes = path.read_bytes()
    normalized_path = str(path.resolve().relative_to(repo_root.resolve()))

    parser = get_parser(language)
    tree = parser.parse(source_bytes)

    query_language = TAGS_QUERY_LANGUAGE_OVERRIDE.get(language, language)
    query_source = get_tags_query(query_language)
    if not query_source:
        raise ValueError(f"No bundled tags query for language '{language}' (queried as '{query_language}')")

    ts_language = get_language(language)  # the parsing language's own grammar -- see module docstring
    query = Query(ts_language, query_source)
    cursor = QueryCursor(query)
    matches = cursor.matches(tree.root_node)

    def text(node: Node) -> str:
        return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    function_scopes: list[tuple[str, Node]] = []  # (bare name, definition node)
    class_scopes: list[tuple[str, Node]] = []  # (name, definition node)
    calls: list[tuple[str, int]] = []  # (callee name, call node start_byte)

    for _pattern_idx, captures in matches:
        name_nodes = captures.get("name")
        if not name_nodes:
            continue
        name = text(name_nodes[0])

        if "definition.function" in captures:
            function_scopes.append((name, captures["definition.function"][0]))
        elif "definition.method" in captures:
            function_scopes.append((name, captures["definition.method"][0]))
        elif "definition.class" in captures:
            class_scopes.append((name, captures["definition.class"][0]))
        elif "definition.interface" in captures:
            class_scopes.append((name, captures["definition.interface"][0]))
        elif "reference.call" in captures:
            calls.append((name, captures["reference.call"][0].start_byte))

    def innermost_class(byte_pos: int) -> str | None:
        best, best_span = None, None
        for cname, cnode in class_scopes:
            if cnode.start_byte <= byte_pos < cnode.end_byte:
                span = cnode.end_byte - cnode.start_byte
                if best_span is None or span < best_span:
                    best, best_span = cname, span
        return best

    # A method's qualified name (e.g. "Greeter.greet") -- computed once per
    # function_scopes entry so both the function inventory and the
    # call-graph's caller attribution below use the identical identity.
    qualified_by_index = [
        (f"{enclosing}.{name}" if (enclosing := innermost_class(node.start_byte)) else name)
        for name, node in function_scopes
    ]

    def innermost_function_index(byte_pos: int) -> int | None:
        best_idx, best_span = None, None
        for i, (_name, node) in enumerate(function_scopes):
            if node.start_byte <= byte_pos < node.end_byte:
                span = node.end_byte - node.start_byte
                if best_span is None or span < best_span:
                    best_idx, best_span = i, span
        return best_idx

    functions = [
        FunctionDef(
            name=qualified_by_index[i],
            file=normalized_path,
            lineno=node.start_point[0] + 1,
            end_lineno=node.end_point[0] + 1,
            source=text(node),
        )
        for i, (_name, node) in enumerate(function_scopes)
    ]

    edges: list[CallEdge] = []
    for callee_name, call_start in calls:
        idx = innermost_function_index(call_start)
        if idx is not None:
            edges.append(CallEdge(caller=qualified_by_index[idx], callee=callee_name))

    return IndexResult(functions=_dedupe_names(functions), call_edges=edges)


def index_file(path: Path, repo_root: Path) -> IndexResult:
    """Parse one file into a function inventory and a direct-call graph.
    Dispatches by extension: Python goes through `ast` (see
    `_index_file_python`); every other supported language (Phase 1's
    agreed v1 set) goes through tree-sitter (see `_index_file_tree_sitter`).
    Raises ValueError for anything else, rather than silently skipping a
    file the caller expected to be indexed."""
    language = detect_language(path)
    if language is None:
        supported = sorted(set(LANGUAGE_BY_EXTENSION.values()))
        raise ValueError(f"Unsupported file extension '{path.suffix}' for {path} -- supported languages: {supported}")
    if language == "python":
        return _index_file_python(path, repo_root)
    return _index_file_tree_sitter(path, repo_root, language)
