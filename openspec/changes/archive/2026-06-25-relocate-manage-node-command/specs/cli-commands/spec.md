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
entrypoint that adds, soft-removes, or hard-removes nodes via a UoW (and
via `SSHMachineGateway` for the add path's optional remote setup); it lives
in `entrypoints/cli/`. The other 2 CLI commands (`check_status`,
`daemonize`) remain in `infra/cli/`.

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

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW
- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(CONFIG_FILE)` is called, `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineGateway` is constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened via `async with deps.uow_factory() as uow:` solely to read `already_there = await uow.nodes.get(spec.host) is not None` (it is closed without commit — nothing was mutated), and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the gateway is passed to the add helper.

### Requirement: Entry points updated

The system SHALL update pyproject.toml console_scripts to point to
`yascheduler.entrypoints.cli.init` for `yainit`, to
`yascheduler.entrypoints.cli.show_nodes` for `yanodes`, to
`yascheduler.entrypoints.cli.submit` for `yasubmit`, and to
`yascheduler.entrypoints.cli.manage_node` for `yasetnode`. The other 2 CLI
commands (`check_status`, `daemonize`) continue to point at
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

#### Scenario: yasetnode resolves to the new location
- **WHEN** `yasetnode` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.manage_node:manage_node` is invoked

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

## ADDED Requirements

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
