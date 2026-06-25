# FILE: tests/unit/test_cli_smoke.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: CLI smoke tests — verify 1 CLI command is importable and structurally correct.
#   SCOPE: Import-level smoke tests: no real DB/SSH needed, just verify function existence
#          and decorator contracts (internal make_daemon use for daemonize). init, show_nodes, submit,
#          manage_node, and check_status moved to entrypoints/cli/ and are covered by
#          tests/unit/test_cli_init.py, tests/unit/test_cli_show_nodes.py, tests/unit/test_cli_submit.py,
#          tests/unit/test_cli_manage_node.py, tests/unit/test_cli_check_status.py.
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCLIFunctions - Smoke test the daemonize CLI entry point (init/show_nodes/submit/manage_node/check_status covered separately)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Drop test_check_status_function_exists (check_status moved to entrypoints/cli/check_status.py in relocate-check-status-command; covered by tests/unit/test_cli_check_status.py).
#   PREVIOUS_CHANGE: v1.6.0 - Drop test_manage_node_function_exists (manage_node moved to entrypoints/cli/manage_node.py in relocate-manage-node-change; covered by tests/unit/test_cli_manage_node.py).
# END_CHANGE_SUMMARY

"""CLI smoke tests: verify 1 CLI command still functional.

Import-level smoke tests — verify that importing and inspecting the daemonize CLI
function doesn't crash (no real DB/SSH needed, just mock everything). init, show_nodes,
submit, manage_node, and check_status moved to entrypoints/cli/ and are covered by
dedicated test files.
"""

import inspect


def _check_sync_function(func: object) -> None:
    """Assert that *func* is a plain synchronous callable (not async, not @to_sync)."""
    assert callable(func), f"{func} is not callable"
    assert not hasattr(func, "__wrapped__"), (
        f"{getattr(func, '__name__', func)} must not be @to_sync decorated"
    )


class TestCLIFunctions:
    """Smoke tests for CLI command functions — import and verify structure."""

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
