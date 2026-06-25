# Explore Brief — consolidate-daemon-entrypoints

## Alternatives considered and rejected

### A1. Keep `daemonize` in `infra/cli/`, only relocate the two launchers
Rejected. Leaves the last resident of the abandoned `infra/cli/` package, perpetuates the
split (1 command in `infra/cli/`, 5 in `entrypoints/cli/`), and keeps the public import path
`yascheduler.infra.cli.daemonize` that `package-facades` already flags as a deferred
follow-up. The whole point of this change is to finish the migration.

### A2. Centralize all three entrypoints behind a single `daemonize()` dispatcher with kwargs
Rejected (Q3). Each launcher builds its own argparse parser and calls the shared daemon
core with ready arguments. A single dispatcher with `log_file_default=...` kwarg introduces a
second calling form and obscures the per-launcher argparse surface in `--help`.

### A3. Keep `@to_sync` on the five existing CLI commands, only use `asyncio.run` in the new daemon code
Rejected (Q10). Leaves two styles (`@to_sync` on 5 old, `asyncio.run` on 3 new) in the same
subpackage. The user explicitly asked to consolidate. `to_sync` is overkill for CLI
entrypoints: the thread-offload branch never fires (no async test or caller invokes the
entrypoints), so `to_sync` is exactly `asyncio.run` plus dead weight. `to_sync` stays in
`shared/async_utils.py` for `client.py` (legitimate cross-context caller).

### A4. Add `WARN` as a `--log-level` choice alias for backward compatibility
Rejected (Q13). `WARN` is an internal alias for `WARNING`; `logging.nameToLevel` only knows
`WARNING`. No script in the repo passes `WARN`. Canonical `WARNING` is cleaner.

### A5. Add `--foreground` flag to sysv launcher for container/debug use
Rejected (Q7, YAGNI). Legacy sysv path must keep working; adding options risks it.

### A6. Add SIGHUP reload handler
Rejected (Q8). Config reload + in-flight migration is a separate, complex feature.

## Final approach — labels, dimensions, mapping tables

### Module relocation map

| Symbol / file              | From                                  | To                                       | Status after        |
| -------------------------- | ------------------------------------- | ---------------------------------------- | ------------------- |
| `daemonize` function       | `yascheduler/infra/cli/daemonize.py`    | `yascheduler/entrypoints/cli/daemonize.py` | re-implemented thin |
| `infra/cli/__init__.py`    | exists                                | deleted                                 | gone                |
| `infra/cli/` (directory)   | exists                                | deleted (liquidated)                    | gone                |
| `daemon_systemd.py`        | `entrypoints/cli/daemon_systemd.py`    | same path, re-implemented thin           | updated             |
| `daemon_sysv.py`           | `entrypoints/cli/daemon_sysv.py`       | same path, re-implemented thin           | updated             |
| `args.py`                  | —                                     | `entrypoints/cli/args.py` (NEW)         | new                 |
| `daemon_common.py`         | —                                     | `entrypoints/cli/daemon_common.py` (NEW) | new                 |
| `pyproject.toml` scripts   | `yascheduler.infra.cli.daemonize:daemonize` | `yascheduler.entrypoints.cli.daemonize:daemonize` | updated  |

### New shared helpers in `args.py`

| Helper                          | Purpose                                                       | Used by                                |
| ------------------------------- | ------------------------------------------------------------- | -------------------------------------- |
| `existing_path(s) -> Path`      | argparse type: existing file or `ArgumentTypeError` (exit 2) | `add_config_arg`, re-used by `submit.py` |
| `add_config_arg(parser, *, default=CONFIG_FILE, dest="config")` | `--config PATH` with `type=existing_path`        | all 6 entrypoints                      |
| `add_log_level_arg(parser, *, default="WARNING")` | `--log-level` with explicit `choices=["DEBUG","INFO","WARNING","ERROR","CRITICAL"]` (no `logging._levelToName`) | all 6 entrypoints |
| `add_log_file_arg(parser, *, default)` | `--log-file PATH` (path string, no existence check; FileHandler will fail loudly if unwritable) | 3 daemon entrypoints |

### Daemon defaults table

| Entrypoint                          | `--config` default | `--log-level` default | `--log-file` default | Extra flags                 |
| ----------------------------------- | ------------------ | --------------------- | -------------------- | --------------------------- |
| `daemonize` (`yascheduler` console_script) | `CONFIG_FILE`        | `INFO`                | `None` → stderr      | —                           |
| `daemon_systemd.py`                   | `CONFIG_FILE`        | `INFO`                | `None` → stderr      | —                           |
| `daemon_sysv.py`                     | `CONFIG_FILE`        | `INFO`                | `LOG_FILE`           | `-p`/`--pid-file` (default `PID_FILE`) |

