# Delta: testing-unit

## MODIFIED Requirements

### Requirement: Domain entities lifecycle

Tests SHALL verify `Task`, `Node`, `ConnectedMachine`, `Engine`,
`ProcessResult`, `TaskStatus`, and `MachineState`: lifecycle transition
methods and their guard errors, `Task` immutability, `Engine.validate_inputs`
behavior, `ConnectedMachine` state transitions, and `Node` defaults.

#### Scenario: Task fail on non-running raises TaskNotRunningError
- **WHEN** `task.fail("reason")` is called on a TO_DO task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: Task fail sets error to the reason
- **WHEN** `task.fail("out of memory")` is called on a RUNNING task
- **THEN** the returned Task has `status=DONE` and `error="out of memory"`

#### Scenario: Task reject sets error to the reason
- **WHEN** `task.reject("disk full")` is called on a TO_DO task
- **THEN** the returned Task has `status=DONE` and `error="disk full"`

#### Scenario: Task run transitions TO_DO to RUNNING
- **WHEN** `task.run()` is called on a TO_DO task
- **THEN** the returned Task has `status=RUNNING`

#### Scenario: Task run on non-TO_DO raises TaskNotTodoError
- **WHEN** `task.run()` is called on a RUNNING task
- **THEN** `TaskNotTodoError` is raised

#### Scenario: Task complete transitions RUNNING to DONE
- **WHEN** `task.complete()` is called on a RUNNING task
- **THEN** the returned Task has `status=DONE`

#### Scenario: Task complete on non-RUNNING raises TaskNotRunningError
- **WHEN** `task.complete()` is called on a TO_DO task
- **THEN** `TaskNotRunningError` is raised

#### Scenario: Task abandon sets error
- **WHEN** `task.abandon("cancelled")` is called on a RUNNING task
- **THEN** the returned Task has `status=DONE` and `error="cancelled"`

#### Scenario: NewTask has no remote_folder or error
- **WHEN** a NewTask is constructed with `label="job"`, `engine="cp2k"`
- **THEN** it has no `remote_folder` attribute and no `error` attribute; those fields appear only on the post-persistence `Task`

#### Scenario: Engine validate_inputs passes
- **WHEN** `engine.validate_inputs({"input.in": "ATOMS"})` is called and `engine.input_files=("input.in",)`
- **THEN** it passes (no exception)

#### Scenario: Engine validate_inputs raises on missing file
- **WHEN** `engine.validate_inputs({})` is called and `engine.input_files=("input.in",)`
- **THEN** `MissingInputFileError` is raised

### Requirement: Domain exception hierarchy

Tests SHALL verify every exception class in `yascheduler.domain.exceptions` is importable, catchable via its parent class, and carries its documented attribute.

#### Scenario: Exception hierarchy and field carrying
- **WHEN** `UnsupportedEngineError("gaussian")`, `TaskNotTodoError(TaskId(42))`, `NoCompatibleNodeError(TaskId(1), ["linux"])`, `MachineBusyError(NodeId(1))`, `MachineConnectionError(NodeId(1), "10.0.0.1", "refused")` are raised and caught
- **THEN** each stores its documented attribute (`engine_name`, `task_id`, `platforms`, `node_id`, `hostname`, `reason`) and is catchable via its parent class; `MachineBusyError` stores `node_id` only (no `hostname` attribute)

### Requirement: Domain port Protocol conformance

Tests SHALL verify that stub implementations satisfy `@runtime_checkable` Protocol checks for `TaskRepository`, `NodeRepository`, `MachineRepository`, `MachineSession`, and `CloudProvisioner` from `yascheduler.domain.ports`.

#### Scenario: Stub implementations satisfy Protocol checks

- **WHEN** stub classes with matching async method signatures are checked against `TaskRepository`, `NodeRepository`, `MachineRepository`, `MachineSession`, `CloudProvisioner`
- **THEN** `isinstance` returns `True` for each

### Requirement: Domain services

Tests SHALL verify `match_task_to_node` from `yascheduler.domain.services` returns the first compatible free machine or `None`.

#### Scenario: match_task_to_node returns first compatible free machine
- **WHEN** `match_task_to_node(task, engine, [busy_machine, free_compatible, free_other])` is called
- **THEN** it returns the `free_compatible` machine

### Requirement: Config parsing and validation

Tests SHALL verify INI config parsing via `parse_config` and the per-section parser functions: round-tripping `[db]` / `[local]` / `[remote]` / `[engine.*]` / `[cloud.*]` sections into the corresponding value objects, the `CLOUD_CONFIG_PARSERS` registry dispatch for clouds, `ConfigCloudAzure` rejecting `username="root"` via `ValueError`, the frozen `Config` aggregate assembly, and `warn_unknown_fields` emitting `ConfigWarning` for unknown keys.

