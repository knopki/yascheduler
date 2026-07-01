## ADDED Requirements

### Requirement: Live Hetzner cloud-provider E2E test

The project SHALL provide an opt-in, credentials-gated, real-cloud end-to-end test at
`tests/e2e/test_hetzner_live.py` that exercises the full autoscale → allocate → download
→ idle-deallocate happy path against a **real** Hetzner Cloud account. The test SHALL
drive the real entrypoint code paths (`make_daemon` from `entrypoints/di.py`,
`_submit_async` from `entrypoints/cli/submit.py`) and assert via `uow_factory` — it SHALL
NOT bypass the orchestrator, the cloud provisioner, the SSH layer, or the persistence
layer.

The test SHALL be OFF by default and SHALL run ONLY when both of these environment
variables are set:

- `YASCHEDULER_TEST_HETZNER` — equal to the literal string `1` (the deliberate opt-in
  gate);
- `YASCHEDULER_CLOUDS_HETZNER_TOKEN` — a non-empty Hetzner API token.

If either is absent, the test SHALL `pytest.skip(...)` with a message naming the missing
variable. The test SHALL carry the existing `e2e` marker (auto-applied by
`tests/e2e/conftest.py::pytest_collection_modifyitems` for files under `tests/e2e/`); the
project SHALL NOT add any new pytest marker for this test — the gate is purely
env-based. The default `pytest` / CI `-m e2e` run SHALL collect and skip the test
(`pytest.skip` is not a failure) and SHALL make no Hetzner API call.

The provider image/size knobs SHALL be overridable via environment variables with cheap
defaults:

- `YASCHEDULER_CLOUDS_HETZNER_LOCATION` (default `hel1`);
- `YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE` (default `cx23`);
- `YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME` (default `debian-13`).

The test SHALL provide a session-scoped `hetzner_config` fixture (defined in the test
file, NOT in the shared `tests/e2e/conftest.py`) that depends ONLY on session-scoped
shared fixtures (`postgres_container`, `_db_config`, `_init_schema`) — it SHALL NOT
depend on `ssh_pool` (Hetzner provisions its own VM) and SHALL NOT depend on the
function-scoped `uow_factory` or `log_records` (a session fixture depending on
function-scoped fixtures raises pytest `ScopeMismatch`). The fixture SHALL write a temp
INI containing the `[db]`, `[local]` (with `cloud_package_upgrade = false`), `[remote]`,
and `[engine.test_shell]` sections (same shape as the static-node `e2e_config` fixture)
plus a `[clouds]` section with: `hetzner_token` (from env), `hetzner_max_nodes = 1`,
`hetzner_server_type` (from env/default), `hetzner_location` (from env/default),
`hetzner_image_name` (from env/default), and `hetzner_idle_tolerance` set to a small
value (start near 5; raise toward 10 if the deallocate window proves too tight). The
fixture SHALL set `YASCHEDULER_CONF_PATH` to the temp INI for the test duration and
return the parsed `Config`. `connect_grace` SHALL NOT be set in the INI (it is not an
INI-parsed key; the `ConfigCloudHetzner` DTO default applies and is ample because
`cloud_package_upgrade = false` skips the slow `apt-get upgrade`).

The test scenario SHALL be:

1. **Start daemon**: `orchestrator = await make_daemon(hetzner_config)`; start it as a
   background `asyncio.Task` via `orchestrator.start()`. The test SHALL NOT call
   `run_daemon`.
2. **Submit jobs**: submit TWO tasks via `_submit_async(["<script>", "--config",
   "<ini_path>"])`, each in its own temp CWD holding a distinct `1.input` payload,
   capturing `task_id` from stdout.
3. **Assert queued**: assert both tasks are `TO_DO` before any node exists.
4. **Assert autoscale**: poll `uow.nodes.list_all()` until a node row with
   `cloud == "hetzner"` appears (the orchestrator provisioned a VM); record its IP into
   `observed_ips`; timeout at least 600 seconds.
5. **Wait for completion**: poll until both tasks reach `DONE`, capturing each task's
   `RUNNING` snapshot (`allocated_ip`); timeout at least 600 seconds.
6. **Assert outputs**: for each task, assert `status == DONE`, `context.error is None`,
   `context.local_folder` is set, and `<local_folder>/1.input.out` exists with content
   matching the per-job payload.
