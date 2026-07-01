# Explore Brief — add-hetzner-live-e2e

## Problem
Cloud provisioning path (autoscale → allocate → download → idle-deallocate) has **no
e2e coverage**. Existing e2e (`test_full_cycle.py`) exercises only static-node lifecycle.
Cloud adapters + `CloudProvisionerImpl.allocate` + `_setup_vm` + `deallocate_node` are
validated only by unit tests with doubles. Real provider API, real VMs, cloud-init,
`setup_node`, idle-deallocate are untested. Hetzner is manually confirmed working.

## Rejected alternatives
- **VCR/responses mocking hcloud HTTP** — SDK wiring is thin, already unit-mocked; does
  not catch the real glue (cloud-init schema, image renames, platform-match, SSH boot).
- **API-only smoke (`servers.get_all()`)** — validates token/quota only, not provisioning.
- **Hybrid (smoke + full)** — smoke adds noise without testing glue; only full path has value.
- **Local Hetzner API mock** — no mature Hetzner API mock exists.
- **Per-`ConfigCloud*` `package_upgrade` field** — wrong: the `package_upgrade=True`
  hardcode is ONE place in `CloudProvisionerImpl._get_cloud_config_data`, cloud-agnostic.
  Knob belongs where the hardcode is → `LocalSettings` field read by the manager.

## Final approach (decisions locked with user)
| Axis | Decision |
|---|---|
| Scenario | cold-start 0→1; 2 tasks; `max_nodes=1`; both tasks DONE on the single node |
| Machine | `cx23` / `hel1` / `debian-13` (env-overridable) |
| Gate | env-only: `YASCHEDULER_TEST_HETZNER=1` AND non-empty `YASCHEDULER_CLOUDS_HETZNER_TOKEN`; else `pytest.skip` naming the missing var |
| Marker | NONE new — test is `e2e` (auto-applied by conftest); gate is env-only |
| Override envs | `YASCHEDULER_CLOUDS_HETZNER_LOCATION` / `_SERVER_TYPE` / `_IMAGE_NAME` |
| idle_tolerance | spec gives guidance (~5, raise toward ~10 if deallocate window too tight), NOT a hardcoded constant |
| package_upgrade | NEW knob: `LocalSettings.cloud_package_upgrade: bool = True`; `[local] cloud_package_upgrade`; `_get_cloud_config_data` reads `self.local_config.cloud_package_upgrade`; test sets `false` (skips apt-upgrade → default `connect_grace=60` is ample) |
| Deletion assertion | STRONG: DB node-row gone AND `find_srv(ip) is None` (poll Hetzner API) |
| Cleanup | `finally` only; observed-IP `hetzner_delete_node`; NO sweep (useless after hard crash, conflicts with parallel runs) |
| Leak alarm | if delete raises OR post-delete `find_srv(ip) is not None` → `pytest.fail(...)` with IP in the message + ERROR log |
| CI | untouched (auto-skip on absent creds) |

## Cross-module data flows
- `make_daemon(hetzner_config)` → `CloudProvisionerImpl` built from `config.clouds`
  (filter `max_nodes>0` + resolved adapter).
- `_allocator_producer` → `allocate_task` → no free machine →
  `clouds.select_provider(platforms, counts)` → `clouds.allocate("hetzner")` →
  `hetzner_create_node` (hcloud SDK) → `_setup_vm` (SSH/cloud-init/setup_node) →
  `_persist_node_with_cleanup` → emits `[AllocateTask][allocate_task][CLOUD_DONE]
  task_id=%s ip=%s provider=%s` (allocate_task.py:413).
- idle → `_deallocator_producer` → `deallocate_nodes` (disable) → `deallocate_node` →
  emits `[deallocate_node][CLOUD_DELETE] ip=%s cloud=%s` (deallocate_nodes.py:76) →
  `clouds.deallocate("hetzner", ip)` → `hetzner_delete_node` (find_srv + delete).

## Log-capture constraint (verified)
`log_records` attaches to the `"yascheduler"` logger only. `[CLOUD_DONE]` and
`[CLOUD_DELETE]` are on `yascheduler.application.*` module loggers → CAPTURED.
`CREATED <ip>` / `[CloudProvisionerImpl]` are on the top-level `"Orchestrator"` logger
(child of root) → NOT captured. Test asserts only the two capturable markers.

## Open questions
All resolved (see Decisions). None outstanding.
