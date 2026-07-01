## Why

The cloud provisioning path — autoscaling by creating cloud nodes, allocating tasks
onto them, collecting results, and deleting idle nodes — has **no e2e coverage**. The
existing e2e suite (`test_full_cycle.py`) only exercises the **static-node** lifecycle
(operator-added SSH containers). The full `allocate_task → CloudProvisionerImpl.allocate
→ _setup_vm → deallocate_node` chain, the real `hcloud` SDK, real VMs, cloud-init,
`setup_node`, and idle-deallocation are validated only by unit tests with doubles, so
the real integration **glue** — the part that breaks silently (SDK wording changes,
cloud-init schema, image renames, platform-match between engine and adapter) — is
unchecked. Hetzner is now manually confirmed working against a real account, making it
the first provider to gain a real e2e test and establish the harness pattern for the
rest.

A prerequisite obstacle: `CloudProvisionerImpl._get_cloud_config_data` hardcodes
`package_upgrade=True`, so every freshly-provisioned VM runs `apt-get upgrade` under
cloud-init — slow enough (60–180 s) to risk exceeding the `connect_grace` window and
abandoning the node (orphan VM with no DB row). This change also makes that flag
configurable so the test (and any operator who wants fast provisioning) can disable it.

## What Changes

- Add `tests/e2e/test_hetzner_live.py`: a real-Hetzner, opt-in e2e test exercising the
  minimal happy path — daemon with a `[clouds]` section allowing **max 1** Hetzner node
  + the existing primitive `test_shell` engine, two submitted jobs, autoscale node
  creation (cold-start 0→1), task allocation + result download, and idle-node deletion.
- Add an **env-only gate**: the test runs iff `YASCHEDULER_TEST_HETZNER == "1"` AND
  `YASCHEDULER_CLOUDS_HETZNER_TOKEN` is non-empty; otherwise it `pytest.skip`s with a
  message naming the missing variable. **No new pytest marker** — the test carries the
  existing `e2e` marker (auto-applied by `tests/e2e/conftest.py`); the gate is purely
  env-based and the test skips under the default CI/local run.
- Provider image/size knobs are env-overridable with cheap defaults:
  `YASCHEDULER_CLOUDS_HETZNER_LOCATION` (default `hel1`),
  `YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE` (default `cx23`),
  `YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME` (default `debian-13`); `max_nodes=1`.
- Add a `hetzner_config` session-scoped fixture (in the test file) that reuses the
  shared session-scoped `postgres_container`/`_db_config`/`_init_schema` fixtures only
  (NOT `ssh_pool` — Hetzner provisions its own VM; NOT the function-scoped
  `uow_factory`/`log_records`, which the test function consumes directly) and builds a
  temp INI with `[db]`, `[local]` (`cloud_package_upgrade = false`), `[remote]`,
  `[engine.test_shell]`, and `[clouds]`.
- Add a **guaranteed-cleanup** `finally` that deletes any Hetzner VM observed during the
  test by its IP via `hetzner_delete_node`, and **fails loudly** (with the IP in the
  message) if deletion fails or a post-delete `find_srv(ip)` still returns the server —
  no name-prefix sweep (useless after a hard crash, conflicts with parallel runs).
- Add a **strong** deletion assertion: the DB node row disappears AND `find_srv(ip)` is
  `None` (definitive proof the billed VM is gone).
- Make `package_upgrade` configurable: add `cloud_package_upgrade: bool = True` to
  `LocalSettings`; `_get_cloud_config_data` reads `self.local_config.cloud_package_upgrade`
  instead of hardcoding `True`. Default `True` preserves existing behavior.

No **BREAKING** changes. No public API, CLI, INI format (a new optional `[local]` key is
additive), or DB schema changes. The `test_shell` engine and the Hetzner provider code
itself are unchanged.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `e2e-testing`: add a requirement for an opt-in, env-gated, real-Hetzner e2e test
  covering the autoscale → allocate → download → idle-deallocate happy path, with the
  env gate/credentials contract, the `hetzner_config` fixture, the strong deletion
  assertion, and the loud-fail-on-leak cleanup obligation.
- `config-value-objects`: add the `cloud_package_upgrade: bool = True` field to
  `LocalSettings` and the corresponding `[local] cloud_package_upgrade` INI key.
- `cloud-provisioner`: `CloudProvisionerImpl._get_cloud_config_data` SHALL source the
  `package_upgrade` flag from `local_config.cloud_package_upgrade` instead of hardcoding
  `True`.

## Impact

- **Code**: new `tests/e2e/test_hetzner_live.py`; one field + `__post_init__` no-op on
  `LocalSettings` (`yascheduler/domain/settings.py`); one read in
  `CloudProvisionerImpl._get_cloud_config_data` (`yascheduler/infra/cloud/manager.py`);
  one `sec.getboolean(...)` line in `_parse_local_section`
  (`yascheduler/entrypoints/config_parser.py`). No production-code public-API change.
- **Dependencies**: optional. The test imports `hcloud` lazily inside helpers (only when
  the gate is set); `hcloud` is already an optional provider SDK. No new runtime
  dependency.
- **CI / local runs**: zero effect by default — the test skips when the gate env is
  unset. Operators set the two env vars to run it manually.
- **Cost**: capped at one `cx23`-class VM for the test duration (~minutes) when enabled;
  the loud-fail cleanup contract prevents silent orphan billing.
- **Specs**: `e2e-testing`, `config-value-objects`, `cloud-provisioner` deltas.
