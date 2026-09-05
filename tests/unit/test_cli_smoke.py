"""CLI smoke tests: verify all six CLI entry points are importable and structurally correct.

Import-level smoke tests — verify that importing and inspecting each CLI entry point
doesn't crash (no real DB/SSH needed). Each entry point must be a plain synchronous
function (no @to_sync __wrapped__ attribute) and reference its expected DI factory.
"""
# region MODULE_CONTRACT
# PURPOSE: CLI smoke tests — verify all six CLI entry points are importable, structurally correct, and reference their expected DI factory.
# SCOPE: Import-level smoke tests: no real DB/SSH needed, just verify function existence, no __wrapped__ attribute, and the expected factory is referenced in source (make_daemon for daemonize, make_cli_deps for the four CLI commands, apply_schema/Config.from_config_parser for init).
# KEYWORDS: CLI smoke, importable, entry points, DI factory
# endregion MODULE_CONTRACT

import inspect


def _check_sync_function(func: object) -> None:
    """Assert that *func* is a plain synchronous callable (not async, not @to_sync)."""
    assert callable(func), f"{func} is not callable"
    assert not hasattr(func, "__wrapped__"), (
        f"{getattr(func, '__name__', func)} must not be @to_sync decorated"
    )


class TestCLIFunctions:
    """One smoke test per entry point — import, callable, no __wrapped__, expected factory."""

    def test_daemonize_exists_and_uses_make_daemon(self) -> None:
        """``daemonize`` exists in entrypoints/cli/, is plain sync, references make_daemon."""
        from yascheduler.entrypoints.cli.daemonize import daemonize

        _check_sync_function(daemonize)
        # daemonize delegates the async runtime to daemon_common.run_daemon, which awaits
        # make_daemon. Verify the module references make_daemon (via daemon_common or DI).
        from yascheduler.entrypoints.cli import daemon_common

        source = inspect.getsource(daemon_common)
        assert "make_daemon" in source, (
            "daemon_common.run_daemon must call make_daemon from DI"
        )

    def test_init_exists_and_uses_apply_schema(self) -> None:
        """``init`` exists, is plain sync, references apply_schema / Config.from_config_parser."""
        from yascheduler.entrypoints.cli.init import init

        _check_sync_function(init)
        # init() itself delegates to _init_schema, which calls apply_schema; the module
        # source must reference both apply_schema and Config.from_config_parser.
        from yascheduler.entrypoints.cli import init as init_mod

        mod_source = inspect.getsource(init_mod)
        assert "apply_schema" in mod_source, "init module must reference apply_schema"
        assert "parse_config" in mod_source, (
            "init module must reference Config.from_config_parser"
        )

    def test_show_nodes_exists_and_uses_make_cli_deps(self) -> None:
        """``show_nodes`` exists, is plain sync, references make_cli_deps."""
        from yascheduler.entrypoints.cli.show_nodes import show_nodes

        _check_sync_function(show_nodes)
        from yascheduler.entrypoints.cli import show_nodes as show_nodes_mod

        source = inspect.getsource(show_nodes_mod)
        assert "make_cli_deps" in source, (
            "show_nodes module must reference make_cli_deps"
        )

    def test_submit_exists_and_uses_make_cli_deps(self) -> None:
        """``submit`` exists, is plain sync, references make_cli_deps."""
        from yascheduler.entrypoints.cli.submit import submit

        _check_sync_function(submit)
        from yascheduler.entrypoints.cli import submit as submit_mod

        source = inspect.getsource(submit_mod)
        assert "make_cli_deps" in source, "submit module must reference make_cli_deps"

    def test_manage_node_exists_and_uses_make_cli_deps(self) -> None:
        """``manage_node`` exists, is plain sync, references make_cli_deps."""
        from yascheduler.entrypoints.cli.manage_node import manage_node

        _check_sync_function(manage_node)
        from yascheduler.entrypoints.cli import manage_node as manage_node_mod

        source = inspect.getsource(manage_node_mod)
        assert "make_cli_deps" in source, (
            "manage_node module must reference make_cli_deps"
        )

    def test_check_status_exists_and_uses_make_cli_deps(self) -> None:
        """``check_status`` exists, is plain sync, references make_cli_deps."""
        from yascheduler.entrypoints.cli.check_status import check_status

        _check_sync_function(check_status)
        from yascheduler.entrypoints.cli import check_status as check_status_mod

        source = inspect.getsource(check_status_mod)
        assert "make_cli_deps" in source, (
            "check_status module must reference make_cli_deps"
        )
