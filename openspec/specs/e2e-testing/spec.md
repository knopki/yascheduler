# End-to-end testing

## Purpose

End-to-end test infrastructure and full-cycle tests that validate the scheduler's complete task lifecycle against real PostgreSQL and SSH containers.

## Requirements

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

#### Scenario: Persistence fixtures provide empty database per test
- **WHEN** two E2E tests run sequentially and the first inserts a node via `uow_factory`
- **THEN** the second test sees zero nodes (the `pg_conn` teardown TRUNCATEs both tables)

#### Scenario: log_records fixture captures yascheduler debug logs for the test duration
- **WHEN** the `log_records` fixture is active and the orchestrator emits a debug log
- **THEN** the log record's `getMessage()` is present in the captured list
- **AND** after the test, the handler is removed from the `"yascheduler"` logger

### Requirement: Test engine script
The project SHALL provide a shell script `run.sh` as the test engine executable. The script SHALL sleep for 3 seconds then copy `1.input` to `1.input.out` in the current working directory. The script SHALL be executable and use `#!/bin/sh` shebang.

#### Scenario: Test engine script copies input to output
- **WHEN** `run.sh` is executed with `1.input` present in the working directory
- **THEN** it sleeps for 3 seconds, then copies `1.input` to `1.input.out`

### Requirement: Full cycle E2E test

The project SHALL provide a test in `tests/e2e/test_full_cycle.py` that
exercises the complete scheduler lifecycle through the application's real
entrypoint code paths (not direct repository/UoW bypass):

1. **Start daemon**: Create the orchestrator via `make_daemon(config)` and
   start it as a background `asyncio.Task` via `orchestrator.start()`. The test
   SHALL NOT call `run_daemon` (which registers signal handlers unsuitable
   for a test loop).
2. **Submit jobs**: Submit four tasks by calling the internal async entrypoint
   `_submit_async(argv)` from `entrypoints/cli/submit.py` (the async core of
   the `yasubmit` CLI). Each call SHALL pass `["<script_path>", "--config",
   "<ini_path>"]` where `<script_path>` is a temp file containing
   `ENGINE=test_shell` and `LABEL=job_N`, and the current working directory is
   a temp dir containing a `1.input` file with content `"hello e2e N"` (per-job
   CWD isolation via `monkeypatch.chdir`). The test SHALL capture `task_id`
   from the entrypoint's stdout (`print(str(task_id))`).
3. **Assert queued**: After all four submissions, read all four tasks via
   `uowFactory()` and assert each has status `TO_DO`.
4. **Add nodes**: Add two nodes by calling the internal async entrypoint
   `_manage_node_async(argv)` from `entrypoints/cli/manage_node.py` (the async
   core of the `yasetnode` CLI).
5. **Wait for completion**: Poll until all four tasks reach `DONE` (timeout ≥
   60s), capturing each task's `RUNNING` snapshot node IP via
   `uow.nodes.get_by_id(t.allocated_node_id).ip` (was `task.allocated_ip`,
   which is removed — see the `domain-entities` delta).
6. **Assert per-task state**: For each task, read it via `uow.tasks.get(id)`,
   resolve its node via `uow.nodes.get_by_id(task.allocated_node_id)`, and
   assert.
7. **Assert completion and outputs**: For each task, assert `status == DONE`,
   `task.error is None` (was `context.error is None` — see the
   `domain-entities` delta), `task.local_folder` is set (was
   `context.local_folder`), and the output file
   `<local_folder>/1.input.out` exists with content matching the per-job
   `1.input` payload.
8. **Assert distribution**: Collect node IPs from all four tasks (via
   `uow.nodes.get_by_id(t.allocated_node_id).ip`). Assert the set of allocated
   node IPs equals `{"<ipA>", "<ipB>"}` (both nodes were used) AND that no
   single node received all four tasks (reject the 0:4 / 4:0 monopoly case —
   those indicate one node never accepted work).
9. **Assert scheduling activity in logs**: Grep the captured `log_records`
   for `[AllocateTask][_try_allocate_to_machine][ALLOCATED]` entries and
   assert one appears for each of the four `task_id`s, and that both node IPs
   appear among the logged `ip=` values.
10. **Remove nodes (soft)**: Remove both nodes by calling
    `_manage_node_async(["<host>:<port>", "--remove-soft", "--config",
    "<ini_path>"])` once per container. This exercises the real
    `_remove_node_soft` path which, with no RUNNING tasks, takes the
    `uow.nodes.remove(ip)` branch.
11. **Assert nodes removed**: After both soft-remove calls return, assert
    `uow.nodes.list_all()` returns an empty list.
