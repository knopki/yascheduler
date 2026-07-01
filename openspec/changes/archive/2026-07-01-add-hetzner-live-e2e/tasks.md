## 1. `package_upgrade` knob (production code)

- [x] 1.1 Add `cloud_package_upgrade: bool = True` field to `LocalSettings` in `yascheduler/domain/settings.py` (after `deallocate_pending`). No `__post_init__` validation needed (any bool accepted). Bump the module `VERSION` and `START_CHANGE_SUMMARY`. Verify: `uv run pytest -m unit` passes; `LocalSettings().cloud_package_upgrade is True`.
- [x] 1.2 In `CloudProvisionerImpl._get_cloud_config_data` (`yascheduler/infra/cloud/manager.py`), replace the hardcoded `CloudInitConfig(package_upgrade=True, packages=pkgs)` with `CloudInitConfig(package_upgrade=self.local_config.cloud_package_upgrade, packages=pkgs)`. Bump module `VERSION` + `START_CHANGE_SUMMARY`; update the contract's SIDE_EFFECTS note if needed. Verify: existing unit test `test_cloud_config_with_engine_packages` still passes (its mock `local_config` is a `MagicMock` → truthy → `package_upgrade is True`); add a focused unit assertion that `local_config.cloud_package_upgrade = False` propagates to the returned `CloudInitConfig.package_upgrade`.
- [x] 1.3 In `_parse_local_section` (`yascheduler/entrypoints/config_parser.py`), add `cloud_package_upgrade=sec.getboolean("cloud_package_upgrade", fallback=True)` to the `LocalSettings(...)` construction. Bump module `VERSION` + `START_CHANGE_SUMMARY`. Verify: parsing a `[local]` section without the key yields `True`; with `cloud_package_upgrade = false` yields `False`; no "unknown field" warning (covered by `_local_valid_fields()` introspection).

## 2. Test file scaffold + env gate

- [x] 2.1 Create `tests/e2e/test_hetzner_live.py` with the GRACE-lite `FILE`/`VERSION`/`START_MODULE_CONTRACT`/`START_MODULE_MAP`/`START_CHANGE_SUMMARY` header (PURPOSE: real-Hetzner autoscale→allocate→download→idle-deallocate e2e; DEPENDS: M-ENTRYPOINTS-DI, M-ENTRYPOINTS-CLI-SUBMIT, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ALLOCATE, M-APPLICATION-DEALLOCATE, M-CLOUD-HETZNER, M-PERSISTENCE-UOW). Test module stays OUT of `docs/knowledge-graph.xml` (GRACE-lite rule for test modules).
- [x] 2.2 Implement `_cloud_env_or_skip()` returning `(token, server_type, location, image)` reading `YASCHEDULER_TEST_HETZNER` (must == `"1"`), `YASCHEDULER_CLOUDS_HETZNER_TOKEN` (non-empty), `YASCHEDULER_CLOUDS_HETZNER_LOCATION` (default `hel1`), `YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE` (default `cx23`), `YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME` (default `debian-13`); `pytest.skip(...)` naming the missing var otherwise. The helper imports NOTHING optional (no `hcloud`) — the collection-without-SDK guarantee flows from this helper + the lazy imports in §4. Verify: with env unset, `uv run pytest tests/e2e/test_hetzner_live.py` SKIPS (no API call); collection passes even with `hcloud` uninstalled.

## 3. `hetzner_config` fixture

- [x] 3.1 Add a session-scoped `hetzner_config` fixture (in the test file) depending ONLY on `postgres_container`, `_db_config`, `_init_schema`. It writes a temp INI with `[db]`, `[local]` (`cloud_package_upgrade = false`, plus `data_dir`), `[remote]` (`user = root`), `[engine.test_shell]` (same `run.sh` + fresh keys_dir setup as `tests/e2e/conftest.py::e2e_config`, but a SEPARATE temp keys_dir so the daemon generates its own key), and `[clouds]` with `hetzner_token`, `hetzner_max_nodes = 1`, `hetzner_server_type`, `hetzner_location`, `hetzner_image_name`, `hetzner_idle_tolerance = 5`. Writes the `run.sh` engine script (sleep 3; `cat 1.input > 1.input.out`); sets `YASCHEDULER_CONF_PATH`; returns parsed `Config`. Verify: parse succeeds; `config.clouds == [ConfigCloudHetzner(max_nodes=1, token=<env>, server_type/location/image=<env|default>, idle_tolerance=5)]`; the INI text contains `cloud_package_upgrade = false` and does NOT contain `connect_grace`.

## 4. Cleanup + verification helpers

