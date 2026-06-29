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
`SSHMachineRepository` + `SSHMachineOperations` for the add path's optional
remote setup); it lives in `entrypoints/cli/`. The `yastatus` command is an
execution-query entrypoint that reads tasks (and, in verbose mode, remote
machine output) via `CLIDeps` and the SSH repository/operations; it lives in
`entrypoints/cli/`. The `yascheduler` command (`daemonize` in
`entrypoints/cli/daemonize.py`) starts the daemon via `make_daemon()` and
`orchestrator.start()`, delegating the async runtime and signal handling to
`daemon_common.run_daemon` (see the `daemon-common` capability); it lives in
`entrypoints/cli/`. All six CLI commands now live in `entrypoints/cli/`;
`yascheduler/infra/cli/` is liquidated.

All six CLI commands and the three daemon launchers (`daemonize`,
`daemon_systemd`, `daemon_sysv`) SHALL accept `--config PATH` (default
`CONFIG_FILE`, validated by `existing_path` — a missing config file exits 2)
and `--log-level` (default `WARNING` for `yainit`/`yanodes`/`yasubmit`/
`yasetnode`/`yastatus`; default `INFO` for the three daemon launchers), via
the shared `args.py` helpers (see the `cli-args` capability). The five
non-daemon CLI commands SHALL replace their hardcoded `logging.WARN` (or
unconfigured root logger) with `logging.getLevelName(args.log_level)` applied
to the root logger. The three daemon launchers SHALL additionally accept
`--log-file PATH` (default `None` → stderr for `daemonize` and
`daemon_systemd`; default `LOG_FILE` for `daemon_sysv`) via
`add_log_file_arg`.

The five non-daemon CLI commands (`init`, `show_nodes`, `submit`,
`manage_node`, `check_status`) SHALL be synchronous `def` entry points that
call `asyncio.run(_<name>_async(argv))` on a private `async def` coroutine,
NOT `@to_sync`-decorated async functions. The thread-offload branch of
`to_sync` never fires for CLI entry points (no async caller invokes them);
`asyncio.run` is explicit and equivalent. `to_sync` stays in
`yascheduler/shared/async_utils.py` for `client.py`'s legitimate
cross-context use. Each entry point SHALL accept an `argv: list[str] | None =
None` parameter (None reads `sys.argv`) for testability.

#### Scenario: yasubmit calls SubmitTask
- **WHEN** yasubmit is invoked with valid arguments
- **THEN** make_cli_deps() is called, SubmitTask use case is invoked via CLIDeps.submit, task_id is printed to stdout

#### Scenario: yastatus queries tasks via CLIDeps
- **WHEN** yastatus is invoked (default mode, `-i`, `--json`, or `-v`)
- **THEN** make_cli_deps() is called, tasks are read via `uow.tasks.list_by_status({RUNNING, TO_DO})` (default) or `uow.tasks.list_by_jobs(job_ids)` (with `-j`), and the selected renderer prints the result

#### Scenario: yascheduler starts daemon via orchestrator
- **WHEN** yascheduler is invoked
- **THEN** `make_daemon(config, logger)` is called via `daemon_common.run_daemon` and `orchestrator.start()` is awaited inside `asyncio.run(run_daemon(config, logger))`

