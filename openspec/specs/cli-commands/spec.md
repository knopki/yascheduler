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
lives in `entrypoints/cli/`. The `yasetnode` command is an execution-mutate
entrypoint that adds, soft-removes, or hard-removes nodes via a UoW (and via
`SSHMachineGateway` for the add path's optional remote setup); it lives in
`entrypoints/cli/`. The `yastatus` command is an execution-query entrypoint
that reads tasks (and, in verbose mode, remote machine output) via `CLIDeps`
and the SSH gateway; it lives in `entrypoints/cli/`. The other 1 CLI command
(`daemonize`) remains in `infra/cli/`.

#### Scenario: yasubmit calls SubmitTask
- **WHEN** yasubmit is invoked with valid arguments
- **THEN** make_cli_deps() is called, SubmitTask use case is invoked via CLIDeps.submit, task_id is printed to stdout

#### Scenario: yastatus queries tasks via CLIDeps
- **WHEN** yastatus is invoked (default mode, `-i`, `--json`, or `-v`)
- **THEN** make_cli_deps() is called, tasks are read via `uow.tasks.list_by_status({RUNNING, TO_DO})` (default) or `uow.tasks.list_by_jobs(job_ids)` (with `-j`), and the selected renderer prints the result

#### Scenario: yascheduler starts daemon via orchestrator
- **WHEN** yascheduler is invoked
- **THEN** make_daemon() is called and orchestrator.start() is awaited

#### Scenario: yainit is a bootstrap entrypoint without DI
- **WHEN** `yainit` is invoked (with any combination of `--schema` / `--daemon` / no flags)
- **THEN** `init()` performs infrastructure setup (service install and/or schema apply) directly via `apply_schema(config.db)` and service-template file writes, without calling `make_cli_deps` or any use case

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW
- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(CONFIG_FILE)` is called, `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineGateway` is constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened via `async with deps.uow_factory() as uow:` solely to read `already_there = await uow.nodes.get(spec.host) is not None` (it is closed without commit — nothing was mutated), and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the gateway is passed to the add helper.

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
`yascheduler.entrypoints.cli.show_nodes` for `yanodes`, to
`yascheduler.entrypoints.cli.submit` for `yasubmit`, to
`yascheduler.entrypoints.cli.manage_node` for `yasetnode`, and to
`yascheduler.entrypoints.cli.check_status` for `yastatus`. The other 1 CLI
command (`daemonize`) continues to point at `yascheduler.infra.cli.*`.

#### Scenario: yainit resolves to the new location
- **WHEN** `yainit` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.init:init` is invoked

#### Scenario: yanodes resolves to the new location
- **WHEN** `yanodes` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.show_nodes:show_nodes` is invoked

#### Scenario: yasubmit resolves to the new location
- **WHEN** `yasubmit` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.submit:submit` is invoked

#### Scenario: yastatus resolves to the new location
- **WHEN** `yastatus` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.check_status:check_status` is invoked

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

The `--json` flag on `yanodes` and `yastatus` SHALL establish the project
convention for machine-readable CLI output: query-oriented CLI commands SHALL
offer a `--json` flag that emits raw domain values as JSON (no display
transformations), so that scripts can consume the output without
reverse-mapping display tokens. `yanodes --json` is the first instance of the
convention; `yastatus --json` is the second instance. Future query-oriented
CLI commands MAY follow the same convention; this is not a retroactive
requirement on existing commands that lack a machine consumer.

#### Scenario: yanodes --json is the first instance of the convention
- **WHEN** `yanodes --json` is invoked
- **THEN** the output is raw-domain-value JSON (no display tokens), establishing the convention

#### Scenario: yastatus --json is the second instance of the convention
- **WHEN** `yastatus --json` is invoked
- **THEN** the output is raw-domain-value JSON (no display tokens), the second instance of the convention established by `yanodes`

#### Scenario: --json convention does not retroactively require changes to other commands
- **WHEN** `yasubmit`, `yasetnode`, or `yascheduler` is inspected
- **THEN** no `--json` flag is required to be present on those commands by this change (the convention is forward-looking; `yastatus` is the second instance, not a retroactive mandate)

### Requirement: yasetnode parses host grammar via argparse type

The `yasetnode` command SHALL accept a single positional `host` argument
parsed by a custom `argparse` type `_parse_host_spec(s) -> HostSpec`, where
`HostSpec` is a frozen dataclass with fields `host: str`,
`username: str | None`, `port: int`, `ncpus: int | None`. The grammar is
`[user@]host[:port][~ncpus]`:

- `user` — non-empty string without `@`. When the `user@` prefix is absent,
  `HostSpec.username` is `None` (the default is resolved later from
  `config.remote.username` by `manage_node`, NOT hardcoded by the parser).
- `host` — either an IPv4 literal or a bracketed IPv6 literal `[...]`. The
  host string MUST be non-empty.
- `port` — integer in `1..65535`. When `:port` is absent, the parser
  applies the default `22`.
- `ncpus` — non-negative integer. `~0` and absent `~ncpus` both yield
  `HostSpec.ncpus = None` (the unlimited/MAX sentinel; downstream
  `Node(ncpus=0)` encodes this in the DB).

Malformed input (multiple `@`, multiple `~`, empty segments, unbracketed
IPv6, port out of range, negative ncpus, non-integer port/ncpus) SHALL
raise `argparse.ArgumentTypeError`, which argparse surfaces as a usage error
with exit `2`.

#### Scenario: yasetnode plain IPv4 host
- **WHEN** `_parse_host_spec("10.0.0.1")` is called
- **THEN** it returns a `HostSpec(host="10.0.0.1", username=None, port=22, ncpus=None)`

#### Scenario: yasetnode user@host
- **WHEN** `_parse_host_spec("deploy@10.0.0.1")` is called
- **THEN** it returns a `HostSpec(host="10.0.0.1", username="deploy", port=22, ncpus=None)`

#### Scenario: yasetnode host with explicit port
- **WHEN** `_parse_host_spec("10.0.0.1:2222")` is called
- **THEN** it returns a `HostSpec(host="10.0.0.1", username=None, port=2222, ncpus=None)`

#### Scenario: yasetnode host with ncpus
- **WHEN** `_parse_host_spec("10.0.0.1~4")` is called
- **THEN** it returns a `HostSpec(host="10.0.0.1", username=None, port=22, ncpus=4)`

#### Scenario: yasetnode full spec user@host:port~ncpus
- **WHEN** `_parse_host_spec("deploy@10.0.0.1:2222~4")` is called
- **THEN** it returns a `HostSpec(host="10.0.0.1", username="deploy", port=2222, ncpus=4)`

#### Scenario: yasetnode bracketed IPv6
- **WHEN** `_parse_host_spec("[::1]")` is called
- **THEN** it returns a `HostSpec(host="::1", username=None, port=22, ncpus=None)`

#### Scenario: yasetnode bracketed IPv6 with port
- **WHEN** `_parse_host_spec("[fe80::1]:2222")` is called
- **THEN** it returns a `HostSpec(host="fe80::1", username=None, port=2222, ncpus=None)`

#### Scenario: yasetnode tilde-zero maps to None ncpus
- **WHEN** `_parse_host_spec("10.0.0.1~0")` is called
- **THEN** it returns a `HostSpec(host="10.0.0.1", username=None, port=22, ncpus=None)` (the `0` is normalized to `None`, the unlimited sentinel)

#### Scenario: yasetnode unbracketed IPv6 is rejected
- **WHEN** `_parse_host_spec("::1")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError` (IPv6 must be bracketed to disambiguate from `:port`)

#### Scenario: yasetnode multiple at-signs rejected
- **WHEN** `_parse_host_spec("a@b@c")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode multiple tildes rejected
- **WHEN** `_parse_host_spec("10.0.0.1~4~5")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode empty port rejected
- **WHEN** `_parse_host_spec("10.0.0.1:")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode port out of range rejected
- **WHEN** `_parse_host_spec("10.0.0.1:99999")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError` (port must be `1..65535`)

#### Scenario: yasetnode port zero rejected
- **WHEN** `_parse_host_spec("10.0.0.1:0")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError` (port `0` is not a valid SSH port)

#### Scenario: yasetnode negative ncpus rejected
- **WHEN** `_parse_host_spec("10.0.0.1~-5")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode non-integer port rejected
- **WHEN** `_parse_host_spec("10.0.0.1:abc")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode hostname passes (no DNS validation)
- **WHEN** `_parse_host_spec("compute-node-7")` is called
- **THEN** it returns a `HostSpec(host="compute-node-7", username=None, port=22, ncpus=None)` (the parser validates structure, not reachability)

#### Scenario: yasetnode missing host positional exits 2
- **WHEN** `yasetnode` is invoked with no arguments
- **THEN** argparse prints a usage error to stderr (missing the required `host` argument) and exits `2`

#### Scenario: yasetnode malformed host exits 2
- **WHEN** `yasetnode ::1` is invoked (unbracketed IPv6)
- **THEN** the `_parse_host_spec` type raises `argparse.ArgumentTypeError`, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode prog is yasetnode in help and errors
- **WHEN** `yasetnode --help` or any argparse error is shown
- **THEN** the program name displayed is `yasetnode` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yasetnode parses flags via argparse

`manage_node()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yasetnode",
description="Add or remove nodes from the yascheduler daemon")` exposing:
- `host` (positional, `type=_parse_host_spec`): the node spec (see the host
  grammar requirement).
- `--skip-setup` (`store_true`): on the add path, skip the remote
  `gateway.setup_node` step. Valid ONLY on the add path.
- `--remove-soft` (`store_true`): disable the node if it has running tasks,
  or remove it immediately if not. Mutually exclusive with `--remove-hard`.
- `--remove-hard` (`store_true`): mark associated RUNNING tasks DONE and
  remove the node record. Mutually exclusive with `--remove-soft`.

`--remove-soft` and `--remove-hard` SHALL be in a
`mutually_exclusive_group`: passing both exits `2`. `--skip-setup` is
incompatible with either remove flag; a body-level check after `parse_args`
SHALL call `parser.error(...)` when
`skip_setup and (remove_soft or remove_hard)`, producing exit `2`. The
flags SHALL use `action="store_true"` and SHALL NOT accept a value (the
previous `nargs="?", type=bool, const=True` pattern was removed because
`bool("false") is True`).

The parser SHALL accept an `argv: list[str] | None = None` parameter
forwarded to `parser.parse_args(argv)`. `None` reads `sys.argv` (the
console_script convention); tests pass an explicit list.

#### Scenario: yasetnode --help shows argparse usage
- **WHEN** `yasetnode --help` is invoked
- **THEN** argparse prints the standard help screen showing `prog="yasetnode"`, the `host` positional argument with its description, and the three flags, and exits `0`

#### Scenario: yasetnode with unknown flag exits 2
- **WHEN** `yasetnode 10.0.0.1 --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yasetnode --remove-soft --remove-hard exits 2
- **WHEN** `yasetnode 10.0.0.1 --remove-soft --remove-hard` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yasetnode --skip-setup --remove-hard exits 2
- **WHEN** `yasetnode 10.0.0.1 --skip-setup --remove-hard` is invoked
- **THEN** the body-level `parser.error(...)` fires, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode --skip-setup --remove-soft exits 2
- **WHEN** `yasetnode 10.0.0.1 --skip-setup --remove-soft` is invoked
- **THEN** the body-level `parser.error(...)` fires, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode --skip-setup does not accept a value
- **WHEN** `yasetnode 10.0.0.1 --skip-setup true` is invoked
- **THEN** argparse treats `true` as an unknown extra positional and exits `2` (the `store_true` flag takes no value)

#### Scenario: yasetnode argv parameter reads sys.argv when None
- **WHEN** `manage_node()` is invoked with `argv=None` (the console_script default)
- **THEN** `parser.parse_args(None)` is called, which reads `sys.argv[1:]`

#### Scenario: yasetnode argv parameter accepts explicit list
- **WHEN** `manage_node(["10.0.0.1", "--remove-hard"])` is invoked
- **THEN** `parser.parse_args(["10.0.0.1", "--remove-hard"])` is called, with no reading of `sys.argv`

### Requirement: yasetnode exit code contract

`manage_node()` SHALL follow the `0`/`1`/`2` exit-code contract:
- `0` on success: add completed; remove-hard completed; remove-soft
  completed (whether the node was disabled or removed).
- `1` on runtime failure: host already in DB (on the add path); host NOT in
  DB (on either remove path); SSH connection or setup failure; DB error;
  config parse error; or any unexpected exception caught at the top level.
  The error SHALL be printed to stderr as `Error: <error>` and the process
  SHALL exit `1`.
- `2` on argparse error (argparse default — missing host, malformed host
  grammar via `type=_parse_host_spec`, port out of range, negative ncpus,
  `--remove-soft --remove-hard`, `--skip-setup --remove-*`, unknown flag).

`manage_node()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body.

#### Scenario: yasetnode add exits 0 on success
- **WHEN** `yasetnode 10.0.0.1` is invoked and the add completes without exception
- **THEN** the success messages are printed to stdout and the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yasetnode add exits 1 when host already in DB
- **WHEN** `yasetnode 10.0.0.1` is invoked and `uow.nodes.get("10.0.0.1")` returns an existing node
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode remove exits 1 when host NOT in DB
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked and `uow.nodes.get("10.0.0.1")` returns `None`
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode exits 1 on SSH connect failure
- **WHEN** `yasetnode 10.0.0.1` is invoked and `gateway.connect(...)` raises an SSH connection error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode exits 1 on DB error
- **WHEN** `uow.nodes.add(...)`, `uow.nodes.remove(...)`, `uow.nodes.disable(...)`, `uow.tasks.update_status(...)`, or `uow.tasks.list_ids_by_ip_and_status(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode exits 1 on config parse error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode --help exits 0
- **WHEN** `yasetnode --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yasetnode remove-hard exits 0 on success
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked against an existing node and the hard-remove completes without exception
- **THEN** the per-task and removal success messages are printed to stdout and the process exits `0`

#### Scenario: yasetnode remove-soft exits 0 on success
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against an existing node and the soft-remove completes without exception (whether the node had running tasks or not)
- **THEN** the success messages are printed to stdout and the process exits `0`

### Requirement: yasetnode output channels and verbatim success messages

On success, `manage_node()` SHALL print the following messages verbatim to
**stdout**, and SHALL emit them **after** `await uow.commit()` succeeds (so
the observable output matches the committed DB state):

| path                        | message (verbatim)                                                      |
| --------------------------- | ----------------------------------------------------------------------- |
| add, before setup           | `Setup host...`                                                          |
| add, after commit           | `Added host to yascheduler: {host}:{port}`                                |
| remove-hard, per task       | `An associated task {task_id} at {host} is now marked done!`              |
| remove-hard, after commit   | `Removed host from yascheduler: {host}`                                   |
| remove-soft, has tasks      | `A task associated, prevent from assigning the new tasks`                 |
|                              | `Prevented from assigning the new tasks: {host}`                          |
| remove-soft, no tasks       | `No tasks associated, remove node immediately`                             |
| remove-soft, no tasks, after commit | `Removed host from yascheduler: {host}`                            |

`{host}` is the parsed `HostSpec.host` (the cleaned host string, not the
raw input); `{port}` is the resolved `port` int; `{task_id}` is each
RUNNING task id marked DONE by the hard-remove.

On failure, `manage_node()` SHALL print `Error: <message>` to **stderr**
via `raise` + top-level `except Exception as e: print(f"Error: {e}",
file=sys.stderr); sys.exit(1)`. Failure messages SHALL NOT appear on
stdout.

#### Scenario: yasetnode add success prints verbatim messages to stdout after commit
- **WHEN** `yasetnode 10.0.0.1` succeeds (without `--skip-setup`)
- **THEN** stdout contains `Setup host...` (a progress indicator printed before `setup_node`, not a success confirmation) and `Added host to yascheduler: 10.0.0.1:22` (the confirmation, emitted after `uow.commit()` returns), in that order

#### Scenario: yasetnode add with --skip-setup omits Setup host message
- **WHEN** `yasetnode 10.0.0.1 --skip-setup` succeeds
- **THEN** stdout does NOT contain `Setup host...` (the setup step was skipped) and contains `Added host to yascheduler: 10.0.0.1:22`

#### Scenario: yasetnode remove-hard prints per-task messages after commit
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` succeeds against a node with RUNNING task ids `[1, 2]`
- **THEN** stdout contains `An associated task 1 at 10.0.0.1 is now marked done!` and `An associated task 2 at 10.0.0.1 is now marked done!` and `Removed host from yascheduler: 10.0.0.1`, all emitted after `uow.commit()` returns

#### Scenario: yasetnode remove-soft with tasks prints disable messages
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` succeeds against a node with at least one RUNNING task
- **THEN** stdout contains `A task associated, prevent from assigning the new tasks` and `Prevented from assigning the new tasks: 10.0.0.1`

#### Scenario: yasetnode remove-soft without tasks prints remove messages
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` succeeds against a node with no RUNNING tasks
- **THEN** stdout contains `No tasks associated, remove node immediately` and `Removed host from yascheduler: 10.0.0.1`

#### Scenario: yasetnode failure prints Error to stderr not stdout
- **WHEN** `yasetnode 10.0.0.1` fails (host already in DB, SSH failure, DB error, or any exception)
- **THEN** stderr contains `Error: ...`, stdout is empty of success messages, and the process exits `1`

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL construct a single
`SSHMachineGateway` at the top of the function (before opening any UoW) and
pass it as a parameter to the add helper. The add helper `_add_node(deps,
gateway, spec, config, skip_setup)` SHALL open its own UoW via
`deps.uow_factory()` and wrap the sequence `gateway.connect(...)` → optional
`gateway.setup_node(...)` → `uow.nodes.add(...)` → `uow.commit()` in
`try/finally`, with `await gateway.disconnect(host)` in the `finally` block.
The disconnect SHALL run on both the success path and any failure path (SSH
failure, setup failure, DB failure), so the SSH connection is released
rather than leaking until timeout.

The gateway SHALL be instantiated once per invocation; the helper SHALL
NOT construct its own gateway. This makes the add helper unit-testable via
direct mock injection (no `patch.object` on the gateway class).

#### Scenario: yasetnode constructs gateway once and passes to add helper
- **WHEN** `yasetnode 10.0.0.1` is invoked on the add path
- **THEN** exactly one `SSHMachineGateway()` is constructed (at the top of `manage_node`), and that instance is passed as a parameter to the add helper

#### Scenario: yasetnode disconnects gateway on add success
- **WHEN** `yasetnode 10.0.0.1` succeeds on the add path
- **THEN** `gateway.disconnect(host)` is called after `uow.commit()` (inside `_add_node`'s own UoW, the `try/finally` ensures disconnect runs)

#### Scenario: yasetnode disconnects gateway when setup_node raises
- **WHEN** `gateway.setup_node(...)` raises an exception after `gateway.connect(...)` succeeded
- **THEN** `gateway.disconnect(host)` is still called (the `finally` block runs), the exception propagates to the top-level handler which prints `Error: ...` to stderr and exits `1`

#### Scenario: yasetnode disconnects gateway when nodes.add raises
- **WHEN** `uow.nodes.add(...)` raises a DB error after `gateway.connect(...)` succeeded
- **THEN** `gateway.disconnect(host)` is still called (the `finally` block runs), the exception propagates to the top-level handler which prints `Error: ...` to stderr and exits `1`

#### Scenario: yasetnode skips setup when --skip-setup given
- **WHEN** `yasetnode 10.0.0.1 --skip-setup` succeeds on the add path
- **THEN** `gateway.setup_node(...)` is NOT called, but `gateway.connect(...)` and `gateway.disconnect(host)` ARE called, and `uow.nodes.add(...)` IS called

### Requirement: yasetnode dispatches add and remove paths

After argparse succeeds and the `HostSpec` is parsed, `manage_node()` SHALL
open a short, read-only validation UoW via
`async with deps.uow_factory() as uow:`, read
`already_there = await uow.nodes.get(spec.host) is not None`, and close it
(without commit — nothing was mutated). It SHALL then dispatch to exactly one
helper, each of which opens its OWN UoW via `deps.uow_factory()` to perform
its mutations, commit, and print:

- If `already_there` and no remove flag: raise `ValueError` → top-level
  handler prints `Error: ...` to stderr, exits `1`. (Adding an existing
  node is an operator error; disabled nodes are re-enabled via the
  remove + add cycle, not by re-adding.)
- If NOT `already_there` and a remove flag is set: raise `ValueError` →
  top-level handler prints `Error: ...` to stderr, exits `1`.
- If `--remove-hard`: call `_remove_node_hard(deps, spec)` — inside its own
  UoW, list RUNNING task ids for the host, mark each DONE, remove the node,
  commit.
- If `--remove-soft`: call `_remove_node_soft(deps, spec)` — inside its own
  UoW, if RUNNING tasks exist, disable the node; else remove the node;
  commit.
- Otherwise (add): resolve `username = spec.username or
  config.remote.username`, call `_add_node(deps, gateway, spec, config,
  skip_setup)` — inside its own UoW, connect + optional setup +
  `uow.nodes.add(...)`, commit.

A TOCTOU window exists between closing the validation UoW and opening the
dispatch helper's UoW; for a single-operator CLI this is accepted (see design
D18). Failure modes are benign and non-corrupting: add-on-already-present →
unique-constraint / helper re-check → exit 1; remove-on-just-removed →
no-op / not-found → exit 1.

The `Node` record constructed on the add path SHALL use
`ip=spec.host`, `port=spec.port`, `username=<resolved>`,
`ncpus=(spec.ncpus if spec.ncpus is not None else 0)`, `enabled=True`.

#### Scenario: yasetnode add constructs Node with resolved username and default ncpus
- **WHEN** `yasetnode 10.0.0.1` is invoked and `config.remote.username` is `"root"`
- **THEN** `uow.nodes.add(...)` is called (inside `_add_node`'s own UoW) with a `Node(ip="10.0.0.1", port=22, username="root", ncpus=0, enabled=True)`

#### Scenario: yasetnode add respects explicit user@ override
- **WHEN** `yasetnode deploy@10.0.0.1` is invoked and `config.remote.username` is `"root"`
- **THEN** `uow.nodes.add(...)` is called (inside `_add_node`'s own UoW) with a `Node(ip="10.0.0.1", port=22, username="deploy", ncpus=0, enabled=True)` (the `user@` prefix overrides the config default)

#### Scenario: yasetnode add with explicit ncpus
- **WHEN** `yasetnode 10.0.0.1~4` is invoked
- **THEN** `uow.nodes.add(...)` is called (inside `_add_node`'s own UoW) with a `Node(ip="10.0.0.1", port=22, username=<resolved>, ncpus=4, enabled=True)`

#### Scenario: yasetnode remove-hard marks running tasks DONE then removes node
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked against a node with RUNNING task ids `[1, 2]`
- **THEN** inside `_remove_node_hard`'s own UoW, `uow.tasks.update_status(1, TaskStatus.DONE)` and `uow.tasks.update_status(2, TaskStatus.DONE)` are called, then `uow.nodes.remove("10.0.0.1")` is called, then `uow.commit()` is called

#### Scenario: yasetnode remove-soft with tasks disables node
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against a node with at least one RUNNING task
- **THEN** inside `_remove_node_soft`'s own UoW, `uow.nodes.disable("10.0.0.1")` is called, `uow.nodes.remove(...)` is NOT called, and `uow.commit()` is called

#### Scenario: yasetnode remove-soft without tasks removes node
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against a node with no RUNNING tasks
- **THEN** inside `_remove_node_soft`'s own UoW, `uow.nodes.remove("10.0.0.1")` is called, `uow.nodes.disable(...)` is NOT called, and `uow.commit()` is called

#### Scenario: yasetnode logging captures warnings
- **WHEN** `manage_node()` is invoked
- **THEN** `logging.captureWarnings(True)` is called and the root logger level is set to `WARN` (so config warnings from `warn_unknown_fields` reach the operator)

#### Scenario: yasetnode helpers return None
- **WHEN** any of `_add_node`, `_remove_node_hard`, `_remove_node_soft` is called
- **THEN** it returns `None` (the function signals outcomes via side effects, exceptions, and exit codes, not via return values; the previous `bool` return signaling is removed)

### Requirement: yasetnode module path and GRACE-lite markup

The `yasetnode` command SHALL be implemented as `manage_node()` in
`yascheduler/entrypoints/cli/manage_node.py`, an async function decorated
with `@to_sync` (so the console_script invokes a synchronous callable).
The module SHALL carry fresh GRACE-lite markup (`MODULE_CONTRACT`,
`MODULE_MAP`, `CHANGE_SUMMARY`, function contracts, and block anchors)
versioned `1.0.0`. The stale `# FIXME: split adapter and application
layer` comment from the old `infra/cli/manage_node.py` SHALL NOT be carried
to the new file. The logic SHALL be split into private pure functions:
`_parse_host_spec(s)`, `_parse_node_args(argv)`, `_remove_node_hard(deps,
spec)`, `_remove_node_soft(deps, spec)`, `_add_node(deps, gateway, spec,
config, skip_setup)`, and the `HostSpec` frozen dataclass. Each mutate
helper opens its own UoW via `deps.uow_factory()` (see the dispatch
requirement); the validation read uses a separate read-only UoW closed
before dispatch. No use case SHALL be extracted into `application/` — YAGNI
(no second consumer; the daemon-side node lifecycle is owned by the
orchestrator).

#### Scenario: yasetnode is to_sync-decorated
- **WHEN** the `manage_node` callable in `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** it is decorated with `@to_sync` (the `__wrapped__` attribute points to an async function)

#### Scenario: yasetnode module has fresh GRACE-lite markup
- **WHEN** `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** it contains `START_MODULE_CONTRACT`/`END_MODULE_CONTRACT`, `START_MODULE_MAP`/`END_MODULE_MAP`, `START_CHANGE_SUMMARY`/`END_CHANGE_SUMMARY`, function-level `START_CONTRACT:`/`END_CONTRACT:` blocks, and `START_BLOCK_`/`END_BLOCK_` anchors, versioned `1.0.0`

#### Scenario: yasetnode module drops stale FIXME
- **WHEN** `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** the comment `# FIXME: split adapter and application layer` does NOT appear (the framing was stale at the new home and the function-level split resolves the separation)

#### Scenario: yasetnode does not extract an application use case
- **WHEN** the implementation is inspected
- **THEN** no `application/manage_node.py` or equivalent use-case module is created; all orchestration lives in the CLI module's private helpers

### Requirement: yastatus queries task status

The `yastatus` command SHALL query and display task status, optionally with
remote machine output (verbose mode) and convergence info. The command is
implemented as `check_status()` in
`yascheduler/entrypoints/cli/check_status.py`, an async function decorated
with `@to_sync` (so the console_script invokes a synchronous callable). It
SHALL accept an `argv: list[str] | None = None` parameter for testability
(`None` reads `sys.argv`, the argparse convention; tests pass an explicit
list). It SHALL obtain `Config` via `Config.from_config_parser`, build
`CLIDeps` via `make_cli_deps(config)` once, and open exactly one short UoW
for the query phase (fetching `tasks`, and additionally `nodes_by_ip` only
when the selected renderer needs node fields — i.e. `-v` or `--json`). The
UoW SHALL be closed before any SSH work begins (no DB connection held during
SSH).

The default query (no `-j`) SHALL call
`uow.tasks.list_by_status({TaskStatus.RUNNING, TaskStatus.TO_DO})` (DONE
excluded — the AiiDA plugin relies on this default). With `-j ID...`, the
query SHALL call `uow.tasks.list_by_jobs(job_ids=args.jobs)` (returns tasks
of any status; the closed `TaskStatus` enum guarantees all returned statuses
are valid AiiDA states).

The logic SHALL be split into private pure functions: `_parse_status_args`,
`_query_tasks`, `_render_default` (AiiDA contract), `_render_info`,
`_render_json`, `_render_view`, `_resolve_conn_params` (connection-params
bugfix helper mirroring `orchestrator._connect_machine_consumer:209-214`),
`_display_remote_output`, `_download_convergence_snippet`, `_parse_convergence`.

#### Scenario: yastatus default invocation lists RUNNING and TO_DO tasks
- **WHEN** `yastatus` is invoked with no flags
- **THEN** `uow.tasks.list_by_status({RUNNING, TO_DO})` is called, DONE tasks are excluded, and the default renderer prints one line per task

#### Scenario: yastatus -j filters by job ids
- **WHEN** `yastatus -j 1 2` is invoked
- **THEN** `uow.tasks.list_by_jobs(job_ids=["1", "2"])` is called and the result is rendered (tasks of any status, including DONE, are returned)

#### Scenario: yastatus reads config and builds deps once
- **WHEN** `check_status()` is invoked
- **THEN** `Config.from_config_parser(CONFIG_FILE)` is called exactly once and `make_cli_deps(config)` is called exactly once (the previous implementation called it twice)

#### Scenario: yastatus closes the UoW before SSH work
- **WHEN** `yastatus -v` is invoked and the render phase performs SSH operations (connect, tail OUTPUT, SFTP download)
- **THEN** the query-phase UoW is closed before any SSH operation begins (no DB connection is held during SSH)

#### Scenario: yastatus -v and --json fetch nodes_by_ip
- **WHEN** `yastatus -v` or `yastatus --json` is invoked and tasks have allocated IPs
- **THEN** `uow.nodes.get_by_ips([t.allocated_ip for t in tasks if t.allocated_ip])` is called within the query-phase UoW

#### Scenario: yastatus default and -i skip the nodes lookup
- **WHEN** `yastatus` (default) or `yastatus -i` is invoked
- **THEN** `uow.nodes.get_by_ips` is NOT called (the default and info renderers use only task fields; the nodes lookup is conditional on the renderer)

### Requirement: yastatus default output format (AiiDA compatibility)

The default renderer of `yastatus` SHALL emit exactly one line per task in
the form `<task_id><whitespace><STATUS_NAME>`, used when none of
`-v`/`-i`/`--json` is given. `<task_id>` is the integer task id and
`<STATUS_NAME>` is the `TaskStatus` enum member name (`TO_DO`, `RUNNING`,
or `DONE`). This format SHALL be preserved exactly because the AiiDA
scheduler plugin (`entrypoints/aiida_plugin.py:_parse_joblist_output`) parses
the output via `for job_id, status in job.split()` (requiring exactly 2
whitespace-separated elements per line) and maps `status` through
`_MAP_STATUS_YASCHEDULER` (whose keys are `{TO_DO, RUNNING, DONE}`).

`yastatus` SHALL NOT add a header line, a footer line, a summary count, or
any other decoration to the default output. The default renderer
(`_render_default`) SHALL be `print(f"{task.task_id}   {task.status.name}")`
per task (moved as-is from the previous `_print_status_default`). The exact
whitespace run between the two fields is not contractual (the plugin's
`.split()` tolerates any run), but the 2-element shape and the status-name
set are.

The `-v`, `-i`, `-o`, and `--json` modes are NOT used by the AiiDA plugin
(it only invokes `yastatus` or `yastatus --jobs ...`); their output is free
to change. `--json` is therefore safe to add (opt-in; AiiDA never passes it).

#### Scenario: yastatus default output is two-column
- **WHEN** `yastatus` is invoked against tasks with ids 1 (RUNNING), 2 (TO_DO), 3 (DONE)
- **THEN** the default invocation (no `-j`) excludes DONE and prints exactly `1   RUNNING` and `2   TO_DO` (one line per RUNNING/TO_DO task, in the order returned by `list_by_status`)

#### Scenario: yastatus default output has no header or decoration
- **WHEN** `yastatus` is invoked
- **THEN** the first line of stdout is a task row, not a header; no summary, count, or banner appears

#### Scenario: yastatus -j includes DONE tasks in default format
- **WHEN** `yastatus -j 3` is invoked and task 3 has status DONE
- **THEN** the default renderer prints `3   DONE` (DONE is a valid AiiDA state and is included because `-j` queries by id, not by status)

#### Scenario: AiiDA plugin parses yastatus default output
- **WHEN** the default renderer's stdout is parsed with the AiiDA plugin's exact logic `[job.split() for job in stdout.split("\n") if job]` and the resulting pairs are unpacked `for job_id, status in pairs`
- **THEN** every line yields exactly 2 elements and every `status` is a key of `_MAP_STATUS_YASCHEDULER` (`TO_DO`, `RUNNING`, or `DONE`) — no `ValueError`, no `KeyError`

#### Scenario: AiiDA plugin is unchanged
- **WHEN** `entrypoints/aiida_plugin.py` is inspected after this change
- **THEN** `_get_joblist_command` still returns `yastatus` or `yastatus --jobs <ids>` and `_parse_joblist_output` still does `for job_id, status in job.split()` with `_MAP_STATUS_YASCHEDULER` (the AiiDA contract is not touched)

### Requirement: yastatus parses flags via argparse

`check_status()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yastatus",
description="Show status of tasks")`. The flag matrix SHALL be:

- `-j/--jobs` (`nargs="*"`, `default=None`): orthogonal filter; composes with
  any renderer. With no `-j`, the default query `list_by_status({RUNNING,
  TO_DO})` is used; with `-j ID...`, `list_by_jobs(job_ids=ID...)` is used.
- A `mutually_exclusive_group` containing exactly:
  - `-v/--view` (`action="store_true"`): verbose renderer (tail remote OUTPUT,
    optional convergence).
  - `-i/--info` (`action="store_true"`): tab-separated one-line-per-task
    renderer.
  - `--json` (`action="store_true"`): JSON renderer with raw domain values.
  At most one renderer is selected; none means the default AiiDA-compatible
  renderer (`_render_default`).
- `-o/--convergence` (`action="store_true"`): NOT in the mutex group (it
  modifies `-v`, so `-o -v` must remain valid). A body-check after
  `parse_args` SHALL reject `-o` without `-v` via
  `parser.error("--convergence requires --view")` (exit 2).

`--help` shows the standard argparse help screen (argparse default). The
parser SHALL use `action="store_true"` for all boolean flags (NOT the
previous non-idiomatic `nargs="?", type=bool, const=True` shape).

#### Scenario: yastatus --help shows argparse usage
- **WHEN** `yastatus --help` is invoked
- **THEN** argparse prints the standard help screen showing `prog="yastatus"` and the flags `-j/--jobs`, `-v/--view`, `-i/--info`, `-o/--convergence`, `--json` with their descriptions, and exits `0`

#### Scenario: yastatus -v -i mutually exclusive
- **WHEN** `yastatus -v -i` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yastatus --json -v mutually exclusive
- **WHEN** `yastatus --json -v` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yastatus --json -i mutually exclusive
- **WHEN** `yastatus --json -i` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yastatus -o without -v exits 2
- **WHEN** `yastatus -o` is invoked (without `-v`)
- **THEN** the body-check calls `parser.error("--convergence requires --view")`, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yastatus -o -v is valid
- **WHEN** `yastatus -v -o` is invoked
- **THEN** argparse accepts the combination (both flags set), the body-check passes (because `args.view` is True), and the verbose renderer runs with convergence fetching enabled

#### Scenario: yastatus with an unknown flag exits 2
- **WHEN** `yastatus --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yastatus -j composes with any renderer
- **WHEN** `yastatus -j 1 2 --json` is invoked
- **THEN** `list_by_jobs(job_ids=["1", "2"])` is called and the JSON renderer prints the result (the `-j` filter composes orthogonally with any renderer in the mutex group)

#### Scenario: yastatus prog is yastatus in help and errors
- **WHEN** `yastatus --help` or any argparse error is shown
- **THEN** the program name displayed is `yastatus` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yastatus exit code contract

`check_status()` SHALL follow the `0`/`1`/`2` exit-code contract:

- `0` on success: the function returns normally after rendering (default,
  `-i`, `--json`, or `-v`); the process exits `0`.
- `1` on runtime failure: DB error, config parse error, SSH connection
  failure, SFTP failure, convergence-parse failure, or any unexpected
  exception caught at the top level. The error SHALL be printed to stderr as
  `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error: argparse default (unknown flag, mutex group
  violation) or `parser.error("--convergence requires --view")`.

`check_status()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body. The `@to_sync`
decorator propagates `SystemExit` correctly (it is a `BaseException`;
`asyncio.run` does not wrap it).

#### Scenario: yastatus exits 0 on success
- **WHEN** `yastatus` is invoked and the query + render complete without exception
- **THEN** the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yastatus exits 1 on DB error
- **WHEN** `uow.tasks.list_by_status(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus exits 1 on config error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus exits 1 on SSH connection failure
- **WHEN** `yastatus -v` is invoked and `gateway.connect(...)` raises `MachineConnectionError`
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus exits 1 on unexpected exception
- **WHEN** any other unexpected exception is raised during execution
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus --help exits 0
- **WHEN** `yastatus --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yastatus --bogus exits 2
- **WHEN** `yastatus --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yastatus -o without -v exits 2
- **WHEN** `yastatus -o` is invoked (without `-v`)
- **THEN** the body-check calls `parser.error(...)` and the process exits `2`

### Requirement: yastatus --json output format

When `--json` is given, `yastatus` SHALL emit
`json.dumps(list_of_objects)` where each object represents one task with raw
domain values (NO display transformations — no `MAX`, no `-`, no banner).
The object schema SHALL be exactly these 9 fields:

```
{"task_id": int, "status": str, "label": str, "allocated_ip": str | null,
 "port": int | null, "cloud": str | null, "engine": str,
 "local_folder": str | null, "remote_folder": str | null}
```

- `task_id`: the raw `task.task_id` int.
- `status`: the `task.status.name` string (`"TO_DO"`, `"RUNNING"`, or
  `"DONE"`) — NOT an int, NOT a display token.
- `label`: the raw `task.label` string.
- `allocated_ip`: the raw `task.allocated_ip` string, or `null` when the
  task has no allocated IP (typically `TO_DO`).
- `port`: the raw `node.port` int (looked up via `nodes_by_ip`), or `null`
  when the task has no allocated IP. `22` stays `22` (no display
  transformation).
- `cloud`: the raw `node.cloud` string (looked up via `nodes_by_ip`), or
  `null` for static nodes / unallocated tasks.
- `engine`: the raw `task.context.engine` string (always present —
  `TaskContext.engine` is a required field).
- `local_folder`: the raw `task.context.local_folder` string, or `null`.
- `remote_folder`: the raw `task.context.remote_folder` string, or `null`.

One object per task, in the order returned by the query
(`list_by_status` or `list_by_jobs`). `--json` SHALL be in the
`mutually_exclusive_group` with `-v` and `-i`; convergence (`-o`) is NOT
part of `--json` (mixing machine-readable JSON with ephemeral scientific
output is excluded by design).

#### Scenario: yastatus --json emits a list of objects
- **WHEN** `yastatus --json` is invoked against a non-empty task set
- **THEN** the output is valid JSON parseable as a list of objects, one per task, in query order

#### Scenario: yastatus --json uses raw status name
- **WHEN** a task has status `RUNNING`
- **THEN** the JSON object's `status` field is the string `"RUNNING"` (NOT `1`, NOT `"running"`)

#### Scenario: yastatus --json uses raw port
- **WHEN** a task is allocated to a node with `port=22`
- **THEN** the JSON object's `port` field is `22` (NOT `null` or `"-"`)

#### Scenario: yastatus --json uses raw cloud
- **WHEN** a task is allocated to a node with `cloud="hetzner"`
- **THEN** the JSON object's `cloud` field is `"hetzner"`; for a static node (`cloud=None`) it is `null`

#### Scenario: yastatus --json TO_DO task has null placement fields
- **WHEN** a `TO_DO` task (no `allocated_ip`) is rendered via `--json`
- **THEN** the JSON object's `allocated_ip`, `port`, and `cloud` fields are all `null` (the task has not been placed on a node yet)

#### Scenario: yastatus --json engine always present
- **WHEN** a task with `context.engine="g09"` is rendered via `--json`
- **THEN** the JSON object's `engine` field is `"g09"` (never null — `TaskContext.engine` is required)

#### Scenario: yastatus --json empty result is empty list
- **WHEN** `yastatus --json` is invoked and the query returns no tasks
- **THEN** the output is `[]` and the process exits `0`

#### Scenario: yastatus --json composes with -j
- **WHEN** `yastatus -j 1 2 --json` is invoked
- **THEN** `list_by_jobs(job_ids=["1", "2"])` is called and the JSON renderer prints the result (the `-j` filter composes with `--json`)

### Requirement: yastatus view mode connects via SSH with correct node params

When `-v` (or `-v -o`) is given, `yastatus` SHALL, for each RUNNING task with
an allocated IP, connect to the remote machine via `SSHMachineGateway`,
display a tail of the remote `OUTPUT` file, optionally download and parse a
CRYSTAL convergence snippet (when `-o` is also given), and disconnect. The
SSH connection parameters SHALL be resolved by a private
`_resolve_conn_params(node, config)` helper that mirrors
`orchestrator._connect_machine_consumer:209-214`:

- `username` SHALL be `node.username` (NOT a cloud username — the previous
  implementation's `for c in config.clouds: ssh_user = c.username` took the
  last cloud's username, which was a bug).
- `port` SHALL be `node.port` (the previous implementation always used the
  gateway default of 22).
- `jump_host` and `jump_username` SHALL come from the cloud whose `prefix
  == node.cloud` (if any such cloud has both set), falling back to
  `config.remote.jump_host` / `config.remote.jump_username` for static nodes
  or clouds without a jump host. The previous implementation never passed
  jump-host parameters, so `yastatus -v` on a cloud node behind a jump host
  was functionally broken.

All four parameters SHALL be passed to `gateway.connect(...)`. The
convergence snippet SHALL be stored in a `tempfile`-based file (NOT the
previous fixed-name `local_calc_snippet.tmp`) and cleaned up in a
`try/finally` block so it is removed even when `_render_view` raises.

#### Scenario: yastatus -v uses node.username not cloud username
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `username="yascheduler"` and `cloud="hetzner"`, and the `hetzner` cloud config has `username="hcloud-user"`
- **THEN** `gateway.connect(...)` is called with `username="yascheduler"` (the node's username, NOT the cloud's)

#### Scenario: yastatus -v passes node.port
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `port=2222`
- **THEN** `gateway.connect(...)` is called with `port=2222` (NOT the gateway default of 22)

#### Scenario: yastatus -v resolves jump host from matching cloud
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `cloud="hetzner"`, and the `hetzner` cloud config has `jump_host="jump.example.com"` and `jump_username="jumper"`
- **THEN** `gateway.connect(...)` is called with `jump_host="jump.example.com"` and `jump_username="jumper"`

#### Scenario: yastatus -v falls back to config.remote for static nodes
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a static node (`cloud=None`), and `config.remote.jump_host` is set
- **THEN** `gateway.connect(...)` is called with `jump_host=config.remote.jump_host` and `jump_username=config.remote.jump_username`

#### Scenario: yastatus -v -o uses a tempfile for the convergence snippet
- **WHEN** `yastatus -v -o` is invoked
- **THEN** the convergence snippet is written to a `tempfile.NamedTemporaryFile`/`mkstemp`-created file with a unique name (NOT the fixed `local_calc_snippet.tmp`), so concurrent invocations do not collide

#### Scenario: yastatus cleans up the snippet on exception
- **WHEN** `yastatus -v -o` is invoked and `_render_view` raises an exception during SSH or parse
- **THEN** the convergence snippet file is removed by the `try/finally` block (the previous implementation skipped cleanup on the exception path)

