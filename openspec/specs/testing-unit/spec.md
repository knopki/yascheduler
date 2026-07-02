## Purpose

Unit tests for yascheduler: domain entities, domain exceptions, domain ports,
domain services, config parsing, persistence adapters (mocked),
application use cases, orchestrator lifecycle, dependency injection, CLI behavior,
remote machine management, and shared test infrastructure. All tests run without
external dependencies (no real DB, SSH, or filesystem).

## Requirements

### Requirement: Domain entities lifecycle

Tests SHALL verify `Task`, `Node`, `ConnectedMachine`, `TaskContext`, `Engine`,
`ProcessResult`, `TaskStatus`, `MachineState` from `yascheduler.domain.model`:
- `Task` immutability, `allocate_to`/`mark_running`/`complete`/`fail` transitions
  and guard errors (`TaskAlreadyAllocatedError`, `TaskNotAllocatedError`,
  `TaskNotTodoError`, `TaskNotRunningError`)
- `Task.with_context(context)`: wholesale context replacement returns a new
  immutable Task, original is unchanged, `_events` tuple is preserved, no
  validation guard (works in any status), and chains with `with_event`/`fail`/
  `complete`
- `TaskContext` known fields, extra dict, `to_metadata`/`from_metadata` round-trip
  (None omission, extra key merge, webhook_custom_params preservation)
- `TaskContext.replace(**overrides)`: typed copy-with returning a new immutable
  `TaskContext`, single-field and multi-field overrides, original unchanged,
  no-override call returns an equal copy, type checker rejects unknown kwargs
  (verified via the drift-lock test asserting
  `set(TaskContextOverrides.__annotations__) == {"remote_folder", "local_folder",
  "error", "extra"}`)
- `Engine.validate_inputs` passes with all files, raises `MissingInputFileError`
  when a file is missing
- `ConnectedMachine.is_compatible`, `occupy`, `release` with state guards
- `Node` defaults (username="root", port=22, cloud=None, enabled=True)

#### Scenario: Task fail on non-running raises TaskNotRunningError
- **WHEN** `task.fail("reason")` is called on a TO_DO task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: TaskContext round-trip preserves extra
- **WHEN** `TaskContext(engine="fleur", extra={"fort.9": "data"})` is serialized and deserialized
- **THEN** extra keys are preserved

#### Scenario: with_context replaces context wholesale and preserves the original
- **WHEN** `task.with_context(new_context)` is called and the original `task.context` is inspected afterward
- **THEN** the returned Task has `context is new_context` and the original task's context is unchanged (frozen dataclass)

#### Scenario: with_context preserves the events tuple
- **WHEN** `task.with_context(new_context)` is called on a task with a non-empty `_events` tuple
- **THEN** the returned Task has an `_events` tuple equal to the original task's `_events`

#### Scenario: with_context performs no status validation
- **WHEN** `task.with_context(new_context)` is called on a DONE task
- **THEN** no error is raised and a new Task with the new context is returned

#### Scenario: with_context chains with with_event
- **WHEN** `task.with_context(new_context).with_event(TaskCreated, engine_name=new_context.engine)` is called
- **THEN** the returned Task has the new context and the `TaskCreated` event appended

#### Scenario: TaskContext.replace applies a single override and preserves the original
- **WHEN** `ctx.replace(remote_folder="/r/new")` is called on a `TaskContext` with `remote_folder=None`
- **THEN** the returned `TaskContext` has `remote_folder="/r/new"` and all other fields preserved, and the original `ctx.remote_folder` is still `None`

#### Scenario: TaskContext.replace applies multiple overrides simultaneously
- **WHEN** `ctx.replace(local_folder="/l", remote_folder="/r", extra={"k": "v"})` is called
- **THEN** the returned `TaskContext` has all three overridden fields set and all non-overridden fields preserved unchanged

#### Scenario: TaskContext.replace with no overrides returns an equal copy
- **WHEN** `ctx.replace()` is called with no arguments
- **THEN** the returned `TaskContext` compares equal to the original (`==`) but is not the same object (`is`)

#### Scenario: TaskContextOverrides keys match audited call-site usage
- **WHEN** `set(TaskContextOverrides.__annotations__)` is inspected
- **THEN** it equals exactly `{"remote_folder", "local_folder", "error", "extra"}` — the fields actually overridden somewhere in the codebase; drift in either direction (a new call site overriding an unlisted field, or a TypedDict field with no call site) fails this test