7. **Assert tasks ran on cloud nodes**: assert each task's `allocated_ip` is the IP of
   some `cloud == "hetzner"` node observed in the DB during the test (proves both ran on
   real Hetzner VMs). The test SHALL NOT assert both `allocated_ip` values are identical:
   with `max_nodes = 1` the idle-deallocate loop MAY provision a second VM for the second
   task if the deallocate window wins the race against the allocator (see design Risks);
   that outcome is non-fatal and is tuned via `hetzner_idle_tolerance`, not by asserting a
   single shared IP.
8. **Assert cloud-path logs**: grep the captured `log_records` for an
   `[AllocateTask][allocate_task][CLOUD_DONE]` debug record (emitted by
   `_persist_node_with_cleanup` on the `yascheduler.application.allocate_task` logger)
   whose `ip=` matches the provisioned node and whose `provider=hetzner`, and for a
   `[deallocate_node][CLOUD_DELETE]` debug record (emitted by `deallocate_node` on the
   `yascheduler.application.deallocate_nodes` logger) whose `ip=` and `cloud=hetzner`
   reference the provisioned node. Both markers are on `yascheduler.*` module loggers
   and therefore capturable by the `log_records` fixture (which attaches to the
   `"yascheduler"` logger only); the test SHALL NOT assert on the `CREATED <ip>` line or
   any `[CloudProvisionerImpl]` line, which are emitted on the top-level `"Orchestrator"`
   logger and are not visible to `log_records`.
9. **Assert idle deallocation (strong)**: poll `uow.nodes.list_all()` until the
   `cloud == "hetzner"` node row is gone (the idle-deallocate loop fired); timeout at
   least `idle_tolerance + 120` seconds. THEN poll `find_srv(client, ip)` (Hetzner API)
   until it returns `None`, proving the billed VM is actually deleted; this SHALL be a
   separate, explicit assertion (DB-row removal alone is insufficient).
10. **Guaranteed cleanup with loud-fail-on-leak**: in a `finally` block, the test SHALL
    (a) call `orchestrator.stop()` and await the background task best-effort, and (b) for
    every IP in `observed_ips`, call `hetzner_delete_node` to delete the VM. After each
    delete attempt, the test SHALL call `find_srv(client, ip)`; if the call raised OR
    `find_srv` still returns the server, the test SHALL `pytest.fail(...)` with a message
    of the form naming the leaked IP (e.g. `Hetzner VM <ip> was NOT deleted — manual
    cleanup required`) and emit an ERROR log with the same IP. The project SHALL NOT
    implement any name-prefix "sweep" of unrelated servers (it is unsafe under parallel
    runs and useless after a hard process kill, which is the only case `finally` does not
    cover). Cleanup deletion calls SHALL be best-effort across multiple IPs (one failure
    does not skip remaining deletion attempts) BUT a failure to actually delete a VM MUST
    surface as a test failure, not be swallowed.

Status assertions SHALL use `yascheduler.domain.TaskStatus`. The `hetzner_config`
fixture SHALL reuse a fresh keys_dir so the daemon generates its own SSH key
(`get_or_create_ssh_key`) registered into the Hetzner project by `get_ssh_key_id`; the
test SHALL NOT reuse the static-node `ssh_pool` keypair. The test module SHALL import
`hcloud` lazily inside helpers (only after the gate passes) so module collection succeeds
even when the optional `hcloud` extra is not installed.

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
- **AND** the temp INI contains `cloud_package_upgrade = false` under `[local]` and does NOT contain `connect_grace` as a key

#### Scenario: Daemon autoscales by creating exactly one Hetzner node
- **WHEN** the daemon is running with `hetzner_max_nodes = 1` and two `TO_DO` jobs exist and no free machine is available
- **THEN** the orchestrator provisions exactly one `cloud == "hetzner"` node via `hetzner_create_node`
- **AND** `uow.nodes.list_all()` returns exactly one node whose `cloud == "hetzner"` within 600 seconds

#### Scenario: Both jobs run to DONE on provisioned cloud node(s) and outputs are downloaded
- **WHEN** the Hetzner node has been provisioned and enabled
- **THEN** both tasks transition through `RUNNING` to `DONE` within 600 seconds
- **AND** each task's `allocated_ip` is the IP of a `cloud == "hetzner"` node observed during the test
- **AND** the test does NOT require both `allocated_ip` values to be identical (a second VM provisioned by the idle-deallocate race is non-fatal)
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
