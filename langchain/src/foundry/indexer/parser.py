"""Deterministic Python indexer: AST-based function inventory and call graph.

spec.md FR-020: the function inventory MUST be produced by a deterministic
parser (tree-sitter, ctags, language-server, "or equivalent"); an LLM MAY
augment it but MUST NOT be the sole source. Python's own `ast` module is
that "or equivalent" for a single-language Python target -- no model call
happens anywhere in this file. FR-021: call graph covering at minimum
direct static calls.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


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


def index_file(path: Path, repo_root: Path) -> IndexResult:
    """Parse one Python file into a function inventory and a direct-call graph."""
    source_text = path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(path))
    normalized_path = str(path.resolve().relative_to(repo_root.resolve()))
    source_lines = source_text.splitlines()

    function_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_nodes[node.name] = node

    functions: list[FunctionDef] = []
    edges: list[CallEdge] = []

    for name, node in function_nodes.items():
        end = getattr(node, "end_lineno", node.lineno)
        body_source = "\n".join(source_lines[node.lineno - 1 : end])
        functions.append(
            FunctionDef(
                name=name, file=normalized_path, lineno=node.lineno, end_lineno=end, source=body_source
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

    return IndexResult(functions=functions, call_edges=edges)
