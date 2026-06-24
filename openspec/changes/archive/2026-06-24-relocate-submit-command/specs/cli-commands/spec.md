## MODIFIED Requirements

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