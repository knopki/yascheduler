# FILE: tests/py39_compat_guard.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: AST checker flagging PEP 604 `X | Y` annotations that crash Python 3.9 at import time unless the module has `from __future__ import annotations`.
#   SCOPE: Pure functions scanning source for runtime-evaluated union annotations — function params/returns and module/class-level annotated assignments. Function-local annotated assignments are ignored (not evaluated per PEP 526).
#   DEPENDS: none (stdlib ast only)
#   LINKS: none (test infrastructure; stays out of knowledge graph per GRACE-lite)
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Violation - dataclass: path, lineno, col, context
#   has_future_annotations - True iff module body imports `from __future__ import annotations`
#   check_source - parse a source string, return Violations (empty when future-import present)
#   check_file - read+check a single .py Path
#   scan_paths - recurse files/dirs, return aggregated Violations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial py3.9 compat guard: detects runtime-evaluated PEP 604 annotations missing `from __future__ import annotations`.
# END_CHANGE_SUMMARY

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    col: int
    context: str

    def render(self) -> str:
        return f"{self.path}:{self.lineno}:{self.col}  {self.context}"


def has_future_annotations(tree: ast.Module) -> bool:
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
        ):
            return True
    return False


class _AnnUnionFinder(ast.NodeVisitor):
    """Collects runtime-evaluated annotations containing PEP 604 BinOp(BitOr)."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, int, str]] = []
        self._func_depth = 0

    def _check(self, ann: ast.expr | None, context: str) -> None:
        if ann is None:
            return
        for node in ast.walk(ann):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                ln = getattr(ann, "lineno", 1)
                col = getattr(ann, "col_offset", 0)
                self.violations.append((ln, col, context))
                return

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self._check(arg.annotation, f"param {arg.arg!r} of {node.name}()")
        if args.vararg is not None:
            self._check(
                args.vararg.annotation,
                f"param *{args.vararg.arg} of {node.name}()",
            )
        if args.kwarg is not None:
            self._check(
                args.kwarg.annotation,
                f"param **{args.kwarg.arg} of {node.name}()",
            )
        self._check(node.returns, f"return of {node.name}()")
        self._func_depth += 1
        self.generic_visit(node)
        self._func_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Function-local annotated assignments are NOT evaluated at runtime (PEP 526).
        if self._func_depth == 0 and node.annotation is not None:
            self._check(node.annotation, "module/class-level annotated assignment")
        self.generic_visit(node)


def check_source(source: str, filename: str = "<unknown>") -> list[Violation]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []
    if has_future_annotations(tree):
        return []
    finder = _AnnUnionFinder()
    finder.visit(tree)
    return [
        Violation(Path(filename), ln, col, ctx) for (ln, col, ctx) in finder.violations
    ]


def check_file(path: Path) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return check_source(source, filename=str(path))


def scan_paths(paths: list[Path]) -> list[Violation]:
    out: list[Violation] = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            out.extend(check_file(p))
        elif p.is_dir():
            for f in sorted(p.rglob("*.py")):
                out.extend(check_file(f))
    return out
