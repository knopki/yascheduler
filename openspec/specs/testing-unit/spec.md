## Purpose

Unit tests for yascheduler: domain entities, domain exceptions, domain ports,
domain services, config parsing, legacy DB models, persistence adapters (mocked),
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
- `TaskContext` known fields, extra dict, `to_metadata`/`from_metadata` round-trip
  (None omission, extra key merge, webhook_custom_params preservation)
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
Protocol checks for `TaskRepository`, `NodeRepository`, `MachineGateway`,
`CloudProvisioner` from `yascheduler.domain.ports`.

#### Scenario: Stub implementations satisfy Protocol checks
- **WHEN** stub classes with matching async method signatures are checked against `TaskRepository`, `NodeRepository`, `MachineGateway`, `CloudProvisioner`
- **THEN** `isinstance` returns `True` for each

### Requirement: Domain services

Tests SHALL verify `match_task_to_node` from `yascheduler.domain.services`:
returns first compatible free machine, returns `None` for no match, busy-only,
or empty lists.

#### Scenario: match_task_to_node returns first compatible free machine
- **WHEN** `match_task_to_node(task, engine, [busy_machine, free_compatible, free_other])` is called
- **THEN** it returns the `free_compatible` machine

### Requirement: Config parsing and validation

Tests SHALL verify INI config parsing:
- `ConfigDb`, `ConfigLocal`, `ConfigRemote` defaults and overrides
- Cloud config parsing (Hetzner, UpCloud, Azure)
- `AzureImageReference.from_urn` rejects malformed URN with `ValueError`
- `ConfigCloudAzure` rejects `username="root"` with `ValueError`
- `Engine` rejects unknown spawn placeholders, missing check methods, empty input_files
- `EngineRepository.filter`, `filter_platforms`, immutability
- `Config.from_config_parser` full assembly and empty section defaults
- `warn_unknown_fields` emits `ConfigWarning` for unknown keys

#### Scenario: AzureImageReference.from_urn rejects malformed URN
- **WHEN** `AzureImageReference.from_urn("bad-urn")` is called
- **THEN** `ValueError` is raised

### Requirement: Legacy DB models (TaskModel, NodeModel, TaskStatus)

Tests SHALL verify legacy attrs-based models from `yascheduler.db`:
- `TaskStatus` values: TO_DO=0, RUNNING=1, DONE=2, subclass of `int`
- `TaskModel` frozen, `TaskStatus` converter, deterministic hash
- `NodeModel` defaults and frozen

#### Scenario: TaskModel is frozen and hashable
- **WHEN** a `TaskModel` instance is created
- **THEN** it is frozen (cannot mutate attributes) and has a deterministic hash

### Requirement: DB facade with mocked connection

Tests SHALL verify `DB` methods from `yascheduler.db` using a mocked pg8000
connection: node CRUD (`add_node`, `get_node`, `enable_node`, `disable_node`,
`remove_node`), task CRUD (`add_task`, `get_task`, `set_task_running`,
`set_task_done`), and `set_task_error` with/without error message.

#### Scenario: DB set_task_error with and without message
- **WHEN** `db.set_task_error(task_id, metadata, error="crash")` then `db.set_task_error(task_id, metadata)` are called with a mocked connection
- **THEN** the first call embeds `"error": "crash"` in metadata; the second passes metadata without adding an error key

### Requirement: Persistence adapter with mocked pg8000

Tests SHALL verify `PostgresTaskRepository`, `PostgresNodeRepository`, and
`PostgresUnitOfWork` from `yascheduler.adapters.persistence` using mocked
pg8000 connections:
- `load_query` reads file on first call, returns cache on subsequent calls
- UoW: enter creates repos, commit calls `conn.run("COMMIT")`, exception
  triggers rollback, normal exit closes connection, commit after exit raises
  `UnitOfWorkNotInitializedError`
- Task repo: `get`, `insert` (returns generated ID), `save` (upsert),
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
- `CLIDeps` stores fields and delegates `submit`/`query`
- `make_cli_deps` returns `CLIDeps` with `PostgresUnitOfWork` factory
- `make_daemon` creates all dependencies and accepts optional `db`/`clouds`
- `make_aiida` raises `NotImplementedError`

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

Tests SHALL verify CLI entry point functions exist, are decorated with `@to_sync`
where applicable, and `daemonize` references `make_daemon`.

#### Scenario: CLI entry points are importable
- **WHEN** each CLI entry point module is imported
- **THEN** the expected function symbols are present

### Requirement: Scheduler characterization tests

Tests SHALL verify `Scheduler` delegates `create_new_task` to `submit_task`,
`start()` to `make_daemon`/Orchestrator, and `stop()` to orchestrator or falls
back to clouds/db cleanup. `Yascheduler.queue_submit_task_async` uses `make_cli_deps`.

#### Scenario: Scheduler.create_new_task delegates to submit_task
- **WHEN** `scheduler.create_new_task(...)` is called
- **THEN** it calls the `submit_task` use case

### Requirement: UniqueQueue

Tests SHALL verify `UniqueQueue` and `UMessage`: put/get, deduplication,
`item_done` tracking, re-queueing after done, `psize` reflects in-flight,
`task_done` raises `NotImplementedError`.

#### Scenario: UniqueQueue deduplicates identical items
- **WHEN** the same item is put twice before being consumed
- **THEN** the second put is ignored and queue size does not increase

### Requirement: Remote machine management

Tests SHALL verify `RemoteMachineMetadata` state transitions (`busy` toggles
`free_since`), `is_free_longer_than` evaluation, `RemoteMachineRepository.filter`
(busy, platforms, free_since_gt, reverse_sort, original unchanged).

#### Scenario: RemoteMachineMetadata busy=True sets free_since to None
- **WHEN** `metadata.busy = True` is set on a free machine
- **THEN** `free_since` becomes `None`

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

### Requirement: FakeDB test double

The project SHALL provide a `FakeDB` class implementing the same public methods
as `DB` on in-memory data structures, returning `TaskModel`/`NodeModel` with
auto-incrementing `task_id`.

#### Scenario: FakeDB mirrors DB public methods
- **WHEN** `FakeDB` is used in place of `DB`
- **THEN** `add_task`, `get_task`, `add_node`, `get_all_nodes`, status transitions
  all behave equivalently to `DB`

### Requirement: Shared test fixtures

`tests/fixtures/models.py` SHALL provide `make_task` and `make_node` helpers
with sensible defaults. `tests/fixtures/mock_remote_machine.py` and
`tests/fixtures/mock_clouds.py` SHALL provide spec-compliant mock factories.

#### Scenario: make_task returns TaskModel with defaults
- **WHEN** `make_task()` is called without arguments
- **THEN** it returns a `TaskModel` with `status=TaskStatus.TO_DO`

### Requirement: WebhookPayload

`WebhookPayload` SHALL hold `task_id`, `status`, and `custom_params` fields.
Default `custom_params` is empty dict.

#### Scenario: WebhookPayload defaults custom_params to empty dict
- **WHEN** `WebhookPayload(task_id=1, status=0)` is created
- **THEN** `custom_params` is `{}`