### CLI command defaults table (5 existing + `--config`/`--log-level`)

| Command       | `--config` default | `--log-level` default | `--log-file` | Notes                                  |
| ------------- | ------------------ | --------------------- | ------------ | -------------------------------------- |
| `yainit`        | `CONFIG_FILE`        | `WARNING`             | —            | `_init_schema(config_path)` gets param |
| `yanodes`       | `CONFIG_FILE`        | `WARNING`             | —            | first time root logger configured      |
| `yasubmit`      | `CONFIG_FILE`        | `WARNING`             | —            | replaces hardcoded `logging.WARN`      |
| `yasetnode`     | `CONFIG_FILE`        | `WARNING`             | —            | replaces hardcoded `logging.WARN`      |
| `yastatus`      | `CONFIG_FILE`        | `WARNING`             | —            | first time root logger configured      |

### Exit code contract (uniform across all 6 + 3 daemons)

| Situation                       | Exit |
| ------------------------------- | ---- |
| `--help`                        | 0    |
| Success                         | 0    |
| Runtime error (caught `Exception`) | 1    |
| argparse bad flag / missing file | 2    |
| `--config` nonexistent path     | 2 (via `existing_path` type) |

### `--log-level` choices (explicit list, no private API)

```python
LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
```

Resolved via `logging.getLevelName(args.log_level)` (returns the int). No `logging._levelToName` /
`_nameToLevel` private API.

### Logger configuration (Q4)

```
root logger
├── StreamHandler(stderr)        always; level = root level
└── FileHandler(log_file)        only if log_file is not None; level = DEBUG

yascheduler logger               inherits root handlers
backoff logger                   level = ERROR (suppress retry spam)
asyncssh logger                  level = ERROR (suppress key-exchange noise)
```

`logging.basicConfig` is NOT called (it would install a StreamHandler on stderr we don't
control). Handlers are added explicitly to the root logger.

## Cross-module data flows

### Daemon entrypoint flow (all 3 share this shape)

```
$ yascheduler (or python daemon_systemd.py / daemon_sysv.py -p PID)
   │
   ▼
entrypoint module (daemonize.py | daemon_systemd.py | daemon_sysv.py)
   │ argparse parser built via args.py helpers
   │   --config (add_config_arg, type=existing_path → exit 2 if missing)
   │   --log-level (add_log_level_arg, choices=LOG_LEVEL_CHOICES)
   │   --log-file (add_log_file_arg; sysv also -p/--pid-file)
   │ args = parser.parse_args(argv)
   │
   ▼
daemon_common.configure_logger(args.log_file, level) → logging.Logger
   │ root: StreamHandler(stderr) always + FileHandler(log_file) if set
   │ backoff/asyncssh → ERROR
   │
   ▼
config = Config.from_config_parser(args.config)
   │
   ▼
asyncio.run(daemon_common.run_daemon(config, logger))
   │ make_daemon(config, logger) → Orchestrator
   │ loop.add_signal_handler(SIGTERM/SIGINT → orch.stop + cancel tasks + sleep 0.25)
   │ await orch.start()
   │
   ▼ exit 0 on clean shutdown
except Exception → print "Error: ..." to stderr → exit 1
argparse error/—help → exit 2/0 (argparse native)
```

### sysv-only: `daemon.DaemonContext` wraps the above

```
$ python daemon_sysv.py -p PID -l LOG
   │ argparse (with -p/--pid-file, -l/--log-file, --config, --log-level)
   ▼
daemon.DaemonContext(pidfile=TimeoutPIDLockFile(pid_file), working_directory="/", umask=0o002)
   │ (logger FileHandler is created INSIDE the context so the file fd is the daemon's)
   │
   ▼ (same flow as above: configure_logger → Config → asyncio.run(run_daemon))
```

### CLI command flow (5 existing, after `--config`/`--log-level` added)

```
$ yanodes (or yasubmit/yasetnode/yastatus/yainit)
   │ argparse with add_config_arg + add_log_level_arg + command-specific flags
   │ args = parser.parse_args(argv)
   │
   ▼
logging: root.setLevel(args.log_level) + StreamHandler(stderr)
   │
   ▼
config = Config.from_config_parser(args.config)
   │
   ▼
make_cli_deps(config) → CLIDeps (or apply_schema(config.db) for init)
   │
   ▼ use-case / render / print
exit 0 | except → stderr "Error: ..." → exit 1 | argparse → exit 2
```

