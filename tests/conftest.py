# region MODULE_CONTRACT
# PURPOSE: Shared pytest fixtures and a collection-time Python 3.9 compatibility guard for the yascheduler test suite.
# SCOPE: anyio backend fixture; pytest_configure hook that scans yascheduler/ and tests/ for PEP 604 union annotations without `from __future__ import annotations`.
# KEYWORDS: pytest fixtures, anyio, Python 3.9, annotation guard
# endregion MODULE_CONTRACT

import os
from pathlib import Path

import pytest

from tests.py39_compat_guard import scan_paths


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("YASCHEDULER_SKIP_PY39_GUARD") == "1":
        return
    root = Path(__file__).resolve().parent.parent
    violations = scan_paths([root / "yascheduler", root / "tests"])
    if not violations:
        return
    lines = [
        "",
        "Python 3.9 compatibility guard failed.",
        "",
        "PEP 604 `X | Y` annotations found without `from __future__ import annotations`.",
        "CPython evaluates these at import time and crashes on 3.9 (the project minimum",
        "declared in pyproject.toml). Affected locations:",
        "",
    ]
    lines += [f"  {v.render()}" for v in violations]
    lines += [
        "",
        "Fix: add `from __future__ import annotations` to each listed module, after any",
        "module docstring and before other imports.",
        "",
    ]
    pytest.exit("\n".join(lines), returncode=1)