### Requirement: Domain exception hierarchy

Tests SHALL verify all exception classes from `yascheduler.domain.exceptions`:
- `DomainError` catchable as `Exception`
- `ValidationError` hierarchy: `UnsupportedEngineError` (carries `engine_name`),
  `MissingInputFileError` (carries `engine_name`, `filename`)
- `TaskError` hierarchy: `TaskAlreadyAllocatedError`, `TaskNotAllocatedError`,
  `TaskNotTodoError`, `TaskNotRunningError` (each carries `task_id`)
- `MachineBusyError` (carries `ip`)
- `SchedulingError` hierarchy: `NoCompatibleNodeError` (carries `task_id`, `platforms`),
  `CloudCapacityExhaustedError` (carries `task_id`)
- All classes importable from `yascheduler.domain.exceptions`

#### Scenario: Exception hierarchy and field carrying
- **WHEN** `UnsupportedEngineError("gaussian")`, `TaskAlreadyAllocatedError(42)`, `NoCompatibleNodeError(1, ["linux"])` are raised and caught
- **THEN** each stores its documented attribute (`engine_name`, `task_id`, `platforms`) and is catchable via its parent class

### Requirement: Domain port Protocol conformance

Tests SHALL verify that stub implementations satisfy `@runtime_checkable`
Protocol checks for `TaskRepository`, `NodeRepository`, `MachineRepository`,
`MachineSession`, `MachineOperations`, `CloudProvisioner` from
`yascheduler.domain.ports`.

#### Scenario: Stub implementations satisfy Protocol checks
- **WHEN** stub classes with matching async method signatures are checked against `TaskRepository`, `NodeRepository`, `MachineRepository`, `MachineSession`, `MachineOperations`, `CloudProvisioner`
- **THEN** `isinstance` returns `True` for each

### Requirement: Domain services

Tests SHALL verify `match_task_to_node` from `yascheduler.domain.services`:
returns first compatible free machine, returns `None` for no match, busy-only,
or empty lists.

#### Scenario: match_task_to_node returns first compatible free machine
- **WHEN** `match_task_to_node(task, engine, [busy_machine, free_compatible, free_other])` is called
- **THEN** it returns the `free_compatible` machine

### Requirement: Config parsing and validation

Tests SHALL verify INI config parsing via the `parse_config` function and
the per-section parser functions in
`yascheduler/entrypoints/config_parser.py`:

- `_parse_db_section`, `_parse_local_section`, `_parse_remote_section`
  round-trip `[db]`, `[local]`, `[remote]` sections into
  `PostgresDbConfig`, `LocalSettings`, `RemoteDefaults` with defaults and
  overrides.
- `parse_engines` round-trips `[engine.*]` sections into
  `EngineRepository` (from P2).
- `parse_clouds` round-trips `[cloud.*]` sections into
  `Sequence[CloudConfig]` via the `CLOUD_CONFIG_PARSERS` registry (from
  P3), including `ConfigCloudAzure`, `ConfigCloudHetzner`,
  `ConfigCloudUpcloud`, `ConfigCloudVastAI`.
- `ConfigCloudAzure` rejects `username="root"` with `ValueError` (parser-side
  validation).
- `parse_config(path)` full assembly produces a frozen `Config` aggregate
  with all five fields populated; empty sections use defaults.
- `warn_unknown_fields` emits `ConfigWarning` for unknown keys (called from
  the parser functions, not from the value objects).
- The value objects (`LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`,
  `Config`, `Engine`, `EngineRepository`, `ConfigCloud*`) SHALL be asserted
  frozen (`@dataclass(frozen=True)`) with no `from_config_parser_section` or
  `get_valid_config_parser_fields` methods.

Test fixtures SHALL construct `Config` instances via `dataclasses.replace`
or a `ConfigBuilder` helper, not via direct attribute assignment
(`config.engines = ...`), because `Config` is frozen.

#### Scenario: parse_config round-trips all sections
- **WHEN** `parse_config(path)` is called with a full INI
- **THEN** the returned `Config` has `db`, `local`, `remote`, `clouds`, `engines` populated with the parsed values and is frozen

#### Scenario: Value objects have no parser methods
- **WHEN** `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig` are inspected
- **THEN** they have no `from_config_parser_section` or `get_valid_config_parser_fields` classmethods; parsing lives in `entrypoints/config_parser.py`

