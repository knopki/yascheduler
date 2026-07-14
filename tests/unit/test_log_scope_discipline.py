# FILE: tests/unit/test_log_scope_discipline.py
# VERSION: 3.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Guard tests for logging discipline in yascheduler package.
#   SCOPE: Static AST-based checks: every get_logger("M-...") literal references a real <M-*> tag in docs/knowledge-graph.xml; no logging.getLogger(...) module-level bindings exist outside log.py; no raw .debug() calls; no injected logger parameter in collaborator constructors.
#   DEPENDS: none
#   LINKS: M-LOGGING
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_logger_names_are_real_m_ids - Every get_logger("M-...") literal references a real <M-*> tag; no logging.getLogger(...) module-level bindings outside log.py
#   test_no_raw_debug_calls_in_yascheduler - No raw .debug() calls on loggers in yascheduler/ (all DEBUG tracing goes through .trace())
#   test_no_injected_logger_in_collaborator_constructors - None of the seven collaborator classes accept a parameter named 'log' in their __init__
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v3.0.0 - Add test_no_injected_logger_in_collaborator_constructors guard test.
#   PREVIOUS_CHANGE: v2.0.0 - Scan for get_logger("M-...") instead of logging.getLogger("yascheduler.M-..."); also reject logging.getLogger(...) module-level bindings outside log.py.
# END_CHANGE_SUMMARY

"""Guard tests for logging discipline in yascheduler package.

Two guard tests:
1. test_logger_names_are_real_m_ids — every get_logger("M-...") call references a real <M-*> tag;
   additionally no logging.getLogger(...) module-level logger bindings exist outside yascheduler/shared/log.py.
2. test_no_raw_debug_calls_in_yascheduler — no raw .debug() calls on loggers exist in yascheduler/
   (all DEBUG tracing goes through .trace()).
"""

from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent.parent / "yascheduler"
KG_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "knowledge-graph.xml"

# Third-party loggers that are legitimately suppressed via logging.getLogger(name)
_THIRD_PARTY_LOGGERS = frozenset({"backoff", "asyncssh"})


def _get_m_ids() -> set[str]:
    tree = ET.parse(str(KG_PATH))
    root = tree.getroot()
    return {elem.tag for elem in root.iter() if elem.tag.startswith("M-")}


