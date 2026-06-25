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

## ADDED Requirements

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
