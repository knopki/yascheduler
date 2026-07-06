# Spec Delta: e2e-testing

## MODIFIED Requirements

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

#### Scenario: No TaskContext or task.context references in e2e tests
- **WHEN** `tests/e2e/test_full_cycle.py` is inspected for `TaskContext`, `task.context`, or `context.error`/`context.local_folder` references
- **THEN** none are present; the test reads `task.error`, `task.local_folder`, and resolves node IP via `uow.nodes.get_by_id(task.allocated_node_id).ip`

### Requirement: Live Hetzner cloud-provider E2E test

The project SHALL provide a live Hetzner cloud-provider E2E test in
`tests/e2e/test_hetzner_live.py` exercising the autoscale path against real
Hetzner VMs. (The existing requirement body is unchanged except for the
typed-field read updates noted below. This delta modifies only the assertion
reads; the test scenario steps, gating, fixture, and assertions on node
distribution are unchanged.)

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

Status assertions SHALL use `yascheduler.domain.TaskStatus`. The task's
allocated node IP is read via `uow.nodes.get_by_id(task.allocated_node_id).ip`
(the `Task` entity carries `allocated_node_id`, not `allocated_ip`). The
local folder is read via `task.local_folder` (was `task.context.local_folder`).
The error field is read via `task.error` (was `task.context.error`). No
`task.context` references exist in the test.

#### Scenario: Hetzner autoscale provisions a cloud node
- **WHEN** the daemon is running and two tasks are submitted with no pre-existing nodes
- **THEN** a `cloud == "hetzner"` node appears in `uow.nodes.list_all()` and both tasks transition to DONE

#### Scenario: Each DONE task has error None and local_folder set (hetzner)
- **WHEN** a task reaches DONE on a hetzner-provisioned node
- **THEN** `task.error is None` (was `context.error is None`) and `task.local_folder` is set (was `context.local_folder`); the output file exists at `<task.local_folder>/1.input.out` matching the per-job payload

#### Scenario: No TaskContext or task.context references in hetzner e2e test
- **WHEN** `tests/e2e/test_hetzner_live.py` is inspected for `TaskContext`, `task.context`, or `context.error`/`context.local_folder` references
- **THEN** none are present; the test reads `task.error`, `task.local_folder`, and resolves node IP via `uow.nodes.get_by_id(task.allocated_node_id).ip`