12. **Stop daemon**: In a `finally` block, call `orchestrator.stop()` and
    `asyncio.wait_for(orch_task, timeout=10)`.

Status assertions SHALL use `yascheduler.domain.TaskStatus`. The task's
allocated node IP is read via `uow.nodes.get_by_id(task.allocated_node_id).ip`
(the `Task` entity carries `allocated_node_id`, not `allocated_ip` — the
latter is removed). The local folder is read via `task.local_folder` (was
`task.context.local_folder`). The error field is read via `task.error` (was
`task.context.error`). No `task.context` references exist in the test (the
`TaskContext` value object is removed — see the `domain-entities` delta).

#### Scenario: Submitted jobs are initially TO_DO before nodes exist
- **WHEN** four jobs are submitted via `_submit_async` before any node is added
- **THEN** all four tasks have status `TO_DO` in the database

#### Scenario: Jobs are scheduled across both nodes
- **WHEN** the daemon is running and both nodes are added
- **THEN** all four tasks transition to DONE; the set of node IPs (resolved via `uow.nodes.get_by_id(t.allocated_node_id).ip`) across the four tasks is exactly `{"<ipA>", "<ipB>"}` (both nodes used, no monopoly)

#### Scenario: Each DONE task has error None and local_folder set
- **WHEN** a task reaches DONE
- **THEN** `task.error is None` (success path; was `context.error is None`) and `task.local_folder` is set (was `context.local_folder`); the output file exists at `<task.local_folder>/1.input.out` matching the per-job payload

### Requirement: Live Hetzner cloud-provider E2E test

The project SHALL provide an opt-in, credentials-gated, real-cloud end-to-end test at
`tests/e2e/test_hetzner_live.py` that exercises the full autoscale → allocate → download
→ idle-deallocate happy path against a **real** Hetzner Cloud account. The test SHALL
drive the real entrypoint code paths (`make_daemon` from `entrypoints/di.py`,
`_submit_async` from `entrypoints/cli/submit.py`) and assert via `uow_factory` — it SHALL
NOT bypass the orchestrator, the cloud provisioner, the SSH layer, or the persistence
layer.

The test SHALL be OFF by default and SHALL run ONLY when both `YASCHEDULER_TEST_HETZNER`
(literal `1`, the opt-in gate) and `YASCHEDULER_CLOUDS_HETZNER_TOKEN` (a non-empty Hetzner
API token) are set. If either is absent, the test SHALL `pytest.skip(...)` naming the
missing variable; no Hetzner API call is made. The test carries the existing `e2e` marker
(auto-applied for files under `tests/e2e/`); the project SHALL NOT add any new pytest
marker — the gate is purely env-based.

The provider image/size knobs SHALL be overridable via environment variables with cheap
defaults: `YASCHEDULER_CLOUDS_HETZNER_LOCATION` (default `hel1`),
`YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE` (default `cx23`),
`YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME` (default `debian-13`).

The test SHALL provide a session-scoped `hetzner_config` fixture (defined in the test
file, NOT in the shared `tests/e2e/conftest.py`) depending ONLY on session-scoped shared
fixtures (`postgres_container`, `_db_config`, `_init_schema`) — it SHALL NOT depend on
`ssh_pool`, `uow_factory`, or `log_records` (session-on-function raises pytest
`ScopeMismatch`). The fixture writes a temp INI with `[db]`, `[local]`, `[remote]`,
`[engine.test_shell]`, plus a `[clouds]` section (`hetzner_token`, `hetzner_max_nodes = 1`,
`hetzner_server_type`, `hetzner_location`, `hetzner_image_name`, `hetzner_idle_tolerance`
near 5–10, `hetzner_package_upgrade = false`), sets `YASCHEDULER_CONF_PATH` for the test
duration, and returns the parsed `Config`. `connect_grace` is NOT set in the INI (the
`ConfigCloudHetzner` DTO default applies). Status assertions SHALL use
`yascheduler.domain.TaskStatus`. The fixture reuses a fresh `keys_dir` so the daemon
generates its own SSH key; the test SHALL NOT reuse the static-node `ssh_pool` keypair.
The test module SHALL import `hcloud` lazily inside helpers (only after the gate passes)
so module collection succeeds even when `hcloud` is not installed.

The test scenario SHALL be:

1. **Start daemon**: `orchestrator = await make_daemon(hetzner_config)`; start it as a
   background `asyncio.Task` via `orchestrator.start()` (the test SHALL NOT call
   `run_daemon`).
