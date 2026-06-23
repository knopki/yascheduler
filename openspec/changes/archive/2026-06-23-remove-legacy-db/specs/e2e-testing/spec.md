## MODIFIED Requirements

### Requirement: E2E test fixtures
The project SHALL provide session-scoped and function-scoped pytest fixtures in `tests/e2e/conftest.py` that set up a complete test environment:
- Session-scoped PostgreSQL container (testcontainers) with schema applied via `apply_schema()` from `adapters/persistence/postgres_schema.py`
- Session-scoped SSH container (testcontainers `openssh-server`) with generated key pair
- Session-scoped config fixture that creates a temp directory with minimal INI file (`[db]` + `[engine.test_shell]`), test engine script (`run.sh`) in `data/engines/test_shell/`, and SSH key symlink in `data/keys/`
- Session-scoped `Config` instance parsed from the generated INI
- Function-scoped persistence fixtures: a raw `pg8000.native.Connection` (`pg_conn`), a single-worker `ThreadPoolExecutor` (`pg_executor`), and a `uow_factory` callable returning a `PostgresUnitOfWork` constructed with `_db_config` and a bare `MessageBus()`. Teardown SHALL `TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE` via `pg_conn`. The fixtures SHALL NOT yield a `DB` instance (the class is removed).
- Function-scoped orchestrator fixture that creates but does not start an `Orchestrator` instance

The `YASCHEDULER_CONF_PATH` environment variable SHALL be set to the generated INI path for the duration of the session.

#### Scenario: Config fixture provides valid Config with test engine
- **WHEN** the session-scoped config fixture is resolved
- **THEN** `config.engines` contains exactly one engine named `test_shell` with `spawn="{engine_path}/run.sh"`, `check_pname="sleep"`, `input_files=("1.input",)`, `output_files=("1.input.out",)`, `deployable` containing one `LocalFilesDeploy` pointing to `run.sh`

#### Scenario: Persistence fixtures provide empty database per test
- **WHEN** two E2E tests run sequentially and the first inserts a node via `uow_factory`
- **THEN** the second test sees zero nodes (the `pg_conn` teardown TRUNCATEs both tables)

### Requirement: Full cycle E2E test
The project SHALL provide a test in `tests/e2e/test_full_cycle.py` that exercises the complete scheduler lifecycle:

1. **Add node**: Call `_add_node` logic (create `RemoteMachine`, run `setup_node` to deploy engine, insert node record via `uow.nodes.add(Node(...))` + `uow.commit()`)
2. **Submit task**: Call `deps.submit("e2e test", {"1.input": "hello e2e"}, "test_shell")` to create a TO_DO task
3. **Run orchestrator**: Create orchestrator via `make_daemon`, start as async task, wait for task completion
4. **Verify completion**: Poll task status via the `uow_factory`-backed fixture (`async with uow_factory() as uow: t = await uow.tasks.get(task_id)`) until status is `DONE` with a timeout
5. **Verify output**: Check downloaded output file content matches input
6. **Remove node**: Remove node record via `uow.nodes.remove(ip)` + `uow.commit()`

Status assertions SHALL use `yascheduler.domain.TaskStatus` (not the removed `yascheduler.db.TaskStatus`). The task's allocated IP is read via `task.allocated_ip` (not `task.ip`); the local folder is read via `task.context.local_folder` (not `task.metadata.get("local_folder")`).

#### Scenario: Full lifecycle produces correct output
- **WHEN** a node is added, a task is submitted with input "hello e2e", and the orchestrator runs until completion
- **THEN** the task status is `DONE`, the task has a non-null `allocated_ip` matching the SSH container, and the downloaded output file contains "hello e2e"

#### Scenario: Node transitions BUSY then FREE
- **WHEN** the task is allocated and running
- **THEN** the remote machine's `meta.busy` is `True`
- **WHEN** the task completes and results are consumed
- **THEN** the remote machine's `meta.busy` is `False`

#### Scenario: Engine script is deployed to remote machine
- **WHEN** `setup_node` is called with the test engine
- **THEN** the file `run.sh` exists in the remote engines directory at `{remote_engines_dir}/test_shell/run.sh`

#### Scenario: Task lifecycle transitions are correct
- **WHEN** the task is first created
- **THEN** its status is `TO_DO`
- **WHEN** the orchestrator allocates and starts it
- **THEN** its status transitions to `RUNNING`
- **WHEN** the orchestrator detects completion and downloads results
- **THEN** its status transitions to `DONE`