- [x] 4.1 Implement `_assert_vm_deleted(client, ip)` that polls `find_srv(client, ip)` (reusing `yascheduler.infra.cloud.providers.hetzner.find_srv`) until it returns `None` within a short timeout, then `pytest.fail("Hetzner VM <ip> was NOT deleted — manual cleanup required")` if it does not. Lazy-import `hcloud.Client` and `find_srv` inside the helper.
- [x] 4.2 Implement `async def _cleanup_observed(token, observed_ips, log)` that builds a minimal `ConfigCloudHetzner(token=token, max_nodes=1)` and, for each IP, `await hetzner_delete_node(log, cfg, ip)` (swallow+log per-IP exceptions so all IPs are attempted), then calls `_assert_vm_deleted` per IP (which `pytest.fail`s loudly if a VM survived). Note: a fresh minimal `ConfigCloudHetzner` for cleanup creates a DISTINCT `hcloud.Client` from the daemon's (`get_client` is `@cache`d per cfg instance) — expected; only `cfg.token` is read.

## 5. Test body

- [x] 5.1 Start daemon + submit + queued: call `_cloud_env_or_skip()`; `orchestrator = await make_daemon(hetzner_config)`; `asyncio.create_task(orchestrator.start())`; submit 2 jobs via `_submit_async(["<script>","--config","<ini>"])` in per-job temp CWDs (`1.input` = `"hello cloud 1"`/`"hello cloud 2"`); assert both `TO_DO` via `uow_factory`. Wrap the whole body in `try/finally`.
- [x] 5.2 Autoscale + completion: poll `uow.nodes.list_all()` until exactly one `cloud=="hetzner"` node appears (timeout 600 s); record its IP into `observed_ips`. Poll until both tasks `DONE` (timeout 600 s), capturing each `RUNNING` snapshot `allocated_ip` en route.
- [x] 5.3 Outputs + cloud-node assignment: for each task assert `status==DONE`, `context.error is None`, `context.local_folder` set, `<local_folder>/1.input.out` content matches its payload; assert each task's `allocated_ip` is a `cloud=="hetzner"` node IP observed during the test. Do NOT assert both `allocated_ip` are identical (idle-deallocate race may provision a 2nd VM — non-fatal).
- [x] 5.4 Cloud-path log assertions: grep `log_records` for `[AllocateTask][allocate_task][CLOUD_DONE]` with `ip=<node_ip>` and `provider=hetzner`, and `[deallocate_node][CLOUD_DELETE]` with `cloud=hetzner`. Do NOT assert on `CREATED <ip>` or `[CloudProvisionerImpl]` lines.
- [x] 5.5 Idle deallocation + strong deletion assertion: poll `uow.nodes.list_all()` until the `cloud=="hetzner"` row is gone (timeout `idle_tolerance + 120` s = 125 s); then poll `find_srv(client, ip)` until `None` (the strong, separate deletion assertion).
- [x] 5.6 `finally`: (a) `await orchestrator.stop()` + best-effort `asyncio.wait_for(orch_task, timeout=10)` (swallow `CancelledError`/`TimeoutError`); (b) `await _cleanup_observed(token, observed_ips, log)` — which attempts `hetzner_delete_node` per observed IP and loudly `pytest.fail`s if any VM survived deletion. No name-prefix sweep.

## 6. GRACE-lite markup

- [x] 6.1 Add `START_CONTRACT` blocks to the fixture and each helper/test-step function in `test_hetzner_live.py` (PURPOSE/INPUTS/OUTPUTS/SIDE_EFFECTS/LINKS); add `START_BLOCK_*` anchors for the submit/autoscale/completion/log-assert/deletion/cleanup sections; bump `START_CHANGE_SUMMARY`.

## 7. Verification (static + default-collection)

- [x] 7.1 `uv run ruff check . && uv run ruff format --check .` pass.
- [x] 7.2 `uv run lint-imports` passes (test imports `hcloud` lazily inside helpers → no top-level optional import; production-code edits are intra-package).
- [x] 7.3 `uv run zuban check` passes.
- [x] 7.4 `python3 scripts/grace_check.py` exits 0 (markup + graph; graph unchanged — test module stays out; production modules edited already have `M-` entries).
- [x] 7.5 `openspec validate --all --json` passes (change + three delta specs valid).
- [x] 7.6 Default-collection regression: `uv run pytest tests/e2e -q` SKIPS the new test and does not touch the network (env unset); `uv run pytest -m unit` passes including the new `package_upgrade` propagation assertion.

## 8. Manual smoke (opt-in, operator-run; not CI)

- [x] 8.1 With `YASCHEDULER_TEST_HETZNER=1` and `YASCHEDULER_CLOUDS_HETZNER_TOKEN=<real>` set, run `uv run pytest tests/e2e/test_hetzner_live.py` against a dedicated Hetzner CI project. Confirm: one `cx23` VM is created in `hel1`, both jobs reach DONE with matching outputs, the VM is deleted after the idle window, and `find_srv` confirms deletion. Record the run in `review-log.md` (pass/fail + duration). Costs real money; cap is one VM.