#### Scenario: Config mutation via replace
- **WHEN** a test needs a `Config` with a different `engines` field
- **THEN** it uses `dataclasses.replace(config, engines=new_engines)` (not `config.engines = new_engines`, which raises `FrozenInstanceError`)

#### Scenario: ConfigBuilder helper for high-density test files
- **WHEN** a test file has ≥4 `replace` call sites
- **THEN** it MAY use a `ConfigBuilder` helper defined in `tests/unit/conftest.py` to avoid repetition; the builder produces a frozen `Config` instance

#### Scenario: VastAI round-trips via registry
- **WHEN** `parse_config(path)` is called with an INI containing `[cloud.vastai]`
- **THEN** the cloud is parsed via the `CLOUD_CONFIG_PARSERS` registry entry for `vastai` and appears in `config.clouds`

### Requirement: Persistence adapter with mocked pg8000

Tests SHALL verify `PostgresTaskRepository`, `PostgresNodeRepository`, and
`PostgresUnitOfWork` from `yascheduler.infra.persistence` using mocked
pg8000 connections:
- `load_query` reads file on first call, returns cache on subsequent calls
- UoW: enter creates repos, commit calls `conn.run("COMMIT")`, exception
  triggers rollback, normal exit closes connection, commit after exit raises
  `UnitOfWorkNotInitializedError`
- Task repo: `get`, `insert` (returns generated ID), `save` (update by task_id),
  `list_by_status`, `list_by_jobs`, `count_by_status`, `update_status`
- Node repo: `get`, `list_enabled` (filters invalid IPs), `list_disabled`,
  `add`, `enable`, `disable`, `remove`, `get_by_ips`

#### Scenario: PostgresUnitOfWork commit calls COMMIT
- **WHEN** `uow.commit()` is called with a mocked connection
- **THEN** `conn.run("COMMIT")` is executed

#### Scenario: PostgresUnitOfWork commit after exit raises UnitOfWorkNotInitializedError
- **WHEN** `uow.commit()` is called after the `async with` block has exited
- **THEN** `UnitOfWorkNotInitializedError` is raised and `isinstance(exc, RuntimeError)` is `True`

### Requirement: Application use cases

Tests SHALL verify use cases with mocked dependencies:
- `submit_task`: raises `UnsupportedEngineError`/`MissingInputFileError`,
  happy path inserts task and returns task_id
- `allocate_task`: unsupported engine → `set_task_error` + return False;
  free machine found → allocated + return True; no free machine →
  `clouds.allocate` called + return False
- `consume_task`: successful download → `set_task_done`; download failure →
  `set_task_error`
- `deallocate_nodes`: idle cloud node disabled; non-cloud node skipped

#### Scenario: submit_task happy path returns task_id
- **WHEN** `submit_task` is called with a supported engine and all inputs present
- **THEN** a task is inserted and a positive integer `task_id` is returned

### Requirement: Orchestrator lifecycle

Tests SHALL verify `Orchestrator` initialization creates 4 `UniqueQueue`
instances with correct names and config-derived maxsizes, `start()` creates
background tasks, `stop()` cancels tasks and cleans up, cancellation propagates
to producer-consumer loops, and concurrency limits are passed as `workers_num`.

#### Scenario: Orchestrator start creates background tasks
- **WHEN** `orchestrator.start()` is called
- **THEN** background asyncio tasks are created for producers and consumers

### Requirement: Dependency injection factories

Tests SHALL verify:
- `CLIDeps` stores fields and delegates `submit`
- `make_cli_deps` returns `CLIDeps` with `PostgresUnitOfWork` factory
- `make_daemon` creates all dependencies and accepts optional `clouds`

#### Scenario: make_cli_deps returns CLIDeps with PostgresUnitOfWork factory
- **WHEN** `make_cli_deps(config)` is called
- **THEN** the returned `CLIDeps.engines` matches `config.engines` and `uow_factory()` returns a `PostgresUnitOfWork`

### Requirement: CLI behavioral tests

