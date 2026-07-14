# End-to-end testing

## Purpose

End-to-end test infrastructure and full-cycle tests that validate the scheduler's complete task lifecycle against real PostgreSQL and SSH containers.

## Requirements

### Requirement: E2E test fixtures
The project SHALL provide session-scoped and function-scoped pytest fixtures that set up a complete test environment:
- Session-scoped PostgreSQL container (testcontainers) with schema applied
- Session-scoped `ssh_pool` fixture: a list of TWO SSH containers (testcontainers `openssh-server`) started from ONE generated keypair (shared `PUBLIC_KEY` env). Each container yields its own `get_container_host_ip()` and mapped port 2222. Both containers share the same `username`.
- Session-scoped config fixture that creates a temp directory with minimal INI file (`[db]` + `[engine.test_shell]`), test engine script (`run.sh`) in `data/engines/test_shell/`, and a SINGLE SSH private key symlink in `data/keys/` (the shared keypair used by both `ssh_pool` containers)
- Session-scoped `Config` instance parsed from the generated INI
- Function-scoped persistence fixtures: a raw pg8000 connection (`pg_conn`), a single-worker executor, and a `uow_factory` callable returning a `PostgresUnitOfWork`. Teardown SHALL `TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE` via `pg_conn`.
- Function-scoped `log_records` fixture: an in-memory `logging.Handler` subclass that appends every `LogRecord` to a list, attached to the `"yascheduler"` logger at DEBUG level for the test duration and removed in teardown. The fixture SHALL expose the captured records so tests can assert on trace-record structured fields (block marker and structured fields exposed as programmatic attributes on each record) instead of parsing the rendered message string.
- Function-scoped orchestrator fixture that creates but does not start an `Orchestrator` instance

The `YASCHEDULER_CONF_PATH` environment variable SHALL be set to the generated INI path for the duration of the session.

#### Scenario: Config fixture provides valid Config with test engine
- **WHEN** the session-scoped config fixture is resolved
- **THEN** `config.engines` contains exactly one engine named `test_shell` with `spawn="{engine_path}/run.sh"`, `check_pname="sleep"`, `input_files=("1.input",)`, `output_files=("1.input.out",)`, `deployable` containing one `LocalFilesDeploy` pointing to `run.sh`

#### Scenario: Persistence fixtures provide empty database per test
- **WHEN** two E2E tests run sequentially and the first inserts a node via `uow_factory`
- **THEN** the second test sees zero nodes (the `pg_conn` teardown TRUNCATEs both tables)

#### Scenario: log_records fixture captures yascheduler trace records for the test duration
- **GIVEN** the `log_records` fixture is active
- **WHEN** the orchestrator emits a trace record via `YaLogger.trace()`
- **THEN** the captured record exposes the block marker as a programmatic attribute
- **AND** the captured record exposes the structured fields as a programmatic attribute
- **AND** after the test, the handler is removed from the `"yascheduler"` logger

#### Scenario: log_records fixture captures records via propagation from M-ID namespaced loggers
- **GIVEN** the `log_records` fixture attaches a handler to the `"yascheduler"` logger
- **WHEN** a descendant `yascheduler.M-APPLICATION-ALLOCATE` logger emits a trace record
- **THEN** the record propagates to the `"yascheduler"` parent logger and is present in the captured list

### Requirement: Test engine script
The project SHALL provide a shell script `run.sh` as the test engine executable. The script SHALL sleep for 3 seconds then copy `1.input` to `1.input.out` in the current working directory. The script SHALL be executable and use `#!/bin/sh` shebang.

#### Scenario: Test engine script copies input to output
- **WHEN** `run.sh` is executed with `1.input` present in the working directory
- **THEN** it sleeps for 3 seconds, then copies `1.input` to `1.input.out`

### Requirement: Full cycle E2E test

The project SHALL provide a test that exercises the complete scheduler lifecycle through the application's real entrypoint code paths (not direct repository/UoW bypass). The test SHALL:

- Submit multiple `test_shell` tasks and start the daemon.
- Add statically configured nodes then assert all tasks reach `DONE` with outputs downloaded.
- Assert tasks are distributed across both available nodes (no single-node monopoly).
- Assert scheduling activity is visible in captured `log_records` trace records (structured fields, not rendered-message substrings).
- Cleanly remove nodes and stop the daemon in teardown.

Status assertions SHALL use `yascheduler.domain.TaskStatus`. The test SHALL NOT reference `task.context`.

#### Scenario: Submitted jobs are initially TO_DO before nodes exist
- **WHEN** four jobs are submitted before any node is added
- **THEN** all four tasks have status `TO_DO` in the database

#### Scenario: Jobs are scheduled across both nodes
- **WHEN** the daemon is running and both nodes are added
- **THEN** all four tasks transition to `DONE` and are distributed across both available nodes (neither node received all four tasks)

#### Scenario: Each DONE task has error None and local_folder set
- **WHEN** a task reaches `DONE`
- **THEN** `task.error is None` and `task.local_folder` is set; the output file exists at `<task.local_folder>/1.input.out` matching the per-job payload

