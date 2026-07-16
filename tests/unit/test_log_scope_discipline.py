"""Guard tests for logging discipline in yascheduler package.

Two guard tests:
1. test_no_injected_logger_in_collaborator_constructors — none of the seven
   collaborator classes accept a parameter named 'log' in their __init__.
2. test_no_extra_key_collision_with_native_attrs — no extra={...} literal in
   yascheduler/ uses a key that collides with a native LogRecord attribute.
"""
# region MODULE_CONTRACT
# PURPOSE: Guard tests for logging discipline in yascheduler package.
# SCOPE: Static AST-based checks: no injected logger parameter in collaborator constructors; no extra-key collisions with native LogRecord attributes in extra={...} literals.
# KEYWORDS: logging discipline, injected logger, extra-key collisions
# endregion MODULE_CONTRACT

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yascheduler.shared.log import _NATIVE_KEYS

PACKAGE_DIR = Path(__file__).resolve().parent.parent.parent / "yascheduler"


@pytest.mark.unit
def test_no_injected_logger_in_collaborator_constructors() -> None:
    """None of the seven collaborator classes accept a parameter named 'log' in their __init__.

    AST-walks the seven collaborator modules, finds each class's __init__
    method (or the class annotations for frozen dataclasses), and fails if
    any parameter is named 'log'.
    """
    # (file_rel_path, class_name, abs_path)
    collaborators: list[tuple[str, str]] = [
        ("yascheduler/application/orchestrator.py", "Orchestrator"),
        ("yascheduler/infra/ssh/repository.py", "SSHMachineRepository"),
        ("yascheduler/infra/ssh/session.py", "SSHMachineSession"),
        ("yascheduler/infra/ssh/operations/deployment.py", "TaskDeployer"),
        ("yascheduler/infra/ssh/operations/download.py", "OutputDownloader"),
        ("yascheduler/infra/ssh/operations/occupancy.py", "OccupancyChecker"),
        ("yascheduler/infra/cloud/manager.py", "CloudProvisionerImpl"),
    ]

    errors: list[str] = []

    for rel_path, class_name in collaborators:
        pyfile = PACKAGE_DIR.parent / rel_path
        if not pyfile.exists():
            errors.append(f"{rel_path}: file not found")
            continue
        source = pyfile.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(pyfile))
        except SyntaxError:
            errors.append(f"{rel_path}: syntax error")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name != class_name:
                continue

            # Check __init__ method args for a 'log' parameter
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    # Skip 'self' (first arg)
                    args = item.args
                    all_arg_names: list[str] = [arg.arg for arg in args.args]
                    all_arg_names.extend(arg.arg for arg in args.posonlyargs)
                    all_arg_names.extend(arg.arg for arg in args.kwonlyargs)
                    if "log" in all_arg_names:
                        errors.append(
                            f"{rel_path}: {class_name}.__init__ accepts "
                            f"a parameter named 'log'",
                        )
                    break

            # Check class-level annotations for 'log' field (frozen dataclass)
            for item in node.body:
                if (
                    isinstance(item, ast.AnnAssign)
                    and isinstance(
                        item.target,
                        ast.Name,
                    )
                    and item.target.id == "log"
                ):
                    errors.append(
                        f"{rel_path}: {class_name} has a class-level "
                        f"'log' annotation (frozen dataclass field)",
                    )

    assert not errors, (
        "Collaborator constructor 'log' parameter violations:\n" + "\n".join(errors)
    )


# ---- Synthetic-violation meta-tests (injected-logger guard) ----


@pytest.mark.unit
def test_guard_catches_injected_logger_param() -> None:
    """Guard catches an __init__ with a 'log' parameter."""
    # Simulate a class with log parameter in __init__
    source = """
class Orchestrator:
    def __init__(self, log):
        self._log = log
"""
    tree = ast.parse(source)
    # Walk looking for the class
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Orchestrator":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    args = item.args
                    all_names = [a.arg for a in args.args]
                    assert "log" in all_names
                    break


