# FILE: tests/unit/test_cli_smoke.py
# VERSION: 1.5.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CLI smoke tests — verify 4 CLI commands are importable and structurally correct.
#   SCOPE: Import-level smoke tests: no real DB/SSH needed, just verify function existence
#          and decorator contracts (@to_sync for check_status/manage_node,
#          internal make_daemon use for daemonize). init, show_nodes, and submit moved to
#          entrypoints/cli/ and are covered by tests/unit/test_cli_init.py,
#          tests/unit/test_cli_show_nodes.py, tests/unit/test_cli_submit.py.
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCLIFunctions - Smoke test each of the 4 CLI entry points (init/show_nodes/submit covered separately)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - Drop test_submit_function_exists (submit moved to entrypoints/cli/submit.py in relocate-submit-command; covered by tests/unit/test_cli_submit.py).
#   PREVIOUS_CHANGE: v1.4.0 - Drop test_init_function_exists (init moved to entrypoints/cli/init.py in relocate-init-command; covered by tests/unit/test_cli_init.py).
# END_CHANGE_SUMMARY

"""CLI smoke tests: verify 4 CLI commands still functional.

Import-level smoke tests — verify that importing and inspecting each CLI function
doesn't crash (no real DB/SSH needed, just mock everything). init, show_nodes, and
submit moved to entrypoints/cli/ and are covered by dedicated test files.
"""

import asyncio
import inspect


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


def _check_sync_function(func: object) -> None:
    """Assert that *func* is a plain synchronous callable (not async, not @to_sync)."""
    assert callable(func), f"{func} is not callable"
    assert not asyncio.iscoroutinefunction(func), (
        f"{func.__name__} must not be a coroutine function"
    )
    assert not hasattr(func, "__wrapped__"), (
        f"{func.__name__} must not be @to_sync decorated"
    )


class TestCLIFunctions:
    """Smoke tests for CLI command functions — import and verify structure."""

    # --- @to_sync-decorated commands ---

    def test_check_status_function_exists(self) -> None:
        """``check_status`` exists and is decorated with @to_sync."""
        from yascheduler.infra.cli import check_status

        _check_to_sync_decorated(check_status)

    def test_manage_node_function_exists(self) -> None:
        """``manage_node`` exists and is decorated with @to_sync."""
        from yascheduler.infra.cli import manage_node

        _check_to_sync_decorated(manage_node)

    # --- daemonize (NOT @to_sync; uses make_daemon internally) ---

    def test_daemonize_function_exists_and_uses_make_daemon(self) -> None:
        """``daemonize`` exists, is a plain (not @to_sync) function, and references make_daemon."""
        from yascheduler.infra.cli import daemonize

        assert callable(daemonize)
        # daemonize is NOT decorated with @to_sync — it's a plain sync function
        assert not hasattr(daemonize, "__wrapped__")
        # Verify it internally references make_daemon (from DI)
        source = inspect.getsource(daemonize)
        assert "make_daemon" in source, (
            "daemonize must internally call make_daemon from DI"
        )