#### Scenario: yainit is a bootstrap entrypoint without DI
- **WHEN** `yainit` is invoked (with any combination of `--schema` / `--daemon` / no flags)
- **THEN** `init()` performs infrastructure setup (service install and/or schema apply) directly via `apply_schema(config.db)` and service-template file writes, without calling `make_cli_deps` or any use case

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW
- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(args.config)` is called (NOT the hardcoded `CONFIG_FILE`), `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineRepository` and an `SSHMachineOperations` (bound to that repository) are constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened via `async with deps.uow_factory() as uow:` solely to read `already_there = await uow.nodes.get(spec.host) is not None` (it is closed without commit — nothing was mutated), and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the repository and operations are passed to the add helper.

#### Scenario: all six CLI commands accept --config
- **WHEN** any of `yascheduler`, `yainit`, `yanodes`, `yasubmit`, `yasetnode`, `yastatus` is invoked with `--config /path/to/yascheduler.conf`
- **THEN** `Config.from_config_parser("/path/to/yascheduler.conf")` is called instead of the hardcoded `CONFIG_FILE`

#### Scenario: all six CLI commands accept --log-level
- **WHEN** any of `yascheduler`, `yainit`, `yanodes`, `yasubmit`, `yasetnode`, `yastatus` is invoked with `--log-level DEBUG`
- **THEN** the root logger is configured at `DEBUG` (via `logging.getLevelName("DEBUG")` for the five CLI commands, or via `configure_logger(..., level=logging.DEBUG)` for the three daemon launchers)

#### Scenario: missing config file exits 2
- **WHEN** any CLI command or daemon launcher is invoked with `--config /nonexistent.conf`
- **THEN** argparse prints `not a file: /nonexistent.conf` to stderr and exits 2 (via the `existing_path` validator in `args.py`)

#### Scenario: invalid log level exits 2
- **WHEN** any CLI command or daemon launcher is invoked with `--log-level WARN`
- **THEN** argparse rejects it with exit 2 (only `WARNING` is accepted, not the `WARN` alias)

#### Scenario: five CLI commands use asyncio.run, not @to_sync
- **WHEN** `submit`, `show_nodes`, `manage_node`, or `check_status` is inspected
- **THEN** the entry point is a synchronous `def f(argv: list[str] | None = None)` that calls `asyncio.run(_f_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

#### Scenario: yascheduler console_script points at entrypoints/cli/daemonize
- **WHEN** the `yascheduler` console_script in `pyproject.toml` is inspected
- **THEN** it points at `yascheduler.entrypoints.cli.daemonize:daemonize` (NOT `yascheduler.infra.cli.daemonize:daemonize`)

#### Scenario: infra/cli/ is liquidated
- **WHEN** the `yascheduler/infra/cli/` directory is inspected
- **THEN** it does not exist (both `daemonize.py` and `__init__.py` are deleted)

### Requirement: yasubmit parses AiiDA script and submits task

The `yasubmit` command SHALL parse an AiiDA script file (key=value metadata
lines), read the engine's declared input files from the current working
directory, build the task metadata, and submit a task via `CLIDeps.submit`
(which delegates to the `submit_task` use case). The command is implemented
as `submit()` in `yascheduler/entrypoints/cli/submit.py`, a synchronous
entry point that calls `asyncio.run(_submit_async(argv))` (NOT
`@to_sync`-decorated; CLI entry points have no async caller). It SHALL
accept an `argv: list[str] | None = None` parameter for testability (`None`
reads `sys.argv`, the argparse convention; tests pass an explicit list). It
SHALL obtain `Config` via `Config.from_config_parser`, build `CLIDeps` via
`make_cli_deps(config)`, parse the script into key=value pairs, validate
that an `ENGINE` key is present and known to `config.engines`, build the
metadata dict (including `local_folder`, the engine's input files, and the
webhook fields when `PARENT` is present and `config.local.webhook_url` is
set), and call `deps.submit(label, metadata, engine.name)`. The logic SHALL
be split into private pure functions: `_existing_path` (argparse type
validator), `_parse_submit_args(argv)`.

#### Scenario: yasubmit parses AiiDA script and submits task
- **WHEN** yasubmit is invoked with a valid script file path
- **THEN** the script is parsed, the engine is validated against `config.engines`, input files are read, metadata is built, and `deps.submit(...)` is called

#### Scenario: yasubmit entry point uses asyncio.run
- **WHEN** the `submit` callable in `yascheduler/entrypoints/cli/submit.py` is inspected
- **THEN** it is a synchronous `def submit(argv: list[str] | None = None)` that calls `asyncio.run(_submit_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

### Requirement: yanodes lists nodes and their running tasks

The `yanodes` command SHALL list nodes and their currently running tasks. The command is implemented as `show_nodes()` in `yascheduler/entrypoints/cli/show_nodes.py`, a synchronous entry point that calls `asyncio.run(_show_nodes_async(argv))` (NOT `@to_sync`-decorated; CLI entry points have no async caller). It SHALL accept an `argv: list[str] | None = None` parameter for testability (`None` reads `sys.argv`, the argparse convention; tests pass an explicit list). It SHALL obtain `Config` via `Config.from_config_parser`, build `CLIDeps` via `make_cli_deps(config)`, open a single UoW, read nodes via `uow.nodes.list_all()` and running tasks via `uow.tasks.list_by_status({TaskStatus.RUNNING})`, join them in memory, apply the active filters, and print the result via the selected renderer. Output row order SHALL preserve the order returned by `uow.nodes.list_all()` (no sorting). Each node SHALL produce exactly one output row (table) or one output object (JSON).

#### Scenario: yanodes entry point uses asyncio.run
- **WHEN** the `show_nodes` callable in `yascheduler/entrypoints/cli/show_nodes.py` is inspected
- **THEN** it is a synchronous `def show_nodes(argv: list[str] | None = None)` that calls `asyncio.run(_show_nodes_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL construct a single
`SSHMachineRepository` and a single `SSHMachineOperations` (bound to that
repository) at the top of the function (before opening any UoW) and pass
them as parameters to the add helper. The add helper `_add_node(deps,
repository, operations, spec, config, skip_setup)` SHALL open its own UoW
via `deps.uow_factory()` and wrap the sequence `repository.connect(...)` →
optional `operations.setup_node(session, ...)` → `uow.nodes.add(...)` →
`uow.commit()` in `try/finally`, with `await repository.disconnect(host)`
in the `finally` block. The disconnect SHALL run on both the success path
and any failure path (SSH failure, setup failure, DB failure), so the SSH
connection is released rather than leaking until timeout.

The repository and operations SHALL be instantiated once per invocation;
the helper SHALL NOT construct its own repository/operations. This makes
the add helper unit-testable via direct mock injection (no `patch.object`
on the classes).

#### Scenario: yasetnode constructs repository+operations once and passes to add helper
- **WHEN** `yasetnode 10.0.0.1` is invoked on the add path
- **THEN** exactly one `SSHMachineRepository()` and one `SSHMachineOperations(...)` are constructed (at the top of `manage_node`), and those instances are passed as parameters to the add helper

#### Scenario: yasetnode disconnects repository on add success
- **WHEN** `yasetnode 10.0.0.1` succeeds on the add path
- **THEN** `repository.disconnect(host)` is called after `uow.commit()` (inside `_add_node`'s own UoW, the `try/finally` ensures disconnect runs)

#### Scenario: yasetnode disconnects repository when setup_node raises
- **WHEN** `operations.setup_node(session, ...)` raises an exception after `repository.connect(...)` succeeded
- **THEN** `repository.disconnect(host)` is still called (the `finally` block runs), the exception propagates to the top-level handler which prints `Error: ...` to stderr and exits `1`

#### Scenario: yasetnode disconnects repository when nodes.add raises
- **WHEN** `uow.nodes.add(...)` raises a DB error after `repository.connect(...)` succeeded
- **THEN** `repository.disconnect(host)` is still called (the `finally` block runs), the exception propagates to the top-level handler which prints `Error: ...` to stderr and exits `1`

### Requirement: yasetnode module path and GRACE-lite markup

The `yasetnode` command SHALL be implemented as `manage_node()` in
`yascheduler/entrypoints/cli/manage_node.py`, a synchronous entry point
that calls `asyncio.run(_manage_node_async(argv))` (NOT `@to_sync`-decorated;
CLI entry points have no async caller). The module SHALL carry fresh
GRACE-lite markup (`MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`,
function contracts, and block anchors) versioned `1.0.0`. The stale
`# FIXME: split adapter and application layer` comment from the old
`infra/cli/manage_node.py` SHALL NOT be carried to the new file. The logic
SHALL be split into private pure functions: `_parse_host_spec(s)`,
`_parse_node_args(argv)`, `_remove_node_hard(deps, spec)`,
`_remove_node_soft(deps, spec)`, `_add_node(deps, repository, operations,
spec, config, skip_setup)`, and the `HostSpec` frozen dataclass. Each
mutate helper opens its own UoW via `deps.uow_factory()` (see the dispatch
requirement); the validation read uses a separate read-only UoW closed
before dispatch. No use case SHALL be extracted into `application/` — YAGNI
(no second consumer; the daemon-side node lifecycle is owned by the
orchestrator).

#### Scenario: yasetnode entry point uses asyncio.run
- **WHEN** the `manage_node` callable in `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** it is a synchronous `def manage_node(argv: list[str] | None = None)` that calls `asyncio.run(_manage_node_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

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
`yascheduler/entrypoints/cli/check_status.py`, a synchronous entry point
that calls `asyncio.run(_check_status_async(argv))` (NOT `@to_sync`-decorated;
CLI entry points have no async caller). It SHALL accept an `argv:
list[str] | None = None` parameter for testability (`None` reads
`sys.argv`, the argparse convention; tests pass an explicit list). It SHALL
obtain `Config` via `Config.from_config_parser`, build `CLIDeps` via
`make_cli_deps(config)` once, and open exactly one short UoW for the query
phase (fetching `tasks`, and additionally `nodes_by_ip` only when the
selected renderer needs node fields — i.e. `-v` or `--json`). The UoW SHALL
be closed before any SSH work begins (no DB connection held during SSH).

#### Scenario: yastatus entry point uses asyncio.run
- **WHEN** the `check_status` callable in `yascheduler/entrypoints/cli/check_status.py` is inspected
- **THEN** it is a synchronous `def check_status(argv: list[str] | None = None)` that calls `asyncio.run(_check_status_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

### Requirement: yastatus view mode connects via SSH with correct node params

When `-v` (or `-v -o`) is given, `yastatus` SHALL, for each RUNNING task with
an allocated IP, connect to the remote machine via `SSHMachineRepository`
(resolving a `MachineSession` via `repository.get_session` / a fresh
`repository.connect`), display a tail of the remote `OUTPUT` file, optionally
download and parse a CRYSTAL convergence snippet (when `-o` is also given),
and disconnect. The SSH connection parameters SHALL be resolved by a private
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

All four parameters SHALL be passed to `repository.connect(...)`. The
convergence snippet SHALL be stored in a `tempfile`-based file (NOT the
previous fixed-name `local_calc_snippet.tmp`) and cleaned up in a
`try/finally` block so it is removed even when `_render_view` raises.

#### Scenario: yastatus -v uses node.username not cloud username
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `username="yascheduler"` and `cloud="hetzner"`, and the `hetzner` cloud config has `username="hcloud-user"`
- **THEN** `repository.connect(...)` is called with `username="yascheduler"` (the node's username, NOT the cloud's)

#### Scenario: yastatus -v passes node.port
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `port=2222`
- **THEN** `repository.connect(...)` is called with `port=2222` (NOT the repository default of 22)

#### Scenario: yastatus -v resolves jump host from matching cloud
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `cloud="hetzner"`, and the `hetzner` cloud config has `jump_host="jump.example.com"` and `jump_username="jumper"`
- **THEN** `repository.connect(...)` is called with `jump_host="jump.example.com"` and `jump_username="jumper"`

#### Scenario: yastatus -v falls back to config.remote for static nodes
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a static node (`cloud=None`), and `config.remote.jump_host` is set
- **THEN** `repository.connect(...)` is called with `jump_host=config.remote.jump_host` and `jump_username=config.remote.jump_username`

#### Scenario: yastatus -v -o uses a tempfile for the convergence snippet
- **WHEN** `yastatus -v -o` is invoked
- **THEN** the convergence snippet is written to a `tempfile.NamedTemporaryFile`/`mkstemp`-created file with a unique name (NOT the fixed `local_calc_snippet.tmp`), so concurrent invocations do not collide

#### Scenario: yastatus cleans up the snippet on exception
- **WHEN** `yastatus -v -o` is invoked and `_render_view` raises an exception during SSH or parse
- **THEN** the convergence snippet file is removed by the `try/finally` block (the previous implementation skipped cleanup on the exception path)

## REMOVED Requirements

### Requirement: utils.py preserves re-exports
**Reason**: `yascheduler/utils.py` no longer exists. The re-export shim was removed once all CLI commands relocated to `yascheduler/entrypoints/cli/` and console_scripts were repointed. Keeping this requirement leaves a spec contract for a file that does not exist.
**Migration**: Console_scripts in `pyproject.toml` point directly at `yascheduler.entrypoints.cli.*` modules. No `utils.py` re-export is needed; consumers import from the entrypoints CLI modules directly.