2. **Submit jobs**: submit TWO tasks via `_submit_async(["<script>", "--config",
   "<ini_path>"])`, each in its own temp CWD holding a distinct `1.input` payload,
   capturing `task_id` from stdout.
3. **Assert queued**: both tasks are `TO_DO` before any node exists.
4. **Assert autoscale**: poll `uow.nodes.list_all()` until a `cloud == "hetzner"` node row
   appears; record its IP into `observed_ips`; timeout ≥ 600s.
5. **Wait for completion**: poll until both tasks reach `DONE`, capturing each task's
   `RUNNING` snapshot node IP via `uow.nodes.get_by_id(task.allocated_node_id).ip` (was
   `task.allocated_ip`); timeout ≥ 600s.
6. **Assert outputs**: for each task, assert `status == DONE`, `task.error is
   None` (was `context.error is None`), `task.local_folder` is set (was
   `context.local_folder`), and `<local_folder>/1.input.out` exists matching
   the per-job payload.
7. **Assert tasks ran on cloud nodes**: each task's allocated node IP (read
   via `uow.nodes.get_by_id(task.allocated_node_id).ip`, was
   `task.allocated_ip`) is the IP of some `cloud == "hetzner"` node observed
   during the test. The test SHALL NOT assert both allocated node IPs are
   identical (with `max_nodes = 1` the idle-deallocate loop MAY provision a
   2nd VM; that race is non-fatal).
8. **Assert cloud-path logs**: grep `log_records` for an
   `[AllocateTask][allocate_task][CLOUD_DONE]` record whose `ip=` matches the provisioned
   node and `provider=hetzner`, and a `[deallocate_node][CLOUD_DELETE]` record whose `ip=`
   and `cloud=hetzner` reference the node. The test SHALL NOT assert on the `CREATED <ip>`
   line or any `[CloudProvisionerImpl]` line (those are on the top-level `"Orchestrator"`
   logger, invisible to `log_records`).
9. **Assert idle deallocation (strong)**: poll `uow.nodes.list_all()` until the
   `cloud == "hetzner"` node row is gone (timeout ≥ `idle_tolerance + 120`s). THEN poll
   `find_srv(client, ip)` (Hetzner API) until it returns `None`, proving the billed VM is
   actually deleted — a separate, explicit assertion (DB-row removal alone is
   insufficient).
10. **Guaranteed cleanup with loud-fail-on-leak**: in a `finally` block, the test SHALL
    (a) call `orchestrator.stop()` and await the background task best-effort, and (b) for
    every IP in `observed_ips`, call `hetzner_delete_node`. After each delete attempt, call
    `find_srv(client, ip)`; if it raised OR still returns the server, the test SHALL
    `pytest.fail(...)` naming the leaked IP and emit an ERROR log. The project SHALL NOT
    implement any name-prefix "sweep" of unrelated servers. Cleanup deletion calls SHALL be
    best-effort across multiple IPs BUT a failure to actually delete a VM MUST surface as a
    test failure, not be swallowed.

Status assertions SHALL use `yascheduler.domain.TaskStatus`. The task's
allocated node IP is read via `uow.nodes.get_by_id(task.allocated_node_id).ip`
(the `Task` entity carries `allocated_node_id`, not `allocated_ip`). The
local folder is read via `task.local_folder` (was `task.context.local_folder`).
The error field is read via `task.error` (was `task.context.error`). No
`task.context` references exist in the test.

#### Scenario: Test is skipped when the opt-in gate is absent
- **WHEN** `YASCHEDULER_TEST_HETZNER` is unset (or not equal to `1`) and the test is collected
- **THEN** the test calls `pytest.skip(...)` with a message naming `YASCHEDULER_TEST_HETZNER`
- **AND** no Hetzner API call is made and no VM is created

#### Scenario: Test is skipped when the token is absent
- **WHEN** `YASCHEDULER_TEST_HETZNER == "1"` but `YASCHEDULER_CLOUDS_HETZNER_TOKEN` is unset or empty
- **THEN** the test calls `pytest.skip(...)` with a message naming `YASCHEDULER_CLOUDS_HETZNER_TOKEN`
- **AND** no Hetzner API call is made and no VM is created

#### Scenario: No new pytest marker is added
- **WHEN** `pyproject.toml [tool.pytest.ini_options].markers` is inspected
- **THEN** the list contains exactly the pre-existing `unit`, `integration`, `e2e` markers (no `cloud` marker)
- **AND** the test carries only the `e2e` marker

#### Scenario: Module collects without the hcloud extra installed
- **WHEN** `hcloud` is not installed and the test module is collected under `-m e2e` with the gate unset
- **THEN** collection succeeds and the test skips without an ImportError

