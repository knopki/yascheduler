# CLI Commands

## Purpose

Define how CLI commands are wired to use cases via dependency injection,
how entry points resolve to the correct module, and how backward compatibility
is maintained through utils.py re-exports.

## Requirements

### Requirement: CLI commands call use cases via DI

The system SHALL implement each CLI command as a function that obtains
dependencies from di.py and delegates to use cases. The `yainit` command is a
bootstrap entrypoint: it performs infrastructure setup (service installation
and/or schema application) directly, without DI, and lives in the
`entrypoints/cli/` layer. The `yanodes` command is an execution-query
entrypoint that reads nodes and running tasks via a UoW and lives in
`entrypoints/cli/`. The `yasubmit` command is an execution-write entrypoint
that parses an AiiDA script file, builds task metadata, and submits a task
via `CLIDeps.submit` (which delegates to the `submit_task` use case); it
lives in `entrypoints/cli/`. The other 3 CLI commands (`check_status`,
`manage_node`, `daemonize`) remain in `infra/cli/`.

#### Scenario: yasubmit calls SubmitTask
- **WHEN** yasubmit is invoked with valid arguments
- **THEN** make_cli_deps() is called, SubmitTask use case is invoked via CLIDeps.submit, task_id is printed to stdout

#### Scenario: yastatus calls query use case
- **WHEN** yastatus is invoked
- **THEN** task statuses are queried via use case and displayed

#### Scenario: yascheduler starts daemon via orchestrator
- **WHEN** yascheduler is invoked
- **THEN** make_daemon() is called and orchestrator.start() is awaited

#### Scenario: yainit is a bootstrap entrypoint without DI
- **WHEN** `yainit` is invoked (with any combination of `--schema` / `--daemon` / no flags)
- **THEN** `init()` performs infrastructure setup (service install and/or schema apply) directly via `apply_schema(config.db)` and service-template file writes, without calling `make_cli_deps` or any use case

### Requirement: yasubmit parses AiiDA script and submits task

The `yasubmit` command SHALL parse an AiiDA script file (key=value metadata
lines), read the engine's declared input files from the current working
directory, build the task metadata, and submit a task via `CLIDeps.submit`
(which delegates to the `submit_task` use case). The command is implemented
as `submit()` in `yascheduler/entrypoints/cli/submit.py`, an async function
decorated with `@to_sync` (so the console_script invokes a synchronous
callable). It SHALL accept an `argv: list[str] | None = None` parameter for
testability (`None` reads `sys.argv`, the argparse convention; tests pass an
explicit list). It SHALL obtain `Config` via `Config.from_config_parser`,
build `CLIDeps` via `make_cli_deps(config)`, parse the script into key=value
pairs, validate that an `ENGINE` key is present and known to
`config.engines`, build the metadata dict (including `local_folder`, the
engine's input files, and the webhook fields when `PARENT` is present and
`config.local.webhook_url` is set), and call `deps.submit(label, metadata,
engine.name)`. The logic SHALL be split into private pure functions:
`_existing_path` (argparse type validator), `_parse_submit_args(argv)`,
`_parse_script_metadata(text)` (parse key=value lines, malformed lines
ignored), `_read_input_files(engine, local_folder)` (read each file in
`engine.input_files`, falling back to base64 on `UnicodeDecodeError`),
`_build_metadata(script_params, config, local_folder)` (assemble the
metadata dict, encapsulating the webhook branch).

#### Scenario: yasubmit happy path
- **WHEN** `yasubmit script.in` is invoked with a valid script containing `LABEL = Test job` and `ENGINE = g09`, and `g09` is a known engine with `input_files = ("input",)`, and the file `input` exists in the current working directory
- **THEN** `deps.submit("Test job", metadata, "g09")` is called where `metadata` contains `local_folder`, the input file contents, and the webhook fields only if `PARENT` is present and `config.local.webhook_url` is set; `str(task_id)` is printed to stdout; the process exits `0`

#### Scenario: yasubmit reads config and builds deps
- **WHEN** `submit()` is invoked
- **THEN** `Config.from_config_parser(CONFIG_FILE)` is called and `make_cli_deps(config)` is called to obtain `CLIDeps`

