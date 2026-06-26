# FILE: tests/unit/test_di_no_casts.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Regression test guarding against silent reintroduction of typing.cast in the composition root.
#   SCOPE: AST-walks yascheduler/entrypoints/di.py for typing.cast imports/calls.
#   DEPENDS: M-DI
#   LINKS: M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_di_has_no_cast_usage - Parse di.py and assert no typing.cast usage (import, bare call, or attribute call)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Add AST-based regression test asserting no typing.cast usage in the composition root (narrow-config-clouds-type). Config.clouds is typed Sequence[ConfigCloud], so the 2 former Protocol→Union downcasts are unnecessary; this test fails the unit suite if a future change reintroduces them.
# END_CHANGE_SUMMARY

import ast
import pathlib

DI_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "yascheduler"
    / "entrypoints"
    / "di.py"
)


def test_di_has_no_cast_usage() -> None:
    """The composition root must not use typing.cast.

    Config.clouds is typed Sequence[ConfigCloud], so iterating config.clouds
    yields ConfigCloud directly and feeds the infra sinks without a cast. See
    openspec/changes/narrow-config-clouds-type for rationale.

    The AST walk inspects only code — comments and string literals are not
    visited, so historical ``cast(...)`` tokens preserved verbatim in
    ``CHANGE_SUMMARY`` ``PREVIOUS_CHANGE`` lines do not trip the invariant.
    """
    tree = ast.parse(DI_PATH.read_text(), filename=str(DI_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            for alias in node.names:
                if alias.name == "cast":
                    raise AssertionError(f"typing.cast imported at line {node.lineno}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "cast"
        ):
            raise AssertionError(f"cast(...) called at line {node.lineno}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "cast"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "typing"
        ):
            raise AssertionError(f"typing.cast(...) called at line {node.lineno}")
