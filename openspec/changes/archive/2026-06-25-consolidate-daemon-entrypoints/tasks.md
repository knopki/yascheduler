## 1. New shared modules

- [x] 1.1 Create `yascheduler/entrypoints/cli/args.py` with `LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]`, `existing_path(s) -> Path` (argparse type: `Path.is_file()` else `argparse.ArgumentTypeError`), `add_config_arg(parser, *, default=CONFIG_FILE, dest="config")` (`--config PATH`, `type=existing_path`), `add_log_level_arg(parser, *, default="WARNING")` (`--log-level`, `choices=LOG_LEVEL_CHOICES`, resolved via `logging.getLevelName`), `add_log_file_arg(parser, *, default=None)` (`--log-file PATH`). Add full GRACE-lite MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY + per-function START_CONTRACT blocks.
- [x] 1.2 Create `yascheduler/entrypoints/cli/daemon_common.py` with `configure_logger(log_file, level) -> logging.Logger` (root `StreamHandler(sys.stderr)` always + `FileHandler(log_file)` when not None; `backoff`/`asyncssh` → `ERROR`; `logging.captureWarnings(True)`; NO `basicConfig`) and `async def run_daemon(config, logger) -> None` (await `make_daemon`, register SIGTERM/SIGINT handlers on running loop — cancel outstanding tasks, sleep 250ms, log "Done" — move verbatim from `daemonize.py:93-126`; await `orch.start()`). Add full GRACE-lite markup.
- [x] 1.3 Add unit tests `tests/unit/test_cli_args.py` covering: `existing_path` happy/missing path, `add_config_arg` default=CONFIG_FILE + missing-file exit 2, `add_log_level_arg` choices reject `WARN` + `getLevelName` resolves, `add_log_file_arg` default None + custom path.
- [x] 1.4 Add unit tests `tests/unit/test_daemon_common.py` covering: `configure_logger(None, INFO)` → root has StreamHandler only; `configure_logger(path, INFO)` → root has StreamHandler + FileHandler; `backoff`/`asyncssh` level ERROR; `captureWarnings(True)` called; `basicConfig` not called; `run_daemon` is `async def`; `run_daemon` awaits `make_daemon` + `orch.start()` with mocked DI (no real DB/SSH).

## 2. Re-implement daemon entry points

- [x] 2.1 Re-implement `yascheduler/entrypoints/cli/daemonize.py` as thin `def daemonize(argv: list[str] | None = None) -> None`: build parser (`prog="yascheduler"`) with `add_config_arg`, `add_log_level_arg(default="INFO")`, `add_log_file_arg(default=None)`; parse argv; `configure_logger(args.log_file, logging.getLevelName(args.log_level))`; `Config.from_config_parser(args.config)`; `asyncio.run(run_daemon(config, logger))`; wrap in try/except Exception → `Error: ...` stderr + `sys.exit(1)`. Add GRACE-lite markup.
- [x] 2.2 Re-implement `yascheduler/entrypoints/cli/daemon_systemd.py` as thin `def main(argv=None) -> None` with the same parser shape as `daemonize` (log-file default None); call under `if __name__ == "__main__":`. No `python-daemon`. Add GRACE-lite markup.
- [x] 2.3 Re-implement `yascheduler/entrypoints/cli/daemon_sysv.py` as `def main(argv=None) -> None`: parser with `add_config_arg`, `add_log_level_arg(default="INFO")`, `add_log_file_arg(default=LOG_FILE)` keeping `-l` short flag, `-p`/`--pid-file` (default `PID_FILE`); `--config`/`--log-level` long-only; build `daemon.DaemonContext(pidfile=pidfile.TimeoutPIDLockFile(args.pid_file), working_directory="/", umask=0o002)`; INSIDE the context call `configure_logger(args.log_file, level)` + `Config.from_config_parser(args.config)` + `asyncio.run(run_daemon(config, logger))`; try/except → exit 1. Preserve `from daemon import pidfile` and `import daemon` imports. Add GRACE-lite markup.
- [x] 2.4 Add unit tests `tests/unit/test_cli_daemonize.py` covering: `--help` exit 0 (prog=yascheduler), `--bogus` exit 2, `--config /nonexistent` exit 2 with `not a file` message, default `--log-file` is None, default `--log-level` is INFO, runtime error from `make_daemon` → exit 1 with `Error:` on stderr, `daemonize(argv=[...])` reads explicit argv not sys.argv.
- [x] 2.5 Add unit tests `tests/unit/test_cli_daemon_systemd.py` covering: `--help` exit 0, default `--log-file` None (journald), `--log-level` default INFO.
- [x] 2.6 Add unit tests `tests/unit/test_cli_daemon_sysv.py` covering: `--help` exit 0, `-p PID -l LOG` short flags parse correctly, `--log-level DEBUG -l LOG` no collision, default `--log-file` is LOG_FILE, default `--pid-file` is PID_FILE, `DaemonContext` built with `working_directory="/"` (mock `daemon` module), `configure_logger` called INSIDE the context (use a spy/mock to verify ordering).

