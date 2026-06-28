## MODIFIED Requirements

### Requirement: E2E test fixtures
The project SHALL provide session-scoped and function-scoped pytest fixtures in `tests/e2e/conftest.py` that set up a complete test environment:
- Session-scoped PostgreSQL container (testcontainers) with schema applied via `apply_schema()` from `infra/persistence/postgres_schema.py`
- Session-scoped `ssh_pool` fixture: a list of TWO SSH containers (testcontainers `openssh-server`) started from ONE generated keypair (shared `PUBLIC_KEY` env). Each container yields its own `get_container_host_ip()` and mapped port 2222. Both containers share the same `username`.
- Session-scoped config fixture that creates a temp directory with minimal INI file (`[db]` + `[engine.test_shell]`), test engine script (`run.sh`) in `data/engines/test_shell/`, and a SINGLE SSH private key symlink in `data/keys/` (the shared keypair used by both `ssh_pool` containers)
- Session-scoped `Config` instance parsed from the generated INI
- Function-scoped persistence fixtures: a raw `pg8000.native.Connection` (`pg_conn`), a single-worker `ThreadPoolExecutor` (`pg_executor`), and a `uow_factory` callable returning a `PostgresUnitOfWork` constructed with `_db_config` and a bare `MessageBus()`. Teardown SHALL `TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE` via `pg_conn`.
- Function-scoped `log_records` fixture: an in-memory `logging.Handler` subclass that appends every `LogRecord` to a list, attached to the `"yascheduler"` logger at DEBUG level for the test duration and removed in teardown. The fixture SHALL expose the captured records so tests can grep `record.getMessage()` for structured-log substrings.
- Function-scoped orchestrator fixture that creates but does not start an `Orchestrator` instance

The `YASCHEDULER_CONF_PATH` environment variable SHALL be set to the generated INI path for the duration of the session.

#### Scenario: Config fixture provides valid Config with test engine
- **WHEN** the session-scoped config fixture is resolved
- **THEN** `config.engines` contains exactly one engine named `test_shell` with `spawn="{engine_path}/run.sh"`, `check_pname="sleep"`, `input_files=("1.input",)`, `output_files=("1.input.out",)`, `deployable` containing one `LocalFilesDeploy` pointing to `run.sh`

#### Scenario: ssh_pool fixture provides two distinct SSH containers sharing one keypair
- **WHEN** the session-scoped `ssh_pool` fixture is resolved
- **THEN** it returns a list of two dicts, each with `host`, `port`, `username`, `key_path`
- **AND** the two `host` values are distinct (different container IPs)
- **AND** the two `key_path` values are identical (shared keypair)
- **AND** the two `username` values are identical

#### Scenario: Persistence fixtures provide empty database per test
- **WHEN** two E2E tests run sequentially and the first inserts a node via `uow_factory`
- **THEN** the second test sees zero nodes (the `pg_conn` teardown TRUNCATEs both tables)

#### Scenario: log_records fixture captures yascheduler debug logs for the test duration
- **WHEN** the `log_records` fixture is active and the orchestrator emits a debug log
- **THEN** the log record's `getMessage()` is present in the captured list
- **AND** after the test, the handler is removed from the `"yascheduler"` logger

### Requirement: Test engine script
The project SHALL provide a shell script `run.sh` as the test engine executable. The script SHALL sleep for 3 seconds then copy `1.input` to `1.input.out` in the current working directory. The script SHALL be executable and use `#!/bin/sh` shebang.

#### Scenario: Test engine produces output from input
- **WHEN** `run.sh` executes in a directory containing `1.input` with content "hello e2e"
- **THEN** after completion, `1.input.out` exists with content "hello e2e"

### Requirement: Full cycle E2E test
The project SHALL provide a test in `tests/e2e/test_full_cycle.py` that exercises the complete scheduler lifecycle through the application's real entrypoint code paths (not direct repository/UoW bypass):

