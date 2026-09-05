# region MODULE_CONTRACT
# PURPOSE: Unit tests for the py3.9 PEP 604 compatibility checker (tests/py39_compat_guard.py).
# SCOPE: has_future_annotations, check_source (param/return/vararg/kwarg/AnnAssign scope rules, future-import suppression), scan_paths directory recursion.
# KEYWORDS: PEP 604, has_future_annotations, scan_paths, compat checker
# endregion MODULE_CONTRACT

import ast
from pathlib import Path

import pytest

from tests.py39_compat_guard import check_source, has_future_annotations, scan_paths

pytestmark = pytest.mark.unit


class TestFutureAnnotationsDetection:
    def test_detects_future_annotations(self) -> None:
        tree = ast.parse("from __future__ import annotations\n")
        assert has_future_annotations(tree) is True

    def test_absent_without_future_import(self) -> None:
        tree = ast.parse("x = 1\n")
        assert has_future_annotations(tree) is False

    def test_unrelated_future_does_not_count(self) -> None:
        tree = ast.parse("from __future__ import generator_stop\n")
        assert has_future_annotations(tree) is False


class TestParamAndReturnViolations:
    def test_param_union_flagged(self) -> None:
        v = check_source("def f(x: int | None = None) -> None: ...\n", "m.py")
        assert len(v) == 1
        assert v[0].context == "param 'x' of f()"
        assert v[0].lineno == 1

    def test_return_union_flagged(self) -> None:
        v = check_source("def f() -> int | None: ...\n", "m.py")
        assert len(v) == 1
        assert v[0].context == "return of f()"

    def test_nested_generic_alias_union_flagged(self) -> None:
        # The init.py regression: list[str] | None evaluated eagerly on 3.9.
        v = check_source("def f(argv: list[str] | None = None) -> None: ...\n", "m.py")
        assert len(v) == 1
        assert "param 'argv'" in v[0].context

    def test_vararg_and_kwarg_flagged(self) -> None:
        v = check_source(
            "def f(*args: int | None, **kw: str | None) -> None: ...\n",
            "m.py",
        )
        contexts = {x.context for x in v}
        assert "param *args of f()" in contexts
        assert "param **kw of f()" in contexts

    def test_future_import_suppresses_all(self) -> None:
        src = (
            "from __future__ import annotations\n"
            "\n"
            "def f(x: int | None = None) -> int | None: ...\n"
        )
        assert check_source(src, "m.py") == []

    def test_no_union_no_violation(self) -> None:
        assert check_source("def f(x: int = 0) -> int: ...\n", "m.py") == []


class TestAnnotatedAssignmentScope:
    def test_module_level_annassign_flagged(self) -> None:
        v = check_source("y: int | None = None\n", "m.py")
        assert len(v) == 1
        assert "annotated assignment" in v[0].context

    def test_class_level_annassign_flagged(self) -> None:
        v = check_source("class C:\n    attr: int | None = None\n", "m.py")
        assert len(v) == 1

    def test_function_local_annassign_not_flagged(self) -> None:
        # PEP 526: function-local annotations are never evaluated.
        src = "def f():\n    conn: int | None = None\n    return conn\n"
        assert check_source(src, "m.py") == []

    def test_nested_function_params_still_flagged(self) -> None:
        src = (
            "def outer():\n"
            "    def inner(x: int | None = None) -> None: ...\n"
            "    return inner\n"
        )
        v = check_source(src, "m.py")
        assert len(v) == 1
        assert v[0].context == "param 'x' of inner()"


class TestScanPaths:
    def test_recurses_and_reports_only_bad_files(self, tmp_path: Path) -> None:
        (tmp_path / "good.py").write_text("def f(x: int = 0) -> int: ...\n")
        (tmp_path / "bad.py").write_text("def f(x: int | None = None) -> None: ...\n")
        nested = tmp_path / "pkg"
        nested.mkdir()
        (nested / "suppressed.py").write_text(
            "from __future__ import annotations\n"
            "def f(x: int | None = None) -> None: ...\n",
        )

        v = scan_paths([tmp_path])

        assert len(v) == 1
        assert v[0].path.name == "bad.py"

    def test_single_file_target(self, tmp_path: Path) -> None:
        target = tmp_path / "t.py"
        target.write_text("def f() -> int | None: ...\n")
        v = scan_paths([target])
        assert len(v) == 1
        assert v[0].path == target
