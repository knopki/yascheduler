## Context

The CLI entry points are mid-migration. Five of six commands already moved from
`yascheduler/infra/cli/` to `yascheduler/entrypoints/cli/` (see archive:
`relocate-submit-command`, `relocate-show-nodes-command`, `relocate-manage-node-command`,
`relocate-check-status-command`, `relocate-daemon-launchers-to-cli`). The sixth (`daemonize`)
and the two thin launchers (`daemon_systemd.py`, `daemon_sysv.py`) are the last residents of
`infra/cli/` plus the launchers already in `entrypoints/cli/` that still import back across
the layer boundary via `from yascheduler.infra.cli import daemonize`.

Today's daemon path has a latent bug: `daemon_sysv.py` parses `-l/--log-file` and then calls
`daemonize(log_file)`, which re-parses `sys.argv` under a different `-l/--log-level` meaning.
The installed `yascheduler.sh:47` always passes `-l "$logfile"`, so the sysv path is broken.
The five non-daemon CLI commands hardcode `CONFIG_FILE` and `logging.WARN`, blocking
operator overrides.

Constraints from `AGENTS.md`: public interface stability (console_scripts, `Yascheduler`
public API, INI config format, DB schema, AiiDA entrypoint); minimal changes; no new
dependencies without a change proposal (none added here); compatibility with pip and uv;
Python `>=3.9`; Conventional Commits; OpenSpec/GRACE-lite compliance.

## Goals / Non-Goals

**Goals:**
- Finish the `infra/cli/` → `entrypoints/cli/` migration: `daemonize` moves, `infra/cli/` is
  liquidated, no entry point imports across the layer boundary.
- Unify argparse for all six CLI commands and the three daemon launchers via a shared
  `args.py`: `--config` (default `CONFIG_FILE`, `type=existing_path` → exit 2 if missing),
  `--log-level` (explicit `choices`, no `logging._levelToName`), `--log-file` (daemons
  only, sysv keeps `-l` short flag).
- Unify daemon runtime via `daemon_common.py`: `configure_logger(log_file, level)` (root
  `StreamHandler`→stderr always + `FileHandler` when set; `backoff`/`asyncssh` suppressed)
  and `async def run_daemon(config, logger)` (make_daemon + SIGTERM/SIGINT handlers +
  `orch.start()`).
- Fix the ten identified bugs (A–J, see explore-brief).
- Replace `@to_sync` with `asyncio.run` on the five existing CLI entry points; `to_sync`
  stays in `shared/async_utils.py` for `client.py`.
- Uniform exit-code contract (0 success / 1 runtime error with `Error: ...` on stderr / 2
  argparse error including missing config file).
- Uniform `prog="yascheduler"` on the three daemon entry points.
- Update OpenSpec specs (`cli-commands`, `package-facades`) and the GRACE-lite knowledge
  graph in the same change.

**Non-Goals:**
- Config reload via SIGHUP (requires config re-read + in-flight migration — separate
  feature).
- `--foreground` debug flag for sysv (YAGNI; legacy path must keep working).
- Promoting `to_sync` removal to `client.py` (different cross-context contract; out of
  scope).
- AiiDA plugin entrypoint changes (not a CLI command).
- DB schema migration (handled by the parallel `schema-migrations` change).
- Refactoring the orchestrator signal-handling body itself (only its call site moves).

## Decisions

### D1. `args.py` exposes functions, not a base parser

Each entry point builds its own `argparse.ArgumentParser` (with its own `prog`,
command-specific positional/flags, mutually-exclusive groups) and calls into `args.py`
helpers to add the shared flags. Alternatives considered:

- **A1: a base `ArgumentParser` subclass with shared flags pre-registered.** Rejected: forces
  a common base onto heterogeneous parsers (e.g., `submit` has a positional `script`,
  `show_nodes` has a `--cloud`/`--no-cloud` mutex group, `manage_node` has a
  `--remove-soft`/`--remove-hard` mutex group). A base parser would either pre-install
  conflicting flags or push every command into the same shape.
- **A2: a single dispatcher `daemonize(argv, *, log_file_default=None)`.** Rejected (Q3):
  each launcher parses once and calls the shared core with ready values; no double-parse, no
  second calling form.

Function helpers (`add_config_arg`, `add_log_level_arg`, `add_log_file_arg`) compose
cleanly with each command's bespoke parser and let `--help` reflect each command's actual
surface.

### D2. `existing_path` lives in `args.py`, `submit.py` imports it