#### Scenario: Scheduling activity asserted via trace record structured fields
- **GIVEN** the daemon has allocated all four tasks across two nodes
- **WHEN** the captured `log_records` are inspected
- **THEN** there is one trace record with block marker `ALLOCATED` for each task
- **AND** the structured fields on those records expose `ip` values covering both node IPs

### Requirement: Live Hetzner cloud-provider E2E test

The project SHALL provide an opt-in, credentials-gated, real-cloud end-to-end test at `tests/e2e/test_hetzner_live.py` that exercises the full autoscale → allocate → download → idle-deallocate happy path against a real Hetzner Cloud account through real entrypoint code paths (`make_daemon`, the async entrypoint of yasubmit), not bypassing the orchestrator, cloud provisioner, SSH layer, or persistence layer.

The test SHALL be OFF by default, running only when both `YASCHEDULER_TEST_HETZNER=1` and `YASCHEDULER_CLOUDS_HETZNER_TOKEN` (non-empty) are set. Otherwise it SHALL `pytest.skip(...)` naming the missing variable; no Hetzner API call is made. The test carries only the `e2e` marker; the project SHALL NOT add any new pytest marker. The test module SHALL import `hcloud` lazily so collection succeeds without it.

Provider image/size SHALL be overridable via environment variables (`YASCHEDULER_CLOUDS_HETZNER_LOCATION`, `YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE`, `YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME`) with cheap defaults (`hel1`, `cx23`, `debian-13`).

The test SHALL provide a session-scoped `hetzner_config` fixture (in the test file, not conftest.py) depending only on session-scoped shared fixtures. The fixture writes a temp INI with `[db]`, `[local]`, `[remote]`, `[engine.test_shell]`, plus `[clouds]` (hetzner token, `hetzner_max_nodes = 1`, server_type/location/image_name, `hetzner_idle_tolerance` near 5–10, `hetzner_package_upgrade = false`), sets `YASCHEDULER_CONF_PATH` for the test duration, and returns the parsed `Config`. The fixture SHALL use a fresh `keys_dir` (daemon generates its own SSH key), NOT reuse the `ssh_pool` keypair, and NOT depend on `ssh_pool`, `uow_factory`, or `log_records`.

The test SHALL submit two tasks, start the daemon, wait for autoscale provisioning of a Hetzner node, wait for both tasks to reach `DONE` with outputs downloaded, assert the provisioning-success trace record (`CLOUD_DONE`) is present, and assert idle deallocation removes both the DB node row and the Hetzner VM (verified via `find_srv` API call), with a corresponding `CLOUD_DELETE` trace record. Cleanup SHALL be guaranteed in a `finally` block: stop the daemon and delete every provisioned VM. A failure to actually delete a VM MUST surface as a test failure.

Status assertions SHALL use `yascheduler.domain.TaskStatus`. The test SHALL NOT reference `task.context`.

#### Scenario: Test is skipped when the env gate is absent
- **WHEN** `YASCHEDULER_TEST_HETZNER` is unset (or not `1`), or `YASCHEDULER_CLOUDS_HETZNER_TOKEN` is unset or empty
- **THEN** the test calls `pytest.skip(...)` naming the missing variable
- **AND** no Hetzner API call is made and no VM is created

#### Scenario: Real Hetzner node is provisioned and both tasks complete
- **WHEN** the daemon is running with `hetzner_max_nodes = 1` and two `TO_DO` jobs exist
- **THEN** a `cloud == "hetzner"` node is provisioned within 600 seconds
- **AND** both tasks transition through `RUNNING` to `DONE` within 600 seconds
- **AND** each task has `status == DONE`, `error is None`, `local_folder` is set, and `<local_folder>/1.input.out` exists with the correct payload
- **AND** the captured `log_records` contain a trace record with block marker `CLOUD_DONE` whose structured fields expose the provisioned node IP and `cloud=hetzner`

#### Scenario: Idle node is deallocated and VM deletion verified via API
- **WHEN** both tasks are `DONE` and the node has been idle for `hetzner_idle_tolerance`
- **THEN** the `cloud == "hetzner"` node row disappears from the database within `idle_tolerance + 120` seconds
- **AND** polling `find_srv(client, ip)` eventually returns `None` (strong deletion assertion)
- **AND** the captured `log_records` contain a trace record with block marker `CLOUD_DELETE` whose structured fields expose `cloud=hetzner` and the node IP

#### Scenario: Failed VM deletion fails the test loudly
- **WHEN** the `finally` block's deletion attempt raises or a post-delete `find_srv` still returns the server
- **THEN** the test calls `pytest.fail(...)` naming the leaked IP and emits an ERROR log
- **AND** the failure is not swallowed

#### Scenario: Cleanup runs even when an assertion fails mid-test
- **WHEN** any assertion fails (or an exception is raised) after a Hetzner VM was created and its IP was recorded
- **THEN** the `finally` block still deletes each recorded IP before the test reports its failure
