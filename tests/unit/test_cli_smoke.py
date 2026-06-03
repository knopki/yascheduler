# FILE: tests/unit/test_cli_smoke.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CLI smoke tests — verify all 6 CLI commands are importable and structurally correct.
#   SCOPE: Import-level smoke tests: no real DB/SSH needed, just verify function existence
#          and decorator contracts (@to_sync for submit/check_status/init/show_nodes/manage_node,
#          internal make_daemon use for daemonize).
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_utils_import_does_not_import_scheduler - utils import must not pull in scheduler
#   TestCLIFunctions - Smoke test each of the 6 CLI entry points
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Import from adapters.cli instead of utils.
# END_CHANGE_SUMMARY

"""CLI smoke tests (task 7.6): verify all 6 CLI commands still functional.

Import-level smoke tests — verify that importing and inspecting each CLI function
doesn't crash (no real DB/SSH needed, just mock everything).
"""

import asyncio
import inspect
import sys


def test_utils_import_does_not_import_scheduler() -> None:
    """Importing yascheduler.adapters.cli must not trigger yascheduler.scheduler import."""
    saved = sys.modules.pop("yascheduler.scheduler", None)
    try:
        import yascheduler.adapters.cli  # noqa: F401

        assert "yascheduler.scheduler" not in sys.modules, (
            "Importing yascheduler.adapters.cli should not transitively import yascheduler.scheduler"
        )
    finally:
        if saved is not None:
            sys.modules["yascheduler.scheduler"] = saved


def _check_to_sync_decorated(func: object) -> None:
    """Assert that *func* is decorated with ``@to_sync``.

    The ``@to_sync`` decorator wraps an ``async`` function via ``functools.wraps``,
    which sets ``__wrapped__`` pointing to the original coroutine function.
    """
    assert callable(func), f"{func} is not callable"
    assert hasattr(func, "__wrapped__"), (
        f"{func.__name__} lacks __wrapped__ — not decorated with @to_sync"
    )
    assert asyncio.iscoroutinefunction(func.__wrapped__), (
        f"{func.__name__}.__wrapped__ is not a coroutine function"
    )


class TestCLIFunctions:
    """Smoke tests for CLI command functions — import and verify structure."""

    # --- @to_sync-decorated commands ---

    def test_submit_function_exists(self) -> None:
        """``submit`` exists and is decorated with @to_sync."""
        from yascheduler.adapters.cli import submit

        _check_to_sync_decorated(submit)

    def test_check_status_function_exists(self) -> None:
        """``check_status`` exists and is decorated with @to_sync."""
        from yascheduler.adapters.cli import check_status

        _check_to_sync_decorated(check_status)

    def test_init_function_exists(self) -> None:
        """``init`` exists and is decorated with @to_sync."""
        from yascheduler.adapters.cli import init

        _check_to_sync_decorated(init)

    def test_show_nodes_function_exists(self) -> None:
        """``show_nodes`` exists and is decorated with @to_sync."""
        from yascheduler.adapters.cli import show_nodes

        _check_to_sync_decorated(show_nodes)

    def test_manage_node_function_exists(self) -> None:
        """``manage_node`` exists and is decorated with @to_sync."""
        from yascheduler.adapters.cli import manage_node

        _check_to_sync_decorated(manage_node)

    # --- daemonize (NOT @to_sync; uses make_daemon internally) ---

    def test_daemonize_function_exists_and_uses_make_daemon(self) -> None:
        """``daemonize`` exists, is a plain (not @to_sync) function, and references make_daemon."""
        from yascheduler.adapters.cli import daemonize

        assert callable(daemonize)
        # daemonize is NOT decorated with @to_sync — it's a plain sync function
        assert not hasattr(daemonize, "__wrapped__")
        # Verify it internally references make_daemon (from DI)
        source = inspect.getsource(daemonize)
        assert "make_daemon" in source, (
            "daemonize must internally call make_daemon from DI"
        )