## 3. Update five existing CLI commands

- [x] 3.1 Update `yascheduler/entrypoints/cli/submit.py`: replace `_existing_path` with `from yascheduler.entrypoints.cli.args import existing_path` (use `type=existing_path` in `_parse_submit_args`); add `add_config_arg(parser)` + `add_log_level_arg(parser, default="WARNING")` to the parser; replace `Config.from_config_parser(CONFIG_FILE)` with `Config.from_config_parser(args.config)`; replace `log.setLevel(logging.WARN)` with `log.setLevel(logging.getLevelName(args.log_level))`; convert `@to_sync async def submit` to `def submit(argv): asyncio.run(_submit_async(argv))` + `async def _submit_async(argv)`; update MODULE_MAP + CHANGE_SUMMARY.
- [x] 3.2 Update `yascheduler/entrypoints/cli/show_nodes.py`: add `add_config_arg(parser)` + `add_log_level_arg(parser, default="WARNING")` to `_parse_nodes_args`; replace `Config.from_config_parser(CONFIG_FILE)` with `Config.from_config_parser(args.config)`; add `logging.basicConfig`-free root logger setup at level `args.log_level` (StreamHandler→stderr); convert `@to_sync async def show_nodes` to `def show_nodes(argv): asyncio.run(_show_nodes_async(argv))` + `async def _show_nodes_async(argv)`; update CHANGE_SUMMARY.
- [x] 3.3 Update `yascheduler/entrypoints/cli/manage_node.py`: add `add_config_arg(parser)` + `add_log_level_arg(parser, default="WARNING")` to `_parse_node_args`; replace `Config.from_config_parser(CONFIG_FILE)` with `Config.from_config_parser(args.config)`; replace `log.setLevel(logging.WARN)` with `log.setLevel(logging.getLevelName(args.log_level))`; convert `@to_sync async def manage_node` to `def manage_node(argv): asyncio.run(_manage_node_async(argv))` + `async def _manage_node_async(argv)`; update CHANGE_SUMMARY.
- [x] 3.4 Update `yascheduler/entrypoints/cli/check_status.py`: add `add_config_arg(parser)` + `add_log_level_arg(parser, default="WARNING")` to `_parse_status_args`; replace `Config.from_config_parser(CONFIG_FILE)` with `Config.from_config_parser(args.config)`; add root logger setup at `args.log_level`; convert `@to_sync async def check_status` to `def check_status(argv): asyncio.run(_check_status_async(argv))` + `async def _check_status_async(argv)`; update CHANGE_SUMMARY.
- [x] 3.5 Update `yascheduler/entrypoints/cli/init.py`: add `add_config_arg(parser)` + `add_log_level_arg(parser, default="WARNING")` to the parser; replace `Config.from_config_parser(CONFIG_FILE)` in `init()` with `Config.from_config_parser(args.config)` and pass `args.config` to `_init_schema`; change `_init_schema()` to `_init_schema(config_path: str = CONFIG_FILE)` and inside it call `Config.from_config_parser(config_path)`; add root logger setup at `args.log_level`; update CHANGE_SUMMARY.
- [x] 3.6 Update `yascheduler/entrypoints/cli/__init__.py` facade doc: remove `infra/cli/` mention from PURPOSE; bump VERSION; add CHANGE_SUMMARY entry noting `daemonize` is now a sibling resident and `infra/cli/` is liquidated.

## 4. Update existing tests

- [x] 4.1 Update `tests/unit/test_cli_smoke.py`: restructure into 6 smoke tests (one per entry point: `daemonize`, `init`, `show_nodes`, `submit`, `manage_node`, `check_status`); each asserts `callable(f)`, `not hasattr(f, "__wrapped__")`, and that source references the expected factory (`make_daemon` for daemonize, `make_cli_deps` for the four CLI commands, `apply_schema`/`Config.from_config_parser` for init). Update MODULE_CONTRACT + CHANGE_SUMMARY.
- [x] 4.2 Update `tests/unit/test_cli_manage_node.py`: delete `test_manage_node_is_to_sync_decorated` (lines 703-704) — no longer `@to_sync`. Update CHANGE_SUMMARY.
- [x] 4.3 Extend `tests/unit/test_cli_submit.py` with: `--help` lists `--config` and `--log-level`; `--config /nonexistent` exits 2; `--log-level WARN` exits 2; `--log-level DEBUG` sets root logger to DEBUG; `--config /custom.conf` is passed to `Config.from_config_parser`; default `--config` is CONFIG_FILE; default `--log-level` is WARNING.
- [x] 4.4 Extend `tests/unit/test_cli_show_nodes.py` with the same `--config`/`--log-level` scenarios as 4.3 (defaults WARNING).
- [x] 4.5 Extend `tests/unit/test_cli_manage_node.py` with the same `--config`/`--log-level` scenarios as 4.3 (defaults WARNING).
- [x] 4.6 Extend `tests/unit/test_cli_check_status.py` with the same `--config`/`--log-level` scenarios as 4.3 (defaults WARNING).
- [x] 4.7 Extend `tests/unit/test_cli_init.py` with: `--help` lists `--config` and `--log-level`; `--config /nonexistent` exits 2; `--config /custom.conf` is passed through `_init_schema(config_path)` to `Config.from_config_parser` (verify via mock); default `--config` is CONFIG_FILE; default `--log-level` is WARNING. The existing `daemon_systemd.py` / `daemon_sysv.py` path assertions (lines 243, 259) remain unchanged.

