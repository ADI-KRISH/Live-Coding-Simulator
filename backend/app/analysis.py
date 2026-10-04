"""Cheap static checks that run on every code snapshot.

These let the engine react instantly (syntax errors, missing function, nested loops)
and decide whether a change is meaningful, without spending an LLM call.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, asdict


@dataclass
class CodeAnalysis:
    syntax_error: dict | None = None
    has_function: bool = False
    is_stub: bool = True
    max_loop_depth: int = 0
    function_lines: int = 0
    short_names: int = 0
    structure_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_LOOPS = (ast.For, ast.While, ast.AsyncFor, ast.comprehension)


def _loop_depth(node: ast.AST, depth: int = 0) -> int:
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and node is not child:
            # nested helper functions count from zero; calls are not inlined
            best = max(best, _loop_depth(child, 0))
            continue
        inc = 1 if isinstance(child, _LOOPS) else 0
        best = max(best, _loop_depth(child, depth + inc))
    return best


def _is_stub(fn: ast.FunctionDef) -> bool:
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
    return all(isinstance(n, ast.Pass) for n in body) or not body


def analyze(code: str, function_name: str) -> CodeAnalysis:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return CodeAnalysis(
            syntax_error={"type": "SyntaxError", "message": e.msg, "line": e.lineno},
            structure_hash="syntax:" + hashlib.sha1(code.encode()).hexdigest()[:12],
        )

    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            target = node
            break

    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    short = sum(1 for n in names if len(n) == 1 and n not in {"i", "j", "k", "n", "x", "_"})

    return CodeAnalysis(
        syntax_error=None,
        has_function=target is not None,
        is_stub=_is_stub(target) if target is not None else True,
        max_loop_depth=_loop_depth(target) if target is not None else 0,
        function_lines=(target.end_lineno - target.lineno + 1) if target is not None else 0,
        short_names=short,
        structure_hash=hashlib.sha1(ast.dump(tree, annotate_fields=False).encode()).hexdigest()[:12],
    )
