# FILE: tests/conftest.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Shared pytest fixtures and a collection-time Python 3.9 compatibility guard for the yascheduler test suite.
#   SCOPE: anyio backend fixture; pytest_configure hook that scans yascheduler/ and tests/ for PEP 604 union annotations without `from __future__ import annotations`.
#   DEPENDS: none
#   LINKS: none
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   anyio_backend - returns "asyncio" for pytest-anyio compatibility
#   pytest_configure - scans yascheduler/ + tests/ for py3.9-incompatible PEP 604 annotations; pytest.exit(1) on any violation
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Added pytest_configure guard: fails collection (exit 1) if any module under yascheduler/ or tests/ uses PEP 604 `X | Y` annotations without `from __future__ import annotations` (import-time crash on Python 3.9). Bypass via YASCHEDULER_SKIP_PY39_GUARD=1.
#   PREVIOUS_CHANGE: v1.0.0 - Initial test infrastructure: shared fixtures.
# END_CHANGE_SUMMARY

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