## Known bugs being fixed in this change

| ID | File / line                                   | Bug                                                                                                                                                                  | Fix                                                        |
| -- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| A  | `daemon_sysv.py:48` × `daemonize.py:82`        | `-l` short flag collision: sysv passes `-l logfile`, daemonize re-parses `sys.argv` and reads `-l` as `--log-level` → argparse rejects (exit 2). SysV path broken. | Each launcher parses once, passes ready values; no double-parse. |
| B  | `daemonize.py:88` `parse_args()` no argv       | `daemonize(log_file=...)` ignores kwarg context, reads `sys.argv`                                                                                                       | `daemonize(argv=None)` explicit; tests pass argv.           |
| C  | `daemonize.py:79-126`                          | No try/except around `make_daemon`/`orch.start()` → bare traceback, no `Error: ` message                                                                              | Wrap in try/except, exit 1 with stderr message.             |
| D  | `daemon_sysv.py:38` `working_directory=dirname(__file__)` | CWD = package dir in site-packages                                                                                                                          | `working_directory="/"` (python-daemon default).            |
| E  | `daemonize.py:87,90` `logging._levelToName`/`_nameToLevel` | Private CPython API                                                                                                                                                  | Explicit `LOG_LEVEL_CHOICES` list + `logging.getLevelName`. |
| F  | `daemonize.py:80` no `prog=`                  | `--help` shows wrong prog name                                                                                                                                         | `prog="yascheduler"` on all 3.                              |
| G  | `daemonize.py:45` `basicConfig` + 3-logger-only FileHandler | root warnings (`aiohttp`/`pg8000`/`asyncio`) miss the log file                                                                                                       | root FileHandler + root StreamHandler.                      |
| H  | `daemonize.py:79` no `argv` param             | Untestable without monkeypatch                                                                                                                                       | `argv: list[str] | None = None` on all entrypoints.          |
| I  | `daemon_systemd.py`                            | No `--config`/`--log-level`                                                                                                                                            | Added via `args.py`.                                        |
| J  | `daemon_sysv.py`                               | No `--config`/`--log-level`                                                                                                                                            | Added via `args.py`.                                        |

## `@to_sync` → `asyncio.run` migration (Q10)

| File                                | Before                                              | After                                                            |
| ----------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------- |
| `submit.py`                           | `@to_sync`<br>`async def submit(argv)`                | `def submit(argv): asyncio.run(_submit_async(argv))`<br>`async def _submit_async(argv)` |
| `show_nodes.py`                       | `@to_sync`<br>`async def show_nodes(argv)`            | `def show_nodes(argv): asyncio.run(_show_nodes_async(argv))`      |
| `manage_node.py`                      | `@to_sync`<br>`async def manage_node(argv)`           | `def manage_node(argv): asyncio.run(_manage_node_async(argv))`    |
| `check_status.py`                     | `@to_sync`<br>`async def check_status(argv)`          | `def check_status(argv): asyncio.run(_check_status_async(argv))` |
| `test_cli_smoke.py`                   | 1 test (daemonize only)                              | 6 tests (one per entrypoint); all assert `not hasattr(f, "__wrapped__")` |
| `test_cli_manage_node.py:703-704`      | `assert hasattr(manage_node, "__wrapped__")`          | deleted                                                          |

`client.py` keeps `to_sync` (legitimate cross-context caller). `shared/async_utils.py:to_sync`
stays.

## OpenSpec artifacts to update in same change

- `cli-commands` spec (modified): all 6 commands now in `entrypoints/cli/`; add
  `--config`/`--log-level` requirements + exit codes; add daemon-shared-core requirement;
  fix `--log-file` default for systemd (None/journald); document `@to_sync` → `asyncio.run`.
- `package-facades` spec (modified): remove `infra/cli/__init__.py` relative-import scenario
  (package liquidated); update daemon-launcher-not-re-exported scenario (paths unchanged but
  rationale updated).
- Knowledge graph (`docs/knowledge-graph.xml`): update `M-CLI-COMMANDS.fn-daemonize` path;
  add `M-ENTRYPOINTS-CLI-ARGS`, `M-DAEMON-COMMON`; update `M-DAEMON-SYSTEMD`/`M-DAEMON-SYSV`
  depends; rewrite `DF-DAEMON-START`; add CrossLink `M-DAEMON-COMMON -> M-DI`.

## Open questions

None. All resolved during explore (Q1–Q13).