#### Scenario: hetzner_config fixture honors override env vars and excludes ssh_pool
- **WHEN** the `hetzner_config` fixture is resolved with `YASCHEDULER_CLOUDS_HETZNER_LOCATION`, `YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE`, and `YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME` unset
- **THEN** the resulting `Config.clouds` contains exactly one `ConfigCloudHetzner` with `max_nodes == 1`, `token == $YASCHEDULER_CLOUDS_HETZNER_TOKEN`, `server_type == "cx23"`, `location == "hel1"`, and `image_name == "debian-13"`
- **AND** when each override env var is set, the corresponding `ConfigCloudHetzner` field takes the env value
- **AND** the session-scoped `hetzner_config` fixture depends only on session-scoped fixtures and does NOT depend on `ssh_pool`, `uow_factory`, or `log_records`
- **AND** the temp INI contains `hetzner_package_upgrade = false` under `[clouds]` and does NOT contain `connect_grace` as a key

#### Scenario: Daemon autoscales by creating exactly one Hetzner node
- **WHEN** the daemon is running with `hetzner_max_nodes = 1` and two `TO_DO` jobs exist and no free machine is available
- **THEN** the orchestrator provisions exactly one `cloud == "hetzner"` node via `hetzner_create_node`
- **AND** `uow.nodes.list_all()` returns exactly one node whose `cloud == "hetzner"` within 600 seconds

#### Scenario: Both jobs run to DONE on provisioned cloud node(s) and outputs are downloaded
- **WHEN** the Hetzner node has been provisioned and enabled
- **THEN** both tasks transition through `RUNNING` to `DONE` within 600 seconds
- **AND** each task's allocated node IP (read via `uow.nodes.get_by_id(task.allocated_node_id).ip`) is the IP of a `cloud == "hetzner"` node observed during the test
- **AND** the test does NOT require both allocated node IPs to be identical (a second VM provisioned by the idle-deallocate race is non-fatal)
- **AND** `<local_folder>/1.input.out` exists for each task with content matching its `1.input` payload

#### Scenario: Idle node is deallocated, the VM is deleted, and deletion is verified via the API
- **WHEN** both tasks are `DONE` and the node has been idle for `hetzner_idle_tolerance`
- **THEN** `deallocate_nodes` disables the node and `deallocate_node` calls `clouds.deallocate("hetzner", ip)`
- **AND** the `cloud == "hetzner"` node row disappears from `uow.nodes.list_all()` within `idle_tolerance + 120` seconds
- **AND** the test additionally polls `find_srv(client, ip)` until it returns `None` (strong deletion assertion)
- **AND** the captured `log_records` contain a `[deallocate_node][CLOUD_DELETE]` record with `cloud=hetzner` referencing the node IP

#### Scenario: Cloud provisioning-success log is captured via CLOUD_DONE
- **WHEN** `_persist_node_with_cleanup` commits the final cloud node row after `clouds.allocate` succeeds
- **THEN** the captured `log_records` contain an `[AllocateTask][allocate_task][CLOUD_DONE]` debug record whose `ip=` matches the provisioned node's IP and whose `provider=hetzner`
- **AND** the test does NOT assert on the `CREATED <ip>` line or any `[CloudProvisionerImpl]` line (those are on the `"Orchestrator"` logger, invisible to `log_records`)

#### Scenario: Failed VM deletion fails the test loudly with the leaked IP
- **WHEN** the `finally` block's `hetzner_delete_node(ip)` raises OR a post-delete `find_srv(client, ip)` still returns the server
- **THEN** the test calls `pytest.fail(...)` with a message that includes the leaked IP
- **AND** emits an ERROR log naming the IP
- **AND** does NOT swallow the failure (the test reports a failure, not a pass)

#### Scenario: Cleanup runs even when an assertion fails mid-test
- **WHEN** any assertion in steps 2–9 fails (or an exception is raised) after a Hetzner VM was created and its IP was recorded in `observed_ips`
- **THEN** the `finally` block still calls `hetzner_delete_node` for each recorded IP before the test reports its failure

#### Scenario: Each DONE task has error None and local_folder set (hetzner)
- **WHEN** a task reaches DONE on a hetzner-provisioned node
- **THEN** `task.error is None` (was `context.error is None`) and `task.local_folder` is set (was `context.local_folder`); the output file exists at `<task.local_folder>/1.input.out` matching the per-job payload
- **AND** no `TaskContext`, `task.context`, or `context.error`/`context.local_folder` references are present in the test (the test reads `task.error`, `task.local_folder`, and resolves node IP via `uow.nodes.get_by_id(task.allocated_node_id).ip`)