#### Scenario: yasubmit parses script metadata
- **WHEN** `_parse_script_metadata("LABEL = Test job\nENGINE = g09\nmalformed line\n")` is called
- **THEN** it returns `{"LABEL": "Test job", "ENGINE": "g09"}` (the malformed line without `=` is ignored)

#### Scenario: yasubmit reads input files as text
- **WHEN** `_read_input_files(engine, local_folder)` is called and a file in `engine.input_files` is valid UTF-8
- **THEN** the file's text content is included in the returned dict under the filename key

#### Scenario: yasubmit falls back to base64 for binary input files
- **WHEN** `_read_input_files(engine, local_folder)` is called and a file in `engine.input_files` raises `UnicodeDecodeError` when read as UTF-8
- **THEN** the file's bytes are base64-encoded and the ASCII string is included in the returned dict under the filename key (the current fallback behavior is preserved)

#### Scenario: yasubmit builds metadata with webhook when PARENT and webhook_url set
- **WHEN** `_build_metadata(script_params, config, local_folder)` is called with `script_params` containing `PARENT = 42` and `config.local.webhook_url` set to a non-None URL
- **THEN** the returned dict contains `webhook_url` (the URL) and `webhook_custom_params` equal to `{"parent": "42"}`, plus `local_folder` and the input files

#### Scenario: yasubmit omits webhook fields when PARENT absent
- **WHEN** `_build_metadata(script_params, config, local_folder)` is called with `script_params` NOT containing `PARENT`
- **THEN** the returned dict does NOT contain `webhook_url` or `webhook_custom_params`, regardless of `config.local.webhook_url`

#### Scenario: yasubmit omits webhook fields when webhook_url is None
- **WHEN** `_build_metadata(script_params, config, local_folder)` is called with `script_params` containing `PARENT` but `config.local.webhook_url` is `None`
- **THEN** the returned dict does NOT contain `webhook_url` or `webhook_custom_params`

### Requirement: yasubmit parses flags via argparse

`submit()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yasubmit",
description="Submit task to yascheduler via AiiDA script")` exposing one
positional argument:
- `script` (positional, `type=_existing_path`): the path to the AiiDA script
  file. `_existing_path(s)` SHALL return `Path(s)` if `s` is an existing
  file or raise `argparse.ArgumentTypeError(f"not a file: {s}")`, so a
  missing file is an argparse error (exit `2`), not a runtime error (exit
  `1`). This places argument-*shape* validation (the file exists) at the
  argparse layer, while argument-*content* validation (the `ENGINE` key is
  present; the engine name is known to config) remains in the body (exit
  `1`).

`submit()` SHALL NOT add `--json`, `--table`, or any output-mode flag. The
AiiDA scheduler plugin parses `int(stdout.strip())` on the success path
(see the AiiDA stdout compatibility requirement), so the success output is
fixed to `str(task_id)` and cannot be decorated.

#### Scenario: yasubmit --help shows argparse usage
- **WHEN** `yasubmit --help` is invoked
- **THEN** argparse prints the standard help screen showing `prog="yasubmit"` and the `script` positional argument with its description, and exits `0`

#### Scenario: yasubmit with no arguments exits 2
- **WHEN** `yasubmit` is invoked with no arguments
- **THEN** argparse prints a usage error to stderr (missing the required `script` argument) and exits `2`

#### Scenario: yasubmit with a non-existent script exits 2
- **WHEN** `yasubmit /nonexistent.in` is invoked
- **THEN** the `_existing_path` type validator raises `argparse.ArgumentTypeError("not a file: /nonexistent.in")`, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasubmit with extra positional exits 2
- **WHEN** `yasubmit script.in extra.in` is invoked
- **THEN** argparse prints a usage error to stderr (unrecognized extra positional) and exits `2`

