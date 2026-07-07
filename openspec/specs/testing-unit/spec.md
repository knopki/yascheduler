# Unit testing

## Purpose

Unit tests for yascheduler: domain entities, domain exceptions, domain ports,
domain services, config parsing, persistence adapters (mocked),
application use cases, orchestrator lifecycle, dependency injection, CLI behavior,
remote machine management, and shared test infrastructure. All tests run without
external dependencies (no real DB, SSH, or filesystem).

## Requirements

### Requirement: Domain entities lifecycle

Tests SHALL verify `Task`, `Node`, `ConnectedMachine`, `Engine`,
`ProcessResult`, `TaskStatus`, `MachineState` from `yascheduler.domain.model`
(`TaskContext` and `TaskContextOverrides` are REMOVED — see the `domain-entities`
delta; they are no longer tested):
- `Task` immutability, `allocate_to`/`mark_running`/`complete`/`fail`/`reject`
  transitions and guard errors (`TaskAlreadyAllocatedError`,
  `TaskNotAllocatedError`, `TaskNotTodoError`, `TaskNotRunningError`)
- `Task.with_remote_folder(remote_folder)`: returns a new immutable Task with
  `remote_folder` set, all other fields preserved, `_events` tuple preserved,
  no validation guard (works in any status), and chains with `with_event`/`fail`/
  `complete`
- `Task.with_download_results(*, local_folder, remote_folder)`: returns a new
  immutable Task with both fields set, all other fields (including `extra`)
  preserved, `extra` NOT modified, accepts equal values (no-op-equivalent),
  keyword-only (positional args raise `TypeError`), no validation guard (works
  in any status)
- `Task.fail(reason)` / `Task.reject(reason)`: returns a new Task with
  `status=DONE` and `error=reason` (was `context.error`); guards unchanged
  (`TaskNotRunningError` / `TaskNotTodoError`)
- `Task.with_event` reads `self.webhook_url` / `self.webhook_custom_params`
  (was `self.context.X`); passes `task_id=self.task_id` (a `TaskId`)
- `Task.error` column format contract: bare human strings for
  `reject`/orchestrator `fail`, `"Download error: <path>: <msg>, ..."` for
  consume `fail`, `NULL`/`None` on success
- `NewTask` has no `task_id`, no `_events`, no `created_at`/`updated_at`, no
  `status`, no `allocated_node_id`, no `remote_folder`, no `error` (those appear
  only on `Task`, or are DB-defaulted); a pre-bound task is inserted then
  `allocate_to(node)` + `save()`
- `Engine.validate_inputs` passes with all files, raises `MissingInputFileError`
  when a file is missing
- `ConnectedMachine.is_compatible`, `occupy`, `release` with state guards
- `Node` defaults (username="root", port=22, cloud=None, enabled=True)

Tests SHALL construct `Task` / `NewTask` with the typed fields directly (no
`TaskContext(...)` wrapper, no `context=` kwarg). Test fixtures and helpers
(e.g. `tests/unit/conftest.py`) SHALL be updated to the new construction shape.
Test restructuring is NOT a design blocker (user-explicit); tests are updated
to compile and pass against the new model.

#### Scenario: Task fail on non-running raises TaskNotRunningError
- **WHEN** `task.fail("reason")` is called on a TO_DO task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: Task fail sets error to the reason
- **WHEN** `task.fail("out of memory")` is called on a RUNNING task
- **THEN** the returned Task has `status=DONE` and `error="out of memory"` (was `context.error`)

#### Scenario: Task reject sets error to the reason
- **WHEN** `task.reject("disk full")` is called on a TO_DO task
- **THEN** the returned Task has `status=DONE` and `error="disk full"` (was `context.error`)

#### Scenario: with_remote_folder sets the field and preserves the original
- **WHEN** `task.with_remote_folder("/r/new")` is called on a Task with `remote_folder=None`
- **THEN** the returned Task has `remote_folder="/r/new"` and all other fields (`task_id`, `label`, `engine`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`, `status`, `allocated_node_id`, `_events`) preserved unchanged; the original task is unchanged (frozen dataclass)

#### Scenario: with_remote_folder chains with with_event
- **WHEN** `task.with_remote_folder("/r/new").with_event(TaskCreated, engine_name=task.engine)` is called
- **THEN** the returned Task has `remote_folder="/r/new"` and the `TaskCreated` event appended

#### Scenario: with_download_results sets both fields and preserves extra
- **WHEN** `task.with_download_results(local_folder="/l", remote_folder="/r")` is called on a Task with `extra={"input.in": "ATOMS"}`
- **THEN** the returned Task has `local_folder="/l"`, `remote_folder="/r"`, and `extra={"input.in": "ATOMS"}` unchanged (extra NOT modified)

#### Scenario: with_download_results is keyword-only
- **WHEN** `task.with_download_results("/l", "/r")` is called with positional arguments
- **THEN** `TypeError` is raised

#### Scenario: with_event reads webhook fields from self not self.context
- **WHEN** `task.with_event(TaskCreated, engine_name=task.engine)` is called on a Task with `webhook_url="https://example.com"`, `webhook_custom_params={"k": "v"}`
- **THEN** the constructed `TaskCreated` event has `event.webhook_url == "https://example.com"` and `event.webhook_custom_params == {"k": "v"}` (read from `self.webhook_url` / `self.webhook_custom_params`, was `self.context.X`)

#### Scenario: NewTask has no remote_folder or error
- **WHEN** a NewTask is constructed with `label="job"`, `engine="cp2k"`
- **THEN** it has no `remote_folder` attribute and no `error` attribute; those fields appear only on the post-persistence `Task`

#### Scenario: Engine validate_inputs passes
- **WHEN** `engine.validate_inputs({"input.in": "ATOMS"})` is called and `engine.input_files=("input.in",)`
- **THEN** it passes (no exception)

#### Scenario: Engine validate_inputs raises on missing file
- **WHEN** `engine.validate_inputs({})` is called and `engine.input_files=("input.in",)`
- **THEN** `MissingInputFileError` is raised

#### Scenario: No TaskContext or with_context in tests
- **WHEN** the unit test suite is inspected for `TaskContext`, `TaskContextOverrides`, `with_context`, `task.context`, `to_metadata`, or `from_metadata` references
- **THEN** none are present (the value object is removed; tests use the typed `Task` / `NewTask` fields directly); the drift-lock test for `TaskContextOverrides` is also absent (the TypedDict is removed)

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

#### Scenario: Mock factories provided for remote machine and clouds
- **WHEN** `tests/fixtures/mock_remote_machine.py` and `tests/fixtures/mock_clouds.py` are imported
- **THEN** they provide spec-compliant mock factories for testing

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