1. **Start daemon**: Create the orchestrator via `make_daemon(config)` and start it as a background `asyncio.Task` via `orchestrator.start()`. The test SHALL NOT call `run_daemon` (which registers signal handlers unsuitable for a test loop).
2. **Submit jobs**: Submit four tasks by calling the internal async entrypoint `_submit_async(argv)` from `entrypoints/cli/submit.py` (the async core of the `yasubmit` CLI). Each call SHALL pass `["<script_path>", "--config", "<ini_path>"]` where `<script_path>` is a temp file containing `ENGINE=test_shell` and `LABEL=job_N`, and the current working directory is a temp dir containing a `1.input` file with content `"hello e2e N"` (per-job CWD isolation via `monkeypatch.chdir`). The test SHALL capture `task_id` from the entrypoint's stdout (`print(str(task_id))`).
3. **Assert queued**: After all four submissions, read all four tasks via `uow_factory()` and assert each has status `TO_DO`.
4. **Add nodes**: Add two nodes by calling the internal async entrypoint `_manage_node_async(argv)` from `entrypoints/cli/manage_node.py` (the async core of the `yasetnode` CLI) twice — once per `ssh_pool` container — passing `["<host>:<port>", "--config", "<ini_path>"]`. The `:<port>` is required because the SSH containers listen on port 2222, not the `yasetnode` default of 22. Each call exercises the real `_add_node` path: `SSHMachineRepository.connect` + `operations.setup_node` + `uow.nodes.add` + `commit` + `disconnect`.
5. **Assert nodes added**: After both `_add_node` calls return, assert `uow.nodes.list_all()` returns both nodes.
6. **Wait for completion**: Poll `uow_factory()` reading each task until all four reach status `DONE`, with a timeout of at least 30 seconds.
7. **Assert completion and outputs**: For each task, assert `status == DONE`, `context.error is None`, `context.local_folder` is set, and the output file `<local_folder>/1.input.out` exists with content matching the per-job `1.input` payload.
8. **Assert distribution**: Collect `allocated_ip` from all four tasks. Assert the set of allocated IPs equals `{"<ipA>", "<ipB>"}` (both nodes were used) AND that no single node received all four tasks (reject the 0:4 / 4:0 monopoly case — those indicate one node never accepted work).
9. **Assert scheduling activity in logs**: Grep the captured `log_records` for `[AllocateTask][_try_allocate_to_machine][ALLOCATED]` entries and assert one appears for each of the four `task_id`s, and that both node IPs appear among the logged `ip=` values.
10. **Remove nodes (soft)**: Remove both nodes by calling `_manage_node_async(["<host>:<port>", "--remove-soft", "--config", "<ini_path>"])` once per container. This exercises the real `_remove_node_soft` path which, with no RUNNING tasks, takes the `uow.nodes.remove(ip)` branch.
11. **Assert nodes removed**: After both soft-remove calls return, assert `uow.nodes.list_all()` returns an empty list.
12. **Stop daemon**: In a `finally` block, call `orchestrator.stop()` and `asyncio.wait_for(orch_task, timeout=10)`.

Status assertions SHALL use `yascheduler.domain.TaskStatus`. The task's allocated IP is read via `task.allocated_ip`; the local folder is read via `task.context.local_folder`.

#### Scenario: Submitted jobs are initially TO_DO before nodes exist
- **WHEN** four jobs are submitted via `_submit_async` before any node is added
- **THEN** all four tasks have status `TO_DO` in the database

#### Scenario: Jobs are scheduled across both nodes
- **WHEN** the daemon is running and both nodes are added
- **THEN** all four tasks transition to `DONE` within 30 seconds
- **AND** the set of `allocated_ip` values across the four tasks is exactly `{"<ipA>", "<ipB>"}`
- **AND** no single node received all four tasks (the 0:4 / 4:0 split is rejected)

#### Scenario: Output files are downloaded and match input
- **WHEN** a task reaches `DONE`
- **THEN** the file `<local_folder>/1.input.out` exists
- **AND** its content matches the `1.input` payload submitted for that job

#### Scenario: Soft-remove deletes nodes when no RUNNING tasks remain
- **WHEN** both nodes are removed via `_manage_node_async(["<host>:<port>", "--remove-soft", ...])` after all tasks are `DONE`
- **THEN** `_remove_node_soft` queries `list_ids_by_ip_and_status(ip, RUNNING)`, finds it empty, and removes the node row
- **AND** `uow.nodes.list_all()` returns an empty list

#### Scenario: Engine script is deployed to each remote machine
- **WHEN** `_add_node` runs for each of the two nodes
- **THEN** `setup_node` deploys `run.sh` to the remote engines directory at `{remote_engines_dir}/test_shell/run.sh` on each container

#### Scenario: Allocator logs each task placement
- **WHEN** the allocator places a task on a machine
- **THEN** a debug log record with `[AllocateTask][_try_allocate_to_machine][ALLOCATED]` and the `task_id` and `ip` is emitted
- **AND** the captured `log_records` fixture contains one such record per task_id with both node IPs represented

#### Scenario: Task lifecycle transitions are correct
- **WHEN** a task is first created via `_submit_async`
- **THEN** its status is `TO_DO`
- **WHEN** the orchestrator allocates and starts it
- **THEN** its status transitions to `RUNNING`
- **WHEN** the orchestrator detects completion and downloads results
- **THEN** its status transitions to `DONE`