#### Scenario: yasubmit with an unknown flag exits 2
- **WHEN** `yasubmit --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yasubmit prog is yasubmit in help and errors
- **WHEN** `yasubmit --help` or any argparse error is shown
- **THEN** the program name displayed is `yasubmit` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yasubmit validates script content in the body

After argparse succeeds, `submit()` SHALL validate the script *content* in
the body (exit `1` on failure, NOT exit `2` — argparse cannot inspect file
content). The validations are:
- The script's parsed `script_params` dict MUST contain an `ENGINE` key. If
  absent, `submit()` SHALL raise `ValueError("Script has not defined an
  engine")`, print `Error: Script has not defined an engine` to stderr, and
  exit `1`.
- The `ENGINE` value MUST be a known engine name in `config.engines`. If
  `config.engines.get(engine_name)` returns `None`, `submit()` SHALL raise
  `ValueError(f"Engine {engine_name} is not supported")`, print the message
  to stderr, and exit `1`.

#### Scenario: yasubmit exits 1 when ENGINE key is missing
- **WHEN** `yasubmit script.in` is invoked with a script containing `LABEL = Test` but no `ENGINE = ...` line
- **THEN** `Error: Script has not defined an engine` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasubmit exits 1 when engine is unknown
- **WHEN** `yasubmit script.in` is invoked with a script containing `ENGINE = unknown` and `config.engines.get("unknown")` returns `None`
- **THEN** `Error: Engine unknown is not supported` is printed to stderr, nothing is printed to stdout, and the process exits `1`

### Requirement: yasubmit exit code contract

`submit()` SHALL follow the `0`/`1`/`2` exit-code contract:
- `0` on success: `print(str(task_id))`, normal completion.
- `1` on runtime failure: `ENGINE` key missing, engine name unknown to
  config, DB error, config parse error, or any unexpected exception caught
  at the top level. The error SHALL be printed to stderr as
  `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error: argparse default (missing script arg, file not
  found via `type=_existing_path`, extra positional, unknown flag).

`submit()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body.

#### Scenario: yasubmit exits 0 on success
- **WHEN** `yasubmit script.in` is invoked and the submission completes without exception
- **THEN** `str(task_id)` is printed to stdout and the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yasubmit exits 1 on DB error
- **WHEN** `deps.submit(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasubmit exits 1 on config error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasubmit exits 1 on unexpected exception
- **WHEN** any other unexpected exception is raised during execution
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasubmit --help exits 0
- **WHEN** `yasubmit --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yasubmit missing script exits 2
- **WHEN** `yasubmit` is invoked with no arguments
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yasubmit non-existent file exits 2
- **WHEN** `yasubmit /nonexistent.in` is invoked
- **THEN** argparse prints a usage error to stderr (the `_existing_path` validator rejected the path) and exits `2`

### Requirement: yasubmit preserves AiiDA stdout compatibility

The success path of `yasubmit` SHALL print exactly `str(task_id)` to stdout
— no prefix, no suffix, no JSON envelope, no decoration. The failure path
SHALL print nothing to stdout and an error message to stderr. This contract
SHALL be preserved exactly because the AiiDA scheduler plugin
(`entrypoints/aiida_plugin.py:_parse_submit_output`) parses
`int(stdout.strip())` and treats `ValueError` as "no task id received":
```python
output = stdout.strip()
try:
    int(output)
except ValueError:
    self.logger.error("Submitting failed, no task id received")
return output
```
`_get_submit_command` returns `f"{_CMD_PREFIX}yasubmit {submit_script}"`, so
AiiDA executes `yasubmit` as a subprocess over SSH transport and parses its
stdout. Any decoration of the success output breaks the consumer. This is
the key constraint distinguishing `yasubmit` from query-oriented commands
like `yanodes` (which has no machine consumer of its output and can freely
change format). `yasubmit` is a write command; the `--json` convention
established by `yanodes` applies to query-oriented commands only.

#### Scenario: yasubmit success prints only the task id
- **WHEN** `yasubmit script.in` succeeds and `deps.submit(...)` returns `42`
- **THEN** stdout contains exactly `42` (possibly with a trailing newline from `print`), with no prefix, suffix, JSON envelope, or other decoration

#### Scenario: yasubmit failure prints nothing to stdout
- **WHEN** `yasubmit script.in` fails (ENGINE key missing, engine unknown, DB error, or any exception)
- **THEN** stdout is empty; the error message is on stderr; the process exits `1` (or `2` for argparse errors)

#### Scenario: yasubmit does not add output-mode flags
- **WHEN** the `submit()` argparse parser is inspected
- **THEN** it does NOT define `--json`, `--table`, or any other output-mode flag (the success output is fixed to `str(task_id)`)

#### Scenario: AiiDA plugin is unchanged
- **WHEN** `entrypoints/aiida_plugin.py` is inspected after this change
- **THEN** `_get_submit_command` still returns `f"{_CMD_PREFIX}yasubmit {submit_script}"` and `_parse_submit_output` still does `int(stdout.strip())` (the AiiDA contract is not touched)

### Requirement: Entry points updated

The system SHALL update pyproject.toml console_scripts to point to
`yascheduler.entrypoints.cli.init` for `yainit`, to
`yascheduler.entrypoints.cli.show_nodes` for `yanodes`, and to
`yascheduler.entrypoints.cli.submit` for `yasubmit`. The other 3 CLI
commands (`check_status`, `manage_node`, `daemonize`) continue to point at
`yascheduler.infra.cli.*`.

#### Scenario: yainit resolves to the new location
- **WHEN** `yainit` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.init:init` is invoked

#### Scenario: yanodes resolves to the new location
- **WHEN** `yanodes` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.show_nodes:show_nodes` is invoked

#### Scenario: yasubmit resolves to the new location
- **WHEN** `yasubmit` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.submit:submit` is invoked

#### Scenario: All 6 commands functional
- **WHEN** each CLI command is invoked with `--help`
- **THEN** usage information is displayed (commands resolve correctly)

The `yainit` command (`init()` in `entrypoints/cli/init.py`) SHALL be a plain
synchronous function. When schema application is requested, it SHALL call
`apply_schema(config.db)` from `infra/persistence/postgres_schema.py`. When
service installation is requested, it SHALL detect systemd via
`Path("/run/systemd/system").is_dir()` (NOT by shelling out to `pidof systemd`),
render the matching template, and SHALL overwrite the existing service file on
re-run (instead of silently skipping). Service file write failures
(`OSError`, including missing `/etc/systemd/system/` or `/etc/init.d/` parent
directory) SHALL cause `init()` to print the error and exit `1`.

#### Scenario: yainit with no flags installs service and applies schema
- **WHEN** `yainit` is invoked with no flags
- **THEN** the systemd or sysv service file is installed (auto-detected) and `apply_schema(config.db)` is called synchronously to initialize the database; the process exits `0` on success

#### Scenario: yainit --schema applies only the schema
- **WHEN** `yainit --schema` is invoked
- **THEN** `apply_schema(config.db)` is called synchronously, no service file is written, and `init()` exits `0` on success

#### Scenario: yainit --daemon installs only the service
- **WHEN** `yainit --daemon` is invoked
- **THEN** the auto-detected service file (systemd or sysv) is written, `apply_schema` is NOT called, and `init()` exits `0` on success

#### Scenario: yainit --schema --daemon runs both (equals default)
- **WHEN** `yainit --schema --daemon` is invoked
- **THEN** the service file is installed AND `apply_schema(config.db)` is called (identical to the no-flags default), and `init()` exits `0` on success

#### Scenario: yainit --help shows argparse usage
- **WHEN** `yainit --help` is invoked
- **THEN** argparse prints the standard help screen listing `--schema` and `--daemon` with their descriptions, and exits `0`

#### Scenario: yainit with an unknown flag exits 2
- **WHEN** `yainit --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yainit initializes database idempotently
- **WHEN** `yainit --schema` (or the default invocation) is run against an already-initialized database
- **THEN** `apply_schema(config.db)` succeeds (because `schema.sql` uses `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN IF NOT EXISTS`) and `init()` exits `0`

#### Scenario: yainit exits 1 on DatabaseError from apply_schema
- **WHEN** `apply_schema(config.db)` raises `DatabaseError` (e.g. connection refused, authentication failure, type mismatch)
- **THEN** `init()` prints the error and exits `1`

#### Scenario: yainit exits 1 on service file write failure
- **WHEN** writing the service file raises `OSError` (e.g. permission denied, missing `/etc/systemd/system/` or `/etc/init.d/` parent directory, disk full)
- **THEN** `init()` prints `Error: cannot write to <path>: <error>` and exits `1`

#### Scenario: yainit overwrites existing systemd unit file
- **WHEN** `yainit --daemon` (or the default) is invoked on a systemd host and `/etc/systemd/system/yascheduler.service` already exists
- **THEN** the file is overwritten with the freshly rendered template content and `init()` exits `0`

#### Scenario: yainit overwrites existing sysv init script
- **WHEN** `yainit --daemon` (or the default) is invoked on a sysv host and `/etc/init.d/yascheduler` already exists
- **THEN** the file is overwritten with the freshly rendered template content, `chmod 0755` is applied, and `init()` exits `0`

#### Scenario: yainit detects systemd via /run/systemd/system
- **WHEN** `yainit` service install is requested and `/run/systemd/system/` exists as a directory
- **THEN** the systemd unit template is rendered and written to `/etc/systemd/system/yascheduler.service`

#### Scenario: yainit detects non-systemd host
- **WHEN** `yainit` service install is requested and `/run/systemd/system/` does NOT exist
- **THEN** the sysv init script template is rendered and written to `/etc/init.d/yascheduler` with `chmod 0755`

### Requirement: utils.py preserves re-exports

The system SHALL keep utils.py as a re-export module importing from
adapters.cli.commands.

#### Scenario: Direct import of utils.submit still works
- **WHEN** from yascheduler.utils import submit is executed
- **THEN** the function from adapters.cli.commands is returned

### Requirement: yanodes lists nodes and their running tasks

The `yanodes` command SHALL list nodes and their currently running tasks. The command is implemented as `show_nodes()` in `yascheduler/entrypoints/cli/show_nodes.py`, an async function decorated with `@to_sync` (so the console_script invokes a synchronous callable). It SHALL accept an `argv: list[str] | None = None` parameter for testability (`None` reads `sys.argv`, the argparse convention; tests pass an explicit list). It SHALL obtain `Config` via `Config.from_config_parser`, build `CLIDeps` via `make_cli_deps(config)`, open a single UoW, read nodes via `uow.nodes.list_all()` and running tasks via `uow.tasks.list_by_status({TaskStatus.RUNNING})`, join them in memory, apply the active filters, and print the result via the selected renderer. Output row order SHALL preserve the order returned by `uow.nodes.list_all()` (no sorting). Each node SHALL produce exactly one output row (table) or one output object (JSON).

#### Scenario: yanodes default invocation lists all nodes
- **WHEN** `yanodes` is invoked with no flags
- **THEN** all nodes returned by `uow.nodes.list_all()` are listed in the table format, each as one row, in the order returned by `list_all()`, and the process exits `0`

#### Scenario: yanodes preserves list_all order
- **WHEN** `uow.nodes.list_all()` returns nodes in a given order (e.g. `[node_b, node_a, node_c]`)
- **THEN** the output rows appear in that same order (`node_b`, `node_a`, `node_c`), with no reordering by ip, enabled, or any other key

#### Scenario: yanodes with no nodes exits 0
- **WHEN** `uow.nodes.list_all()` returns an empty list
- **THEN** the table renders only its header row (or no rows) and the process exits `0` (an empty result is a valid query answer, not a failure)

#### Scenario: yanodes one row per node
- **WHEN** a node has one running task with `allocated_ip == node.ip`
- **THEN** exactly one row is emitted for that node, showing the task's `task_id` and `label`
- **AND** when a node has no running task, exactly one row is emitted with the free-node display (`TASK_ID=-`, `LABEL=-` in table; `occupied_by: null` in JSON)

#### Scenario: yanodes reads config and builds deps
- **WHEN** `show_nodes()` is invoked
- **THEN** `Config.from_config_parser(CONFIG_FILE)` is called and `make_cli_deps(config)` is called to obtain the UoW factory

### Requirement: yanodes parses flags via argparse

`show_nodes()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yanodes",
description="Show nodes and their running tasks")` exposing:
- `--json` (`store_true`): emit JSON instead of the default table. Selects the
  renderer; not a filter.
- `--enabled` (`store_true`): include only nodes where `node.enabled` is True.
- `--disabled` (`store_true`): include only nodes where `node.enabled` is False.
- `--busy` (`store_true`): include only nodes that have ≥1 RUNNING task with
  `allocated_ip == node.ip`.
- `--free` (`store_true`): include only nodes with no such RUNNING task.
- `--cloud NAME` (`str`): include only nodes where `node.cloud == NAME` (exact
  string equality).
- `--no-cloud` (`store_true`): include only nodes where `node.cloud is None`.

`--enabled` and `--disabled` SHALL be subset selectors, NOT mutually exclusive:
`--enabled --disabled` selects all nodes (= the default, no enabled-axis
filtering). `--busy` and `--free` SHALL be subset selectors, NOT mutually
exclusive: `--busy --free` selects all nodes. `--cloud` and `--no-cloud` SHALL
be in a `mutually_exclusive_group`: `--cloud NAME --no-cloud` is an argparse
error (exit `2`). All filters SHALL compose by AND: a row is emitted iff it
passes every active filter.

#### Scenario: yanodes --help shows argparse usage
- **WHEN** `yanodes --help` is invoked
- **THEN** argparse prints the standard help screen listing `--json`, `--enabled`, `--disabled`, `--busy`, `--free`, `--cloud NAME`, `--no-cloud` with their descriptions, and exits `0`

#### Scenario: yanodes with an unknown flag exits 2
- **WHEN** `yanodes --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yanodes --cloud and --no-cloud are mutually exclusive
- **WHEN** `yanodes --cloud hetzner --no-cloud` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2` (mutex group violation)

#### Scenario: yanodes --enabled --disabled equals default
- **WHEN** `yanodes --enabled --disabled` is invoked
- **THEN** no enabled-axis filter is applied and all nodes (enabled and disabled) are listed

#### Scenario: yanodes --busy --free equals default
- **WHEN** `yanodes --busy --free` is invoked
- **THEN** no busy-axis filter is applied and all nodes (busy and free) are listed

#### Scenario: yanodes filters compose by AND
- **WHEN** `yanodes --enabled --busy --cloud hetzner` is invoked
- **THEN** only nodes that are enabled AND busy AND have `cloud == "hetzner"` are listed

#### Scenario: yanodes --enabled lists only enabled nodes
- **WHEN** `yanodes --enabled` is invoked against a node set containing both enabled and disabled nodes
- **THEN** only the enabled nodes appear in the output

#### Scenario: yanodes --disabled lists only disabled nodes
- **WHEN** `yanodes --disabled` is invoked against a node set containing both enabled and disabled nodes
- **THEN** only the disabled nodes appear in the output

#### Scenario: yanodes --busy lists only nodes with a running task
- **WHEN** `yanodes --busy` is invoked against a node set where some nodes have a RUNNING task and others do not
- **THEN** only the nodes with a RUNNING task (whose `allocated_ip` matches the node's `ip`) appear in the output

#### Scenario: yanodes --free lists only nodes without a running task
- **WHEN** `yanodes --free` is invoked against a node set where some nodes have a RUNNING task and others do not
- **THEN** only the nodes with no RUNNING task appear in the output

#### Scenario: yanodes --cloud NAME exact-matches the cloud field
- **WHEN** `yanodes --cloud hetzner` is invoked against a node set containing nodes with `cloud="hetzner"`, `cloud="exoscale"`, and `cloud=None`
- **THEN** only the nodes with `cloud == "hetzner"` appear in the output (no substring/regex matching; static nodes with `cloud=None` are excluded)

#### Scenario: yanodes --no-cloud lists only static nodes
- **WHEN** `yanodes --no-cloud` is invoked against a node set containing nodes with `cloud="hetzner"` and `cloud=None`
- **THEN** only the nodes with `cloud is None` (static nodes) appear in the output

### Requirement: yanodes exit code contract

`show_nodes()` SHALL follow the `0`/`1`/`2` exit-code contract:
- `0` on success, including an empty filter result (an empty table or `[]` is
  a valid query answer, not a failure).
- `1` on runtime failure: DB error, config parse error, or any unexpected
  exception caught at the top level. The error SHALL be printed to stderr as
  `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error (argparse default — unknown flag, bad value, mutex
  violation).

`show_nodes()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body.

#### Scenario: yanodes exits 0 on success
- **WHEN** `yanodes` is invoked and the query completes without exception
- **THEN** the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yanodes exits 0 on empty filter result
- **WHEN** `yanodes --cloud nonexistent` is invoked and no node matches
- **THEN** an empty table (header only, or no rows) is printed and the process exits `0`

#### Scenario: yanodes exits 1 on DB error
- **WHEN** `uow.nodes.list_all()` or `uow.tasks.list_by_status(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yanodes exits 1 on config error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yanodes exits 1 on unexpected exception
- **WHEN** any other unexpected exception is raised during execution
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yanodes --help exits 0
- **WHEN** `yanodes --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yanodes --bogus exits 2
- **WHEN** `yanodes --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

### Requirement: yanodes default table output format

The default output of `yanodes` (when `--json` is not given) SHALL be a
fixed-width text table rendered with stdlib string formatting only (no
external dependencies such as `rich` or `tabulate`). The table SHALL have a
header row followed by one data row per node, in the order returned by
`uow.nodes.list_all()`. Column widths SHALL be computed from the data (the
maximum of the header width and the widest cell width per column) so the
table is self-aligning regardless of value lengths.

The columns SHALL be: `IP`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`, `TASK_ID`,
`LABEL`. Display-only transformations SHALL apply to the table cells:

| column   | raw value       | table cell                       |
| -------- | --------------- | -------------------------------- |
| IP       | `node.ip`         | as-is                            |
| PORT     | `node.port`       | `-` when `22`, else the int      |
| NCPUS    | `node.ncpus`      | `MAX` when `0`, else the int     |
| ENABLED  | `node.enabled`    | `yes` when True, `no` when False |
| CLOUD    | `node.cloud`      | `-` when None, else the string   |
| TASK_ID  | `task.task_id`     | `-` when free, else the int      |
| LABEL    | `task.label`       | `-` when free, else the string   |

A node is "free" when no RUNNING task has `allocated_ip == node.ip`; it is
"busy" when exactly one RUNNING task does (the one-task-per-node invariant).

#### Scenario: yanodes table has a header row
- **WHEN** `yanodes` is invoked (with or without filter flags)
- **THEN** the first line of output is the header row `IP`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`, `TASK_ID`, `LABEL` (column separators and exact spacing follow the fixed-width computation)

#### Scenario: yanodes table shows a busy node
- **WHEN** a node `10.0.0.1` with `port=22`, `ncpus=4`, `enabled=True`, `cloud=None` has a RUNNING task with `task_id=1`, `label="my_job"`
- **THEN** one row is emitted with PORT=`-`, NCPUS=`4`, ENABLED=`yes`, CLOUD=`-`, TASK_ID=`1`, LABEL=`my_job`

#### Scenario: yanodes table shows a free node
- **WHEN** a node `10.0.0.2` with `port=2222`, `ncpus=0`, `enabled=False`, `cloud="hetzner"` has no RUNNING task
- **THEN** one row is emitted with PORT=`2222`, NCPUS=`MAX`, ENABLED=`no`, CLOUD=`hetzner`, TASK_ID=`-`, LABEL=`-`

#### Scenario: yanodes table hides port 22
- **WHEN** a node has `port=22`
- **THEN** the PORT cell is `-` (the default SSH port is not shown)

#### Scenario: yanodes table shows non-default port
- **WHEN** a node has `port=2222`
- **THEN** the PORT cell is `2222`

#### Scenario: yanodes table shows MAX for zero ncpus
- **WHEN** a node has `ncpus=0`
- **THEN** the NCPUS cell is `MAX`

#### Scenario: yanodes table shows enabled as yes/no
- **WHEN** a node has `enabled=True` (resp. `False`)
- **THEN** the ENABLED cell is `yes` (resp. `no`)

#### Scenario: yanodes table shows dash for null cloud
- **WHEN** a node has `cloud=None`
- **THEN** the CLOUD cell is `-`

#### Scenario: yanodes table column widths fit the data
- **WHEN** the widest IP value is `10.0.0.255` (10 chars) and the header `IP` is 2 chars
- **THEN** the IP column is at least 10 chars wide and all IP cells are padded to that width

#### Scenario: yanodes table no external deps
- **WHEN** the implementation of `_render_nodes_table` is inspected
- **THEN** it uses only stdlib string formatting (f-string width specifiers, `str.ljust`, or equivalent) and does NOT import `rich`, `tabulate`, or any other third-party formatting library

### Requirement: yanodes --json output format

When `--json` is given, `yanodes` SHALL emit `json.dumps(list_of_objects)`
where each object represents one node with raw domain values (NO display
transformations — no `-`, no `MAX`, no `yes`/`no`). The object schema SHALL
be:

```
{"ip": str, "port": int, "ncpus": int, "enabled": bool,
 "cloud": str | null, "occupied_by": {"task_id": int, "label": str} | null}
```

- `port`: the raw `node.port` int (22 stays 22, 2222 stays 2222).
- `ncpus`: the raw `node.ncpus` int (0 stays 0 — `MAX` is a table-only display
  token and MUST NOT appear in JSON).
- `cloud`: `null` for static nodes, else the `node.cloud` string.
- `occupied_by`: `null` when the node is free; a single object
  `{"task_id": int, "label": str}` when the node is busy (one RUNNING task).
  The single-object shape encodes the one-RUNNING-task-per-node invariant;
  promotion to an array is a separate change if the invariant ever relaxes.

One object per node, in the order returned by `uow.nodes.list_all()`.

#### Scenario: yanodes --json emits a list of objects
- **WHEN** `yanodes --json` is invoked against a non-empty node set
- **THEN** the output is valid JSON parseable as a list of objects, one per node, in `list_all()` order

#### Scenario: yanodes --json uses raw port
- **WHEN** a node has `port=22`
- **THEN** the JSON object's `port` field is `22` (NOT `null` or `"-"`)

#### Scenario: yanodes --json uses raw ncpus
- **WHEN** a node has `ncpus=0`
- **THEN** the JSON object's `ncpus` field is `0` (NOT `"MAX"` or `null`)

#### Scenario: yanodes --json busy node occupied_by is an object
- **WHEN** a node has a RUNNING task with `task_id=1`, `label="my_job"`
- **THEN** the JSON object's `occupied_by` field is `{"task_id": 1, "label": "my_job"}`

#### Scenario: yanodes --json free node occupied_by is null
- **WHEN** a node has no RUNNING task
- **THEN** the JSON object's `occupied_by` field is `null`

#### Scenario: yanodes --json static node cloud is null
- **WHEN** a node has `cloud=None`
- **THEN** the JSON object's `cloud` field is `null`

#### Scenario: yanodes --json empty result is empty list
- **WHEN** `yanodes --json` is invoked and no node matches the filters
- **THEN** the output is `[]` and the process exits `0`

### Requirement: yanodes joins nodes to running tasks in memory

`show_nodes()` SHALL perform the node-to-running-task join in memory within a
single UoW: it SHALL read `uow.nodes.list_all()` and
`uow.tasks.list_by_status({TaskStatus.RUNNING})` (two reads within one UoW),
build a `tasks_by_ip` dict mapping `allocated_ip` to the single running task
on that ip (O(n+m) single pass over tasks), and look up each node's task via
`tasks_by_ip.get(node.ip)`. It SHALL NOT perform an O(n*m) nested scan (the
current implementation rebuilds a `node_tasks` list per node by scanning all
tasks).

#### Scenario: yanodes join is O(n+m)
- **WHEN** the implementation of `_fetch_nodes_view` (or equivalent) is inspected
- **THEN** it builds a `tasks_by_ip` dict once and looks up each node's task by ip via dict access, rather than scanning the full task list per node

#### Scenario: yanodes reads nodes and tasks within one UoW
- **WHEN** `show_nodes()` is invoked
- **THEN** both `uow.nodes.list_all()` and `uow.tasks.list_by_status({TaskStatus.RUNNING})` are called within the same `async with deps.uow_factory() as uow:` block

### Requirement: --json is the machine-readable CLI output convention

The `--json` flag on `yanodes` SHALL establish the project convention for
machine-readable CLI output: query-oriented CLI commands SHALL offer a
`--json` flag that emits raw domain values as JSON (no display
transformations), so that scripts can consume the output without
reverse-mapping display tokens. Future query-oriented CLI commands (e.g.
`yastatus` if extended) MAY follow the same convention; this is not a
retroactive requirement on existing commands.

#### Scenario: yanodes --json is the first instance of the convention
- **WHEN** `yanodes --json` is invoked
- **THEN** the output is raw-domain-value JSON (no display tokens), establishing the convention for future query-oriented CLI commands

#### Scenario: --json convention does not retroactively require changes to other commands
- **WHEN** `yasubmit`, `yastatus`, `yasetnode`, or `yascheduler` is inspected
- **THEN** no `--json` flag is required to be present on those commands by this change (the convention is forward-looking, established by `yanodes` as the first instance)