`submit.py:_existing_path` is the same validator (`Path.is_file()` else
`ArgumentTypeError`). Moving it to `args.py` as `existing_path` and having `submit.py`
import removes duplication (Q2). No behavior change: argparse still converts
`ArgumentTypeError` to exit 2.

### D3. `--log-level` uses an explicit `choices` list

```python
LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
```

Resolved via `logging.getLevelName(args.log_level)` (returns the int). This replaces the
`logging._levelToName.values()` / `logging._nameToLevel[...]` private API (bug E) and works
on Python 3.9+ (`logging.getLevelNamesMapping` is 3.11+ only).

`WARN` is not added as an alias (Q13): `nameToLevel` only knows `WARNING`, no script in the
repo passes `WARN`, and canonical names are cleaner. Existing `logging.WARN` constants in
`submit`/`manage_node` are replaced by `args.log_level` (default `"WARNING"`), which is the
same numeric level.

### D4. `daemon_common.run_daemon` is `async def`; entry points call `asyncio.run`

`run_daemon(config, logger)` is `async` (Q6) — it `await`s `make_daemon`, registers signal
handlers on the running loop, and `await`s `orch.start()`. Each entry point is a sync `def`
that calls `asyncio.run(run_daemon(config, logger))`. This matches the five CLI commands'
new shape (`def f(argv): asyncio.run(_f_async(argv))`) and keeps the async boundary
explicit. `to_sync` is not used (its thread-offload branch never fires for entry points).

### D5. `configure_logger` configures the ROOT logger, not just `yascheduler` + 2

The current `_get_logger` adds `FileHandler` only to the `yascheduler`, `backoff`, and
`asyncssh` loggers, so root warnings from `aiohttp`/`pg8000`/`asyncio` never reach the log
file (bug G). The new `configure_logger`:

- Adds a `StreamHandler(sys.stderr)` to the **root** logger (always).
- Adds a `FileHandler(log_file)` to the **root** logger (only when `log_file is not None`).
- Sets `backoff` and `asyncssh` loggers to `ERROR` (suppress retry/key-exchange noise) but
  lets them propagate to root handlers.
- Does NOT call `logging.basicConfig` (it would install an uncontrolled `StreamHandler`).

`logging.captureWarnings(True)` is called so `warnings.warn` reaches the root handlers.

### D6. systemd `--log-file` default is `None` (journald convention)

systemd captures stderr into journald (`journalctl -u yascheduler`). Writing to a flat file
duplicates journald, lacks rotation, and is non-idiomatic. `daemon_systemd.py` and the
`daemonize` console_script default `--log-file` to `None` → stderr. Operators who want the
file log add `--log-file` to the unit override. `daemon_sysv.py` keeps `LOG_FILE` as the
default (sysv has no journald). This is a **BREAKING** change for systemd users who relied on
the implicit file log; the proposal calls it out and the migration plan covers it.

### D7. `daemon_sysv.py` preserves `-p`/`-l` short flags

`yascheduler.sh:47` invokes `$yascheduler -p "$pidfile" -l "$logfile" "$OPTIONS"`. To keep
existing installed init scripts working without re-running `yainit`, `daemon_sysv.py`'s
argparse keeps `-p`/`--pid-file` (default `PID_FILE`) and `-l`/`--log-file` (default
`LOG_FILE`) short flags. `--config` and `--log-level` are long-only (no short collision with
`-l`, since `daemonize`'s `--log-level` is also long-only — the original bug A is fixed by not
re-parsing `sys.argv`).

### D8. `daemon_sysv.py` sets `working_directory="/"`

`python-daemon`'s `DaemonContext` defaults to `/`; the current code overrides it to
`os.path.dirname(__file__)` (the package dir in site-packages), making relative paths in the
daemon resolve against an unreadable CWD. Restoring `/` (bug D) matches `python-daemon`'s
default and the convention for system daemons.

### D9. `daemon_common.run_daemon` owns the signal handlers

The signal-handling body (cancel outstanding tasks, sleep 250ms for SSL close, log "Done")
moves verbatim from `daemonize.py:93-126` into `run_daemon`. The entry points do not
register signal handlers. This keeps the async signal registration next to the event loop
and the orchestrator (it needs `loop.add_signal_handler`, which requires a running loop).

### D10. `@to_sync` → `asyncio.run` on five CLI commands

Each of `submit`, `show_nodes`, `manage_node`, `check_status` is split into a sync public
entry point and a private `async def _<name>_async(argv)`:

