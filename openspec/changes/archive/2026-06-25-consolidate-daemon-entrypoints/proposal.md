## Why

The daemon entry points are split across two packages (`infra/cli/daemonize.py` plus
`entrypoints/cli/daemon_systemd.py` / `daemon_sysv.py`), the launchers duplicate argparse and
logger setup, and the sysv path is silently broken (the `-l` short flag collides between the
two parsers, so `daemonize()` re-parses `sys.argv` and rejects the invocation). The five
non-daemon CLI commands hardcode `CONFIG_FILE` and `logging.WARN`, so operators cannot
override the config path or log level without editing code. This change finishes the
`infra/cli/` → `entrypoints/cli/` migration, unifies argument parsing and logging across
all six CLI commands and the three daemon launchers, and fixes the latent bugs.

## What Changes

- **Relocate `daemonize`** from `yascheduler/infra/cli/daemonize.py` to
  `yascheduler/entrypoints/cli/daemonize.py`, re-implemented as a thin entry point that
  builds its own argparse parser and delegates to the shared daemon core.
- **Liquidate `yascheduler/infra/cli/`**: delete `daemonize.py` and `__init__.py`; remove
  the now-empty directory.
- **Add `yascheduler/entrypoints/cli/args.py`** with shared argparse helpers:
  `existing_path(s) -> Path`, `add_config_arg(parser, *, default, dest)`,
  `add_log_level_arg(parser, *, default)`, `add_log_file_arg(parser, *, default)`.
  `--log-level` uses an explicit `choices` list (no `logging._levelToName` private API).
- **Add `yascheduler/entrypoints/cli/daemon_common.py`** with `configure_logger(log_file,
  level) -> Logger` (root `StreamHandler`→stderr always + `FileHandler` when log_file set;
  `backoff`/`asyncssh` suppressed to `ERROR`) and `async def run_daemon(config, logger)`
  (make_daemon + signal handlers + `orch.start()`).
- **Re-implement `daemon_systemd.py` and `daemon_sysv.py`** as thin entry points that build
  their own parsers via `args.py` and call `daemon_common`. `daemon_sysv.py` keeps the
  `python-daemon` `DaemonContext` (with `working_directory="/"` fix) and preserves the
  short flags `-p`/`--pid-file` and `-l`/`--log-file` for compatibility with the installed
  `yascheduler.sh` init script.
- **Add `--config` and `--log-level` to all six CLI commands** (`yainit`, `yanodes`,
  `yasubmit`, `yasetnode`, `yastatus`, `yascheduler`). `--config` uses `type=existing_path`
  so a missing config file exits 2 with a clear message instead of a cryptic parse error.
- **Replace `@to_sync` with `asyncio.run`** on the five existing CLI command entry points
  (`submit`, `show_nodes`, `manage_node`, `check_status`; `init` is already sync). The
  thread-offload branch of `to_sync` never fires for CLI entry points (no async caller),
  so `asyncio.run` is equivalent and explicit. `to_sync` stays in `shared/async_utils.py`
  for `client.py`'s legitimate cross-context use.
- **Update `pyproject.toml`** console_script `yascheduler` from
  `yascheduler.infra.cli.daemonize:daemonize` to
  `yascheduler.entrypoints.cli.daemonize:daemonize`.
- **Behavior changes**:
  - **BREAKING** (systemd): `daemon_systemd.py` `--log-file` default changes from `LOG_FILE`
    to `None` (stderr → journald), matching the systemd convention. Operators who relied on
    the file log must add `--log-file` to the unit override or configure `StandardError` in
    the unit file.
  - `daemon_sysv.py` `working_directory` changes from the package directory to `/` (the
    `python-daemon` default), so relative paths in the daemon resolve against `/` as
    intended.
  - `yascheduler.sh`'s `$yascheduler -l "$logfile"` invocation now works (the `-l` short
    flag no longer collides with `daemonize`'s `--log-level`), restoring the sysv path.
  - All daemon entry points now exit 1 with `Error: ...` on stderr on runtime failure
    (previously: bare traceback).

## Capabilities

### New Capabilities
- `cli-args`: Shared argparse helpers for CLI entry points — `existing_path` validator,
  `add_config_arg`, `add_log_level_arg`, `add_log_file_arg`.
- `daemon-common`: Shared daemon core — `configure_logger` and `run_daemon`, used by all
  three daemon entry points.

### Modified Capabilities
- `cli-commands`: All six CLI commands now live in `entrypoints/cli/` and accept `--config`
  and `--log-level`; daemon entry points share `daemon_common`; `@to_sync` replaced with
  `asyncio.run`; exit-code contract (0/1/2) enforced uniformly; `--log-file` default for
  systemd is `None` (journald).
- `package-facades`: `yascheduler/infra/cli/` is liquidated; the `infra/cli/__init__.py`
  relative-import scenario is removed; the daemon-launcher-not-re-exported rationale is
  updated.

## Impact

- **Code**:
  - New: `yascheduler/entrypoints/cli/args.py`, `yascheduler/entrypoints/cli/daemon_common.py`,
    re-implemented `yascheduler/entrypoints/cli/daemonize.py`.
  - Modified: `yascheduler/entrypoints/cli/daemon_systemd.py`,
    `yascheduler/entrypoints/cli/daemon_sysv.py`, `yascheduler/entrypoints/cli/init.py`,
    `yascheduler/entrypoints/cli/submit.py`, `yascheduler/entrypoints/cli/show_nodes.py`,
    `yascheduler/entrypoints/cli/manage_node.py`, `yascheduler/entrypoints/cli/check_status.py`,
    `yascheduler/entrypoints/cli/__init__.py` (facade doc), `pyproject.toml` (console_script).
  - Deleted: `yascheduler/infra/cli/daemonize.py`, `yascheduler/infra/cli/__init__.py`,
    `yascheduler/infra/cli/` directory.
- **Public API**: The `yascheduler` console_script target moves
  (`yascheduler.infra.cli.daemonize:daemonize` →
  `yascheduler.entrypoints.cli.daemonize:daemonize`). The deep import
  `from yascheduler.infra.cli import daemonize` is removed (only `daemon_systemd.py`,
  `daemon_sysv.py`, and `test_cli_smoke.py` used it; all updated in this change).
- **Dependencies**: No new dependencies. `python-daemon~=2.3` already declared.
- **Tests**: Update `tests/unit/test_cli_smoke.py` (six entry-point smoke tests, all assert
  `not __wrapped__`), `tests/unit/test_cli_manage_node.py` (drop `__wrapped__` assert). Add
  `tests/unit/test_cli_args.py` (argparse helpers), `tests/unit/test_daemon_common.py`
  (`configure_logger`, `run_daemon` with mocked `make_daemon`),
  `tests/unit/test_cli_daemonize.py` (parsing, exit codes, `--config` validation, `--help`).
  Extend the five existing CLI test files with `--config` and `--log-level` scenarios.
- **Knowledge graph**: Update `M-CLI-COMMANDS`, add `M-ENTRYPOINTS-CLI-ARGS` and
  `M-DAEMON-COMMON`, update `M-DAEMON-SYSTEMD` / `M-DAEMON-SYSV` depends, rewrite
  `DF-DAEMON-START`, add CrossLink `M-DAEMON-COMMON -> M-DI`.
- **Docs**: `docs/ARCHITECTURE.md` §2.6 ("CLI Adapter `yascheduler/infra/cli/`") is removed
  or rewritten to point at `entrypoints/cli/`.