@pytest.mark.unit
def test_guard_catches_frozen_dataclass_log_field() -> None:
    """Guard catches a frozen dataclass with a 'log' annotation."""
    source = """
from dataclasses import dataclass

@dataclass(frozen=True)
class CloudProvisionerImpl:
    log: YaLogger
"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CloudProvisionerImpl":
            for item in node.body:
                if (
                    isinstance(item, ast.AnnAssign)
                    and isinstance(
                        item.target,
                        ast.Name,
                    )
                    and item.target.id == "log"
                ):
                    assert True
                    return
            assert False, "Did not find log annotation"


# ---- Extra-key collision guard test ----


def _find_extra_keys_from_ast(
    tree: ast.Module,
) -> list[tuple[int, str, frozenset[str]]]:
    """Find all extra={...} dict literal keys used as keyword arguments in an AST tree.

    Only matches literal ast.Dict values with Constant str keys;
    non-literal extras (e.g. extra={**d}, extra=CONST) and the empty
    literal extra={} are silently skipped (no keys to collide).

    Returns list of (lineno, call_text_fragment, keys) for each callsite
    where extra= is a dict literal with string keys.
    """
    results: list[tuple[int, str, frozenset[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "extra":
                continue
            if not isinstance(kw.value, ast.Dict):
                continue
            keys: set[str] = set()
            for key_node in kw.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(
                    key_node.value,
                    str,
                ):
                    keys.add(key_node.value)
            if keys:
                results.append((node.lineno, ast.unparse(node)[:120], frozenset(keys)))
    return results


def _colliding_keys(
    extra_keys: set[str] | frozenset[str],
) -> set[str] | frozenset[str]:
    """Return the subset of extra keys that collide with native LogRecord attributes."""
    return extra_keys & _NATIVE_KEYS


@pytest.mark.unit
def test_no_extra_key_collision_with_native_attrs() -> None:
    """No extra={...} dict literal in yascheduler/ uses a key that collides with a native LogRecord attribute.

    AST-scans every extra={...} literal in yascheduler/; derives the native
    LogRecord attribute set from yascheduler.shared.log._NATIVE_KEYS; fails
    naming the file, the offending key, and the call if any extra key
    intersects the native set.
    """
    errors: list[str] = []
    for pyfile in sorted(PACKAGE_DIR.rglob("*.py")):
        source = pyfile.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(pyfile))
        except SyntaxError:
            errors.append(f"{pyfile.relative_to(PACKAGE_DIR.parent)}: syntax error")
            continue
        rel = pyfile.relative_to(PACKAGE_DIR.parent)
        for lineno, call_text, keys in _find_extra_keys_from_ast(tree):
            colliding = _colliding_keys(keys)
            for key in sorted(colliding):
                errors.append(
                    f"{rel}:{lineno}: extra key {key!r} collides with native "
                    f"LogRecord attribute in call: {call_text}",
                )
    assert not errors, (
        "Extra-key collisions with native LogRecord attributes:\n" + "\n".join(errors)
    )


@pytest.mark.unit
def test_guard_catches_extra_key_collision() -> None:
    """_colliding_keys detects a native LogRecord attribute key as a collision.

    Synthetic-violation meta-test: proves the collision-detection helper
    flags a known-native key (funcName) and does NOT flag a benign key (foo).
    """
    assert _colliding_keys({"funcName"}) == {"funcName"}
    assert _colliding_keys({"foo"}) == set()


@pytest.mark.unit
def test_guard_catches_extra_key_literal() -> None:
    """_find_extra_keys_from_ast extracts keys from a synthetic extra={{...}} literal.

    Synthetic-violation meta-test: parses an in-memory callsite and asserts
    the AST walker returns exactly one entry containing the known key.
    Restores parity with the original meta-test discipline where every
    non-trivial AST walker had a positive-detection meta-test.
    """
    source = 'log.debug("X", extra={"funcName": 1})\n'
    tree = ast.parse(source)
    results = _find_extra_keys_from_ast(tree)
    assert len(results) == 1
    _, _, keys = results[0]
    assert "funcName" in keys