## 5. Liquidate infra/cli/

- [x] 5.1 Delete `yascheduler/infra/cli/daemonize.py`.
- [x] 5.2 Delete `yascheduler/infra/cli/__init__.py`.
- [x] 5.3 Remove the now-empty `yascheduler/infra/cli/` directory.
- [x] 5.4 Grep for `yascheduler.infra.cli` and `from yascheduler.infra.cli` across the repo (excluding `openspec/changes/archive/`); fix any remaining references (expected: none beyond what tasks 1-4 already update).

## 6. Update pyproject + entrypoints facade

- [x] 6.1 Update `pyproject.toml` line 51: change `yascheduler = "yascheduler.infra.cli.daemonize:daemonize"` to `yascheduler = "yascheduler.entrypoints.cli.daemonize:daemonize"`.
- [x] 6.2 Update `yascheduler/entrypoints/__init__.py` CHANGE_SUMMARY: remove "only di.py and infra/cli/ remain deferred for follow-up"; note `daemonize` is now a resident of `entrypoints/cli/`; bump VERSION.

## 7. GRACE-lite knowledge graph

- [x] 7.1 Update `docs/knowledge-graph.xml` `M-CLI-COMMANDS`: change `fn-daemonize` PURPOSE to `Start yascheduler daemon (entrypoints/cli/daemonize.py)`; remove any `infra/cli/` mention from annotations.
- [x] 7.2 Add `M-ENTRYPOINTS-CLI-ARGS` element (TYPE=UTILITY, STATUS=implemented, path=`yascheduler/entrypoints/cli/args.py`, depends=none, annotations: `fn-existing_path`, `fn-add_config_arg`, `fn-add_log_level_arg`, `fn-add_log_file_arg`, `const-LOG_LEVEL_CHOICES`).
- [x] 7.3 Add `M-DAEMON-COMMON` element (TYPE=CORE_LOGIC, STATUS=implemented, path=`yascheduler/entrypoints/cli/daemon_common.py`, depends=`M-DI, M-CONFIG, M-APPLICATION-ORCHESTRATOR`, annotations: `fn-configure_logger`, `fn-run_daemon`).
- [x] 7.4 Update `M-DAEMON-SYSTEMD` and `M-DAEMON-SYSV` `<depends>` from `M-CLI-COMMANDS, M-SHARED` to `M-DAEMON-COMMON, M-ENTRYPOINTS-CLI-ARGS, M-SHARED`; update `M-DAEMON-SYSV` `fn-start_daemon` PURPOSE to reflect new thin wrapper (or replace with `fn-main` if renamed).
- [x] 7.5 Rewrite `DF-DAEMON-START` to `M-DAEMON-SYSTEMD / M-DAEMON-SYSV -> M-DAEMON-COMMON` (was `-> M-CLI-COMMANDS`).
- [x] 7.6 Add `CrossLink from="M-DAEMON-COMMON" to="M-DI" relation="uses make_daemon"`.
- [x] 7.7 Run `python3 scripts/grace_check.py` and fix any reported XML/source errors until exit 0.

## 8. Docs and spec validation

- [x] 8.1 Update `docs/ARCHITECTURE.md` §2.6 ("CLI Adapter `yascheduler/infra/cli/`"): remove the section or rewrite to point at `yascheduler/entrypoints/cli/` as the unified CLI subpackage.
- [x] 8.2 Run `openspec validate --all --json` and confirm the change passes (already passing per tasks 1-7, but re-validate after any spec edits).
- [x] 8.3 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` and fix any reported issues.
- [x] 8.4 Run `uv run pytest -m unit` and confirm all unit tests pass (including the new `test_cli_args.py`, `test_daemon_common.py`, `test_cli_daemonize.py`, `test_cli_daemon_systemd.py`, `test_cli_daemon_sysv.py`, and the extended existing CLI tests).
- [x] 8.5 Run `uv run pytest -m integration` and `uv run pytest -m e2e` if any test touches DB/SSH (the daemon relocation should not, but verify nothing regressed).