```python
def submit(argv: list[str] | None = None) -> None:
    asyncio.run(_submit_async(argv))

async def _submit_async(argv: list[str] | None) -> None:
    # body of the former @to_sync async def submit
    ...
```

`init` is already sync (no async body). `test_cli_smoke.py` is restructured: one smoke test
per entry point, each asserting `callable(f)`, `not hasattr(f, "__wrapped__")`, and that the
source references the expected factory (`make_daemon` for `daemonize`, `make_cli_deps` for
the four CLI commands, `apply_schema`/`Config.from_config_parser` for `init`).
`test_cli_manage_node.py:703-704` (`assert hasattr(manage_node, "__wrapped__")`) is deleted.

### D11. `init.py:_init_schema` takes a `config_path` parameter

Currently `_init_schema()` reads `CONFIG_FILE` directly. To honor `--config`,
`_init_schema(config_path: str = CONFIG_FILE)` is introduced and `init()` passes
`args.config`. `_init_systemd`/`_init_sysv` are unchanged (they don't read config).

### D12. Exit-code and error-message discipline

Every entry point wraps its body in `try: ... except Exception as e: print(f"Error: {e}",
file=sys.stderr); sys.exit(1)`. `SystemExit` from argparse (`--help` exit 0, bad flag exit 2)
and from `existing_path` `ArgumentTypeError` (exit 2) propagate naturally — they are NOT
caught by the `except Exception` (a `SystemExit` is not an `Exception`). This matches the
pattern already used by `submit`, `show_nodes`, `manage_node`, `check_status`.

## Risks / Trade-offs

- **[BREAKING systemd `--log-file` default]** → Operators relying on the implicit file log
  lose it on upgrade. Mitigation: the change is called out as BREAKING in the proposal;
  `yainit`'s rendered systemd unit is unchanged (it never set `--log-file`), so the default
  path moves to journald which is the systemd-idiomatic destination. The migration plan
  documents the override.
- **[`asyncio.run` cannot be called from a running loop]** → If a future caller invokes an
  entry point from async code, `asyncio.run` raises `RuntimeError`. Mitigation: CLI entry
  points are console_scripts invoked from a fresh process; no async caller exists in the
  repo. `client.py` keeps `to_sync` for the cross-context case. If an async caller ever
  appears, it should call the private `_f_async` directly.
- **[sysv `working_directory="/"` may surprise callers who relied on the package-dir CWD]**
  → The previous behavior was a bug (the package dir is not a sensible CWD for a system
  daemon). Mitigation: none needed; the fix aligns with `python-daemon`'s default and
  standard daemon convention.
- **[`existing_path` exit 2 on missing config]** → Operators who previously got a cryptic
  `Config.from_config_parser` traceback now get exit 2. Mitigation: the message is clear
  (`not a file: <path>`) and the exit code matches the rest of the CLI surface.
- **[Test churn]** → `test_cli_smoke.py` restructured, `test_cli_manage_node.py` loses one
  assert, five CLI test files gain `--config`/`--log-level` scenarios. Mitigation: each
  addition is small (~15-25 lines) and follows the existing test patterns.
- **[Knowledge-graph drift]** → Adding two modules and rewriting `DF-DAEMON-START` could
  miss a CrossLink. Mitigation: the tasks list the specific graph edits; `grace_check.py`
  is run before completion.

## Migration Plan

1. **Before deploy**: run `yainit` (or `yainit --daemon` on systemd hosts) to refresh the
   service file. The rendered unit file's `ExecStart` already points at the daemon launcher
   path (unchanged by this change); no re-render is strictly required for the launcher path,
   but the `pyproject.toml` console_script target moves, so a `pip install -e .` (or
   `uv sync`) is required to update the `yascheduler` wrapper script.
2. **systemd hosts relying on the file log**: add an override
   (`systemctl edit yascheduler`) with `ExecStart=` (clear) and
   `ExecStart=/usr/bin/python3 .../daemon_systemd.py --log-file /var/log/yascheduler.log`, OR
   configure `StandardError=append:/var/log/yascheduler.log` in the unit. The default
   (journald) is recommended.
3. **sysv hosts**: no action; `-l "$logfile"` now works correctly (bug A fixed).
4. **Rollback**: revert the change; the `infra/cli/` directory and `daemonize.py` return.
   The `pyproject.toml` console_script target reverts. No DB schema or config-file change is
   involved, so rollback is a pure code revert + reinstall.

## Open Questions

None. All decisions (D1–D12) are settled; Q1–Q13 from the explore phase are closed.