#### Scenario: parse_config round-trips all sections
- **WHEN** `parse_config(path)` is called with a full INI
- **THEN** the returned `Config` has `db`, `local`, `remote`, `clouds`, `engines` populated with the parsed values and is frozen

#### Scenario: Value objects have no parser methods
- **WHEN** `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig` are inspected
- **THEN** they have no `from_config_parser_section` or `get_valid_config_parser_fields` classmethods; parsing lives in the parser functions

#### Scenario: Config mutation via replace
- **WHEN** a test needs a `Config` with a different `engines` field
- **THEN** it uses `dataclasses.replace(config, engines=new_engines)` (not `config.engines = new_engines`, which raises `FrozenInstanceError`)

#### Scenario: VastAI round-trips via registry
- **WHEN** `parse_config(path)` is called with an INI containing `[cloud.vastai]`
- **THEN** the cloud is parsed via the `CLOUD_CONFIG_PARSERS` registry entry for `vastai` and appears in `config.clouds`

### Requirement: Persistence adapter with mocked pg8000

Tests SHALL verify `PostgresTaskRepository`, `PostgresNodeRepository`, and `PostgresUnitOfWork` against mocked pg8000 connections, covering the repository CRUD methods and UoW lifecycle (enter, commit, rollback on exception, exit, post-exit `UnitOfWorkNotInitializedError`).

#### Scenario: PostgresUnitOfWork commit calls COMMIT
- **WHEN** `uow.commit()` is called with a mocked connection
- **THEN** `conn.run("COMMIT")` is executed

#### Scenario: PostgresUnitOfWork commit after exit raises UnitOfWorkNotInitializedError
- **WHEN** `uow.commit()` is called after the `async with` block has exited
- **THEN** `UnitOfWorkNotInitializedError` is raised and `isinstance(exc, RuntimeError)` is `True`

### Requirement: Application use cases

Tests SHALL verify `submit_task`, `allocate_task`, `consume_task`, and `deallocate_nodes` with mocked dependencies, covering each use case's success, failure, and edge branches.

#### Scenario: submit_task happy path returns task_id
- **WHEN** `submit_task` is called with a supported engine and all inputs present
- **THEN** a task is inserted and a positive integer `task_id` is returned

### Requirement: Orchestrator lifecycle

Tests SHALL verify `Orchestrator` initialization, `start()` background-task creation, `stop()` cancellation and cleanup, cancellation propagation to producer-consumer loops, and the `workers_num` concurrency limit.

#### Scenario: Orchestrator start creates background tasks
- **WHEN** `orchestrator.start()` is called
- **THEN** background asyncio tasks are created for producers and consumers

### Requirement: Dependency injection factories

Tests SHALL verify `CLIDeps`, `make_cli_deps`, and `make_daemon` produce the documented collaborators.

#### Scenario: make_cli_deps returns CLIDeps with PostgresUnitOfWork factory
- **WHEN** `make_cli_deps(config)` is called
- **THEN** the returned `CLIDeps.engines` matches `config.engines` and `uow_factory()` returns a `PostgresUnitOfWork`

### Requirement: CLI behavioral tests

Tests SHALL verify CLI commands (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`) with mocked DI dependencies.

#### Scenario: yasubmit happy path returns task ID
- **WHEN** `yasubmit` is invoked with valid arguments and mocked dependencies
- **THEN** it prints the created task ID

### Requirement: Client queue-submit characterization

Tests SHALL verify `Yascheduler.queue_submit_task_async` routes submissions through `make_cli_deps()` and not the daemon graph.

#### Scenario: Yascheduler.queue_submit_task_async uses make_cli_deps
- **WHEN** `Yascheduler().queue_submit_task_async(label="t", metadata={"k": "v"}, engine_name="fleur")` is called with `make_cli_deps` patched to return a mock `CLIDeps` whose `submit` is an `AsyncMock`
- **THEN** `make_cli_deps` is called once with the client's `config`, `deps.submit` is awaited once with `("t", {"k": "v"}, "fleur")`, and the awaited return value is returned to the caller

### Requirement: UniqueQueue

Tests SHALL verify `UniqueQueue` and `UMessage` put/get, deduplication, `item_done` tracking, re-queueing after done, `psize` semantics, and `task_done` raising `NotImplementedError`.

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

Tests SHALL verify `ConnectedMachine` state transitions (`occupy`/`release` toggling `state`/`free_since`), `MachineBusyError` construction (carries `node_id` only), and `SSHMachineRepository.list_free(platforms)` filtering (busy exclusion, platforms filter, oldest-first ordering by `free_since`, registry unchanged).

#### Scenario: ConnectedMachine occupy sets state to BUSY

- **WHEN** `session.occupy()` is called on a session whose `machine.state` is FREE
- **THEN** `session.machine.state` becomes BUSY and `session.machine.free_since` remains its prior value (only `release` resets `free_since`)

#### Scenario: ConnectedMachine release resets free_since

- **WHEN** `session.release()` is called on a session whose `machine.state` is BUSY
- **THEN** `session.machine.state` becomes FREE and `session.machine.free_since` is set to `time.monotonic()`

#### Scenario: ConnectedMachine occupy on BUSY raises MachineBusyError with node_id only

- **WHEN** `machine.occupy()` is called on a `ConnectedMachine` with `state=BUSY` and `node_id=NodeId(7)`
- **THEN** `MachineBusyError` is raised, `e.node_id == NodeId(7)`, and `e` does NOT have a `hostname` attribute (asserting `not hasattr(e, "hostname")` or `getattr(e, "hostname", None) is None`)

#### Scenario: list_free filters by platform and state

- **WHEN** `repository.list_free(["linux", "debian-12"])` is called on a repository holding FREE linux, BUSY linux, and FREE windows sessions
- **THEN** the returned list contains only the FREE linux session (BUSY excluded, windows excluded by platform filter), sorted oldest-first by `session.machine.free_since`, and the repository's `_sessions` dict is unchanged

### Requirement: OS check functions

Tests SHALL verify platform detection (`check_is_linux`, `check_is_debian`, `check_is_debian_like`, `check_is_windows`) with mocked SSH output.

#### Scenario: check_is_debian returns False for ubuntu
- **WHEN** mocked SSH returns os-release with `ID=ubuntu` and `ID_LIKE=debian`
- **THEN** `check_is_debian(conn)` returns `False`

### Requirement: RemoteMachineAdapter structure

Tests SHALL verify adapter instances have correct platform names, non-None callables, and `debian_adapter.checks` is a superset of `debian_like_adapter.checks`.

#### Scenario: debian_adapter checks includes debian_like_adapter checks
- **WHEN** comparing `debian_adapter.checks` and `debian_like_adapter.checks`
- **THEN** the debian set is a superset of the debian-like set

### Requirement: WebhookPayload

Tests SHALL verify `WebhookPayload` defaults `custom_params` to an empty dict.

#### Scenario: WebhookPayload defaults custom_params to empty dict
- **WHEN** `WebhookPayload(task_id=1, status=0)` is created
- **THEN** `custom_params` is `{}`

### Requirement: Client queue-query unit verification

Tests SHALL verify that `Yascheduler.queue_get_tasks_async` routes queries through the `deps_factory`-injected `CLIDeps.uow_factory` and the `query_tasks` use case, then maps results to the public six-key dict shape.

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

### Requirement: Logging discipline guard tests

The project SHALL provide two guard unit tests in `tests/unit/` that statically enforce the logging contract across the package:

1. **No injected logger in collaborator constructors**: none of the seven collaborator classes (`Orchestrator`, `SSHMachineRepository`, `SSHMachineSession`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`, `CloudProvisionerImpl`) SHALL accept a parameter named `log` in their `__init__` method (or declare a `log` class-level annotation for frozen dataclasses).
2. **No extra-key collision with native LogRecord attributes**: every `extra={...}` literal callsite in `yascheduler/` SHALL use keys that do NOT collide with the native `LogRecord` attribute set, because stdlib merges `extra` into the record via `__dict__.update` and silently overwrites reserved keys (e.g. `name`, `msg`, `funcName`, `levelname`, `lineno`, `module`).

The guard tests SHALL run under the `unit` pytest marker without external resources.

#### Scenario: guard test fails on an injected logger parameter

- **GIVEN** the no-injected-logger guard test is run
- **WHEN** a `log` parameter appears in the `__init__` method of any of the seven collaborator classes (`Orchestrator`, `SSHMachineRepository`, `SSHMachineSession`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`, `CloudProvisionerImpl`)
- **THEN** the guard test fails, naming the class and the file
- **AND** no such `log` parameter exists in the committed package

#### Scenario: guard test fails on an extra-key collision with a native LogRecord attribute

- **GIVEN** the extra-key-collision guard test is run
- **WHEN** a `logger.debug(msg, extra={...})` callsite in `yascheduler/` uses a key that is a native `LogRecord` attribute name (e.g. `funcName`, `levelname`, `msg`, `name`)
- **THEN** the guard test fails, naming the file, the offending key, and the call
- **AND** no such colliding `extra` key exists in the committed package

#### Scenario: guard tests run under the unit marker without external resources

- **WHEN** the two guard tests are run via `uv run pytest -m unit`
- **THEN** both pass without a database, SSH container, or cloud credentials

#### Scenario: guard tests pass on the committed package

- **GIVEN** the committed `yascheduler/` package
- **WHEN** the two guard tests are run via `uv run pytest -m unit`
- **THEN** both pass (no `log` parameters in collaborator `__init__` methods and no `extra`-key collisions with native `LogRecord` attributes exist in the committed package)

## REMOVED Requirements

### Requirement: Shared test fixtures