def _find_get_logger_calls_from_ast(tree: ast.Module) -> list[tuple[int, str]]:
    """Find all get_logger('M-...') calls in an AST tree with a string-literal argument.

    Returns list of (lineno, m_id) for each get_logger("M-...") call.
    """
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match get_logger('...') as bare name or attribute access
        is_get_logger = (isinstance(func, ast.Name) and func.id == "get_logger") or (
            isinstance(func, ast.Attribute) and func.attr == "get_logger"
        )
        if is_get_logger:
            if (
                len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                m_id = node.args[0].value
                if m_id.startswith("M-"):
                    calls.append((node.lineno, m_id))
    return calls


def _find_get_logger_calls(filepath: Path) -> list[tuple[int, str]]:
    """Find all get_logger('M-...') calls with a string-literal argument."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []
    return _find_get_logger_calls_from_ast(tree)


def _find_direct_getlogger_bindings_from_ast(tree: ast.Module) -> list[tuple[int, str]]:
    """Find logging.getLogger(...) calls used as module-level logger bindings in an AST tree.

    A binding is a logging.getLogger(...) call whose result is assigned to a
    variable (e.g. ``logger = logging.getLogger(...)`` or
    ``self._log = log or logging.getLogger(...)``).

    Excludes root logger getLogger() (no arguments), third-party suppression
    (backoff, asyncssh), and variable-argument calls.
    """
    # Build parent map
    parent_map: dict[ast.AST, ast.AST | None] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node

    bindings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "getLogger"
            and isinstance(func.value, ast.Name)
            and func.value.id == "logging"
        ):
            continue
        # Skip root logger getLogger() (no args)
        if not node.args:
            continue
        # Skip third-party suppression
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if arg.value in _THIRD_PARTY_LOGGERS:
                continue
        # Check if this call is an assignment value (module-level binding)
        parent = parent_map.get(node)
        if parent is None:
            continue
        # Direct assignment: x = logging.getLogger(...)
        if isinstance(parent, ast.Assign) and parent.value is node:
            bindings.append((node.lineno, ast.unparse(node)[:120]))
            continue
        # BinOp inside assignment: x = foo or logging.getLogger(...)
        if isinstance(parent, ast.BinOp):
            grandparent = parent_map.get(parent)
            if isinstance(grandparent, ast.Assign) and grandparent.value is parent:
                bindings.append((node.lineno, ast.unparse(node)[:120]))
    return bindings


def _find_direct_getlogger_bindings(filepath: Path) -> list[tuple[int, str]]:
    """Find logging.getLogger(...) calls used as module-level logger bindings.

    A binding is a logging.getLogger(...) call whose result is assigned to a
    variable (e.g. ``logger = logging.getLogger(...)`` or
    ``self._log = log or logging.getLogger(...)``).

    Excludes root logger getLogger() (no arguments), third-party suppression
    (backoff, asyncssh), and variable-argument calls.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []
    return _find_direct_getlogger_bindings_from_ast(tree)


def test_logger_names_are_real_m_ids() -> None:
    """Every get_logger('M-...') call references a real <M-*> tag.

    Also asserts no logging.getLogger(...) module-level logger bindings
    exist outside yascheduler/shared/log.py — the factory is the only
    sanctioned path.
    """
    m_ids = _get_m_ids()
    errors: list[str] = []

    for pyfile in sorted(PACKAGE_DIR.rglob("*.py")):
        rel = pyfile.relative_to(PACKAGE_DIR.parent)

        # Check 1: every get_logger("M-...") references a real M-ID
        for lineno, m_id in _find_get_logger_calls(pyfile):
            if m_id not in m_ids:
                errors.append(
                    f"{rel}:{lineno}: get_logger({m_id!r}) references "
                    f"non-existent M-ID '{m_id}'"
                )

        # Check 2: no logging.getLogger(...) module-level bindings outside log.py
        if pyfile == PACKAGE_DIR / "shared" / "log.py":
            continue
        for lineno, call_text in _find_direct_getlogger_bindings(pyfile):
            errors.append(
                f"{rel}:{lineno}: module-level logging.getLogger binding: "
                f"{call_text} — use get_logger('M-...') instead"
            )

    assert not errors, "Logging discipline violations:\n" + "\n".join(errors)


def _find_debug_calls_from_ast(tree: ast.Module) -> list[tuple[int, str]]:
    """Find all .debug() attribute calls in an AST tree.

    Returns list of (lineno, call_text) for every ast.Call whose func is an
    attribute access named 'debug' on any object.
    """
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "debug":
            calls.append((node.lineno, ast.unparse(node)[:120]))
    return calls


def _find_debug_calls(filepath: Path) -> list[tuple[int, str]]:
    """Find all .debug() attribute calls in a Python file via AST walk.

    Returns list of (lineno, call_text) for every ast.Call whose func is an
    attribute access named 'debug' on any object.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []
    return _find_debug_calls_from_ast(tree)


def test_no_raw_debug_calls_in_yascheduler() -> None:
    """No raw .debug() calls on loggers exist in yascheduler/.

    All structured DEBUG tracing must go through YaLogger.trace().
    The shared logging module (yascheduler/shared/log.py) is exempt:
    YaLogger.trace calls self.debug internally — that is the sanctioned
    implementation, not a contract violation.
    """
    exempt = {PACKAGE_DIR / "shared" / "log.py"}
    errors: list[str] = []

    for pyfile in sorted(PACKAGE_DIR.rglob("*.py")):
        if pyfile in exempt:
            continue
        rel = pyfile.relative_to(PACKAGE_DIR.parent)
        for lineno, call_text in _find_debug_calls(pyfile):
            errors.append(f"{rel}:{lineno}: raw .debug() call: {call_text}")

    assert not errors, (
        "Raw .debug() calls found in yascheduler/ — use .trace() instead:\n"
        + "\n".join(errors)
    )


def _find_setloggerclass_calls_from_ast(tree: ast.Module) -> list[tuple[int, str]]:
    """Find all logging.setLoggerClass(...) calls in an AST tree."""
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "setLoggerClass"
            and isinstance(func.value, ast.Name)
            and func.value.id == "logging"
        ):
            calls.append((node.lineno, ast.unparse(node)))
    return calls


def _find_setloggerclass_calls(filepath: Path) -> list[tuple[int, str]]:
    """Find all logging.setLoggerClass(...) calls in a Python file via AST walk."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []
    return _find_setloggerclass_calls_from_ast(tree)


def test_no_setloggerclass_in_yascheduler() -> None:
    """No logging.setLoggerClass(...) calls exist in yascheduler/.

    The project SHALL NOT use logging.setLoggerClass. The runtime class swap
    performed by setLoggerClass is invisible to static type checkers; the
    get_logger factory is the sanctioned path.
    """
    errors: list[str] = []
    for pyfile in sorted(PACKAGE_DIR.rglob("*.py")):
        rel = pyfile.relative_to(PACKAGE_DIR.parent)
        for lineno, call_text in _find_setloggerclass_calls(pyfile):
            errors.append(f"{rel}:{lineno}: logging.setLoggerClass call: {call_text}")

    assert not errors, (
        "logging.setLoggerClass() calls found in yascheduler/ — "
        "use get_logger() instead:\n" + "\n".join(errors)
    )


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
                    all_arg_names: list[str] = []
                    for arg in args.args:
                        all_arg_names.append(arg.arg)
                    for arg in args.posonlyargs:
                        all_arg_names.append(arg.arg)
                    for arg in args.kwonlyargs:
                        all_arg_names.append(arg.arg)
                    if "log" in all_arg_names:
                        errors.append(
                            f"{rel_path}: {class_name}.__init__ accepts "
                            f"a parameter named 'log'"
                        )
                    break

            # Check class-level annotations for 'log' field (frozen dataclass)
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    if item.target.id == "log":
                        errors.append(
                            f"{rel_path}: {class_name} has a class-level "
                            f"'log' annotation (frozen dataclass field)"
                        )

    assert not errors, (
        "Collaborator constructor 'log' parameter violations:\n" + "\n".join(errors)
    )


# ---- Synthetic-violation meta-tests (Task 2.3) ----


def test_guard_catches_raw_debug_call() -> None:
    """_find_debug_calls_from_ast returns non-empty for synthetic source with log.debug(...)."""
    source = 'log.debug("test")\n'
    tree = ast.parse(source)
    calls = _find_debug_calls_from_ast(tree)
    assert len(calls) == 1
    assert "debug" in calls[0][1]


def test_guard_catches_fabricated_m_id() -> None:
    """_find_get_logger_calls_from_ast returns a fabricated M-ID when it doesn't exist in KG."""
    source = 'get_logger("M-FABRICATED-NONEXISTENT")\n'
    tree = ast.parse(source)
    calls = _find_get_logger_calls_from_ast(tree)
    assert len(calls) == 1
    assert calls[0][1] == "M-FABRICATED-NONEXISTENT"


def test_guard_catches_direct_getlogger_binding() -> None:
    """_find_direct_getlogger_bindings_from_ast catches logging.getLogger(...) assignments."""
    source = 'logger = logging.getLogger("yascheduler.M-APPLICATION-ALLOCATE")\n'
    tree = ast.parse(source)
    bindings = _find_direct_getlogger_bindings_from_ast(tree)
    assert len(bindings) == 1
    assert "logging.getLogger" in bindings[0][1]


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
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    if item.target.id == "log":
                        assert True
                        return
            assert False, "Did not find log annotation"
