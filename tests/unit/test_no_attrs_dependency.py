"""Canary: no yascheduler module imports attrs or attr."""
# region MODULE_CONTRACT
# PURPOSE: AST-based canary guarding that no module under yascheduler/ imports attrs or attr.
# SCOPE: Walk every .py file in the yascheduler package, parse with ast, flag any ImportFrom/Import node whose module's first dotted segment is exactly "attrs" or "attr".
# KEYWORDS: attrs, attr, AST canary, import guard
# endregion MODULE_CONTRACT

from __future__ import annotations

import ast
import importlib
from pathlib import Path

_ATTRS_MODULES = frozenset({"attrs", "attr"})


def _package_root() -> Path:
    """Resolve the ``yascheduler/`` source directory from the installed package."""
    spec = importlib.util.find_spec("yascheduler")
    assert spec is not None, "yascheduler package not found"
    # SubmoduleSearchLocations is set for regular packages and points at the
    # package directory on disk; prefer it, fall back to the origin file's dir.
    locations = spec.submodule_search_locations
    if locations:
        return Path(next(iter(locations)))
    assert spec.origin is not None, "yascheduler has no origin"
    return Path(spec.origin).resolve().parent


def _iter_python_files(root: Path) -> list[Path]:
    """Yield every ``.py`` file under ``root`` recursively, sorted for stable output."""
    return sorted(root.rglob("*.py"))


def _import_first_segment(
    node: ast.ImportFrom | ast.Import,
    alias: ast.alias,
) -> str | None:
    """Return the first dotted segment of an import's module name.

    Returns None for relative imports (``node.level > 0``), which cannot
    reference the external ``attrs``/``attr`` packages.
    """
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return None
        module = node.module
        if module is None:
            return None
        return module.split(".", 1)[0]
    # ast.Import: the alias name is the dotted module path.
    return alias.name.split(".", 1)[0]


def _attrs_violations(path: Path, source: bytes) -> list[tuple[Path, int, str]]:
    """Collect every attrs/attr import node in ``source`` as (path, lineno, module_name)."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise AssertionError(
            f"{path}: cannot parse (SyntaxError: {exc.msg} at line {exc.lineno}). "
            "Fix the syntax error so the attrs-import canary can inspect this file.",
        ) from exc
    found: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        aliases: list[ast.alias] = []
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            aliases = node.names
        else:
            continue
        for alias in aliases:
            first = _import_first_segment(node, alias)
            if first is not None and first in _ATTRS_MODULES:
                full = node.module if isinstance(node, ast.ImportFrom) else alias.name
                found.append((path, node.lineno, full or first))
    return found


def test_no_attrs_imports_in_yascheduler() -> None:
    """No yascheduler module imports attrs or attr in any form.

    The canary parses every ``.py`` file under ``yascheduler/`` with ``ast`` and
    flags any ``ImportFrom``/``Import`` node whose module's first dotted segment
    is exactly ``attrs`` or ``attr``. This covers ``from attrs import ...``,
    ``from attr import ...``, ``import attrs``, ``import attr``, and dotted
    forms like ``import attrs.something``. It deliberately flags imports
    regardless of ``TYPE_CHECKING`` guard context: ``attrs`` is a runtime
    third-party package, not a typing shim, and must not appear in any
    yascheduler module's import graph in any form. ``tests/`` is excluded; the
    canary guards production code only. The prefix match is on the exact module
    names ``attrs`` and ``attr`` — ``from attrs_foo import x`` does not match.
    Dynamic imports (``__import__``, ``importlib.import_module``, ``exec``/``eval``
    of an import string) are out of scope: the canary inspects static
    ``ImportFrom``/``Import`` AST nodes only, as required by the no-attrs-dependency
    spec.
    """
    root = _package_root()
    violations: list[tuple[Path, int, str]] = []
    for path in _iter_python_files(root):
        source = path.read_bytes()
        violations.extend(_attrs_violations(path, source))

    if violations:
        formatted = "\n".join(
            f"  {p}:{lineno}: imports {name!r}" for p, lineno, name in violations
        )
        raise AssertionError(
            "yascheduler modules must not import 'attrs' or 'attr'.\n"
            "Offending imports:\n" + formatted,
        )