Tests SHALL verify CLI commands (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`)
with mocked DI dependencies: submit happy path and validation errors, status
listing and info mode, node listing with task info, node add/remove/enable/disable.

#### Scenario: yasubmit happy path returns task ID
- **WHEN** `yasubmit` is invoked with valid arguments and mocked dependencies
- **THEN** it prints the created task ID

### Requirement: CLI smoke tests

Tests SHALL verify CLI entry point functions exist, are synchronous `def`
entry points that call `asyncio.run(_<name>_async(argv))` (not `@to_sync`-
decorated), and `daemonize` references `make_daemon`.

#### Scenario: CLI entry points are importable
- **WHEN** each CLI entry point module is imported
- **THEN** the expected function symbols are present

### Requirement: Client queue-submit characterization

Tests SHALL verify that `Yascheduler.queue_submit_task_async` (implemented in
`yascheduler/entrypoints/client.py`; re-exported by the `yascheduler/client.py`
compat shim) submits a task through the composition root's `make_cli_deps()`
factory and does not instantiate the daemon graph. Specifically,
`queue_submit_task_async` MUST call
`make_cli_deps(config).submit(label, metadata, engine_name)` and return its result.

#### Scenario: Yascheduler.queue_submit_task_async uses make_cli_deps
- **WHEN** `Yascheduler().queue_submit_task_async(label="t", metadata={"k": "v"}, engine_name="fleur")` is called with `make_cli_deps` patched to return a mock `CLIDeps` whose `submit` is an `AsyncMock`
- **THEN** `make_cli_deps` is called once with the client's `config`, `deps.submit` is awaited once with `("t", {"k": "v"}, "fleur")`, and the awaited return value is returned to the caller

### Requirement: UniqueQueue

Tests SHALL verify `UniqueQueue` and `UMessage`: put/get, deduplication,
`item_done` tracking, re-queueing after done, `psize` reflects in-flight,
`task_done` raises `NotImplementedError`.

Deduplication in `UniqueQueue` SHALL be keyed on the message `id`. Two
`UMessage` instances with equal `id` SHALL be treated as duplicates regardless
of their `payload`. The `payload` field SHALL NOT participate in `__eq__` or
`__hash__`; therefore an unhashable `payload` (e.g. a `dict`) SHALL be
accepted at construction and during enqueue/get/item_done operations.

#### Scenario: UniqueQueue deduplicates identical items
- **WHEN** the same item (equal `id`) is put twice before being consumed
- **THEN** the second put is ignored and queue size does not increase

#### Scenario: UniqueQueue deduplicates under concurrent put on a full queue
- **WHEN** a `UniqueQueue` at `maxsize=1` with a blocking item A has two
  concurrent coroutines attempting `put(Y)` with the same item, both suspended
  inside `super().put()` because the queue is full, and a consumer drains
  the queue via repeated `get()` calls
- **THEN** only one Y is ever enqueued: after the consumer drains `A` and `Y`,
  `q.qsize() == 0`, and exactly one `put` call enqueued the item

### Requirement: Remote machine management

Tests SHALL verify `ConnectedMachine` state transitions (`occupy`/`release`
toggling `free_since` via `MachineSession.occupy()`/`MachineSession.release()`),
and `SSHMachineRepository.list_free(platforms)` filtering (busy exclusion,
platforms filter, oldest-first ordering by `free_since`, original registry
unchanged). Tests target the session/repository split defined in the
`ssh-infrastructure` capability.

#### Scenario: ConnectedMachine occupy sets state to BUSY

- **WHEN** `session.occupy()` is called on a session whose `machine.state` is FREE
- **THEN** `session.machine.state` becomes BUSY and `session.machine.free_since` remains its prior value (only `release` resets `free_since`)

#### Scenario: ConnectedMachine release resets free_since

- **WHEN** `session.release()` is called on a session whose `machine.state` is BUSY
- **THEN** `session.machine.state` becomes FREE and `session.machine.free_since` is set to `time.monotonic()`

#### Scenario: list_free filters by platform and state

- **WHEN** `repository.list_free(["linux", "debian-12"])` is called on a repository holding FREE linux, BUSY linux, and FREE windows sessions
- **THEN** the returned list contains only the FREE linux session (BUSY excluded, windows excluded by platform filter), sorted oldest-first by `session.machine.free_since`, and the repository's `_sessions` dict is unchanged

### Requirement: OS check functions

Tests SHALL verify platform detection (`check_is_linux`, `check_is_debian`,
`check_is_debian_like`, `check_is_windows`) with mocked SSH output, including
`check_is_debian` returning False for ubuntu.

#### Scenario: check_is_debian returns False for ubuntu
- **WHEN** mocked SSH returns os-release with `ID=ubuntu` and `ID_LIKE=debian`
- **THEN** `check_is_debian(conn)` returns `False`

### Requirement: RemoteMachineAdapter structure

Tests SHALL verify adapter instances have correct platform names, non-None
callables, and `debian_adapter.checks` is a superset of `debian_like_adapter.checks`.

#### Scenario: debian_adapter checks includes debian_like_adapter checks
- **WHEN** comparing `debian_adapter.checks` and `debian_like_adapter.checks`
- **THEN** the debian set is a superset of the debian-like set

### Requirement: Shared test fixtures

The project SHALL provide spec-compliant mock factories in
`tests/fixtures/mock_remote_machine.py` and `tests/fixtures/mock_clouds.py`.
Tests SHALL construct domain entities directly (`yascheduler.domain.Task`,
`yascheduler.domain.Node`) or via local helpers in each test file.

#### Scenario: Domain entities constructed directly in tests
- **WHEN** a unit test needs a `Task` or `Node` instance
- **THEN** it constructs `yascheduler.domain.Task(...)` / `yascheduler.domain.Node(...)` directly (or via a file-local helper)

### Requirement: WebhookPayload

`WebhookPayload` SHALL hold `task_id`, `status`, and `custom_params` fields.
Default `custom_params` is empty dict.

#### Scenario: WebhookPayload defaults custom_params to empty dict
- **WHEN** `WebhookPayload(task_id=1, status=0)` is created
- **THEN** `custom_params` is `{}`

### Requirement: Client queue-query unit verification

Tests SHALL verify that `Yascheduler.queue_get_tasks_async` (implemented in
`yascheduler/entrypoints/client.py`; re-exported by the `yascheduler/client.py`
compat shim) routes queries through the `deps_factory`-injected `CLIDeps.uow_factory`
and the `query_tasks` use case, then maps results to the public six-key dict shape.
Tests SHALL construct the client with a `FakeCLIDeps`-returning `deps_factory` whose
`uow_factory()` returns a `FakeUnitOfWork` carrying a `FakeTaskRepository`.

#### Scenario: Status filter dispatches list_by_status
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(status=[0])` is called with `FakeTaskRepository.list_by_status` seeded to return a known Task
- **THEN** `list_by_status({domain.TaskStatus.TO_DO})` is awaited and the returned dict has exactly the keys `{task_id, label, ip, status, metadata, cloud}`

#### Scenario: Jobs filter dispatches list_by_jobs
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(jobs=[7])` is called
- **THEN** `list_by_jobs([7])` is awaited on the fake repository and results mapped to the six-key shape

#### Scenario: Both filters supplied raises ValueError
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(jobs=[1], status=[0])` is called
- **THEN** `ValueError` is raised

#### Scenario: Neither filter returns empty list
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async()` is called with no arguments
- **THEN** `[]` is returned without dispatching to the repository

#### Scenario: Returned dict shape and types are correct
- **WHEN** a Task with `allocated_ip=None` is seeded into the fake repository and queried
- **THEN** the returned dict has `ip == ""`, `status` is `isinstance(status, domain.TaskStatus)` (not a plain int), and `cloud is None`

### Requirement: pytest configuration

The project SHALL declare pytest configuration under `[tool.pytest.ini_options]` in `pyproject.toml`, with `testpaths` pointing to `tests/unit/`. Integration and e2e tests run via explicit paths only.

#### Scenario: Default pytest run executes only unit tests
- **WHEN** developer runs `pytest` without arguments
- **THEN** only tests under `tests/unit/` are discovered and executed

### Requirement: Test directory structure

`tests/` SHALL contain `unit/`, `integration/`, and `e2e/` subdirectories, each with `__init__.py`.

#### Scenario: Test directories exist
- **WHEN** the project is checked out
- **THEN** `tests/unit/`, `tests/integration/`, and `tests/e2e/` directories exist with `__init__.py`

### Requirement: CI unit test workflow

A GitHub Actions workflow triggered on push and pull request SHALL run unit tests via `pytest`. CI SHALL NOT execute integration or e2e tests.

#### Scenario: CI excludes integration tests
- **WHEN** the CI workflow runs
- **THEN** only tests under `tests/unit/` execute
