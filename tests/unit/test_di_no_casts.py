# region MODULE_CONTRACT
# PURPOSE: Regression test guarding against silent reintroduction of typing.cast in the composition root.
# SCOPE: AST-walks yascheduler/entrypoints/di.py for typing.cast imports/calls.
# KEYWORDS: typing.cast, composition root, AST walk
# endregion MODULE_CONTRACT

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
