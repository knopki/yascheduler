## Context

The e2e suite today (`tests/e2e/test_full_cycle.py`, `test_consume_retry.py`) covers only
the **static-node** lifecycle: operator-added SSH containers (testcontainers
`openssh-server`) receive pre-submitted jobs, run the `test_shell` engine, and are
soft-removed. It never exercises:

- `CloudProvisionerImpl.allocate` against a **real** provider SDK,
- `hetzner_create_node` / `hetzner_delete_node` against the **real** Hetzner API,
- `_setup_vm` (cloud-init `status --wait`, `setup_node`, CPU detection) on a **real** VM,
- `_persist_node_with_cleanup` committing the final enabled node row and removing the
  tmp-node row in one commit (`allocate_task.py:370`),
- the idle-deallocate path (`deallocate_nodes` → `deallocate_node` →
  `clouds.deallocate`) on a real, billed resource.

The unit layer doubles all of these. Hetzner is manually confirmed working on a real
account, so it is the right first target. Two hard constraints: (1) the test spends real
money and needs real credentials → must be opt-in and skip by default; (2) the existing
`package_upgrade=True` hardcode in `_get_cloud_config_data` makes cloud-init run
`apt-get upgrade` on every fresh VM, slow enough to risk the `connect_grace` window and
orphan the VM — so this change also makes that flag configurable.

Key codebase anchors (frozen, unchanged unless noted):
- `make_daemon(config)` (`entrypoints/di.py`) builds `CloudProvisionerImpl` from
  `config.clouds` (filter `max_nodes > 0` + resolved adapter).
- `allocate_task` (`application/allocate_task.py`) → no free machine →
  `clouds.select_provider` → `clouds.allocate(provider)` → `_setup_vm` →
  `_persist_node_with_cleanup` → emits `[AllocateTask][allocate_task][CLOUD_DONE]
  task_id=%s ip=%s provider=%s` (`allocate_task.py:413`).
- `deallocate_node` (`application/deallocate_nodes.py:76`) emits
  `[deallocate_node][CLOUD_DELETE] ip=%s cloud=%s` before `clouds.deallocate`.
- `LocalSettings` (`domain/settings.py`) frozen dataclass; `_parse_local_section`
  (`entrypoints/config_parser.py`) reads fields by name and validates via
  `_local_valid_fields()` (introspects the dataclass, so a new field is automatically a
  valid `[local]` key).
- `ConfigCloudHetzner` (`infra/cloud/cloud_configs.py`): `token`, `max_nodes`,
  `server_type`, `location`, `image_name`, `idle_tolerance`, `connect_grace=60` (default,
  NOT INI-parsed). `[clouds]` keys: `hetzner_token`, `hetzner_max_nodes`,
  `hetzner_server_type`, `hetzner_location`, `hetzner_image_name`,
  `hetzner_idle_tolerance`; `hetzner_user` inherited from `[remote]`.
- `can_debian_buster` (`infra/cloud/adapters.py:50`) matches
  `["debian-10","debian","debian-like","linux"]` → the `test_shell` engine's
  `platforms = linux` passes Hetzner adapter selection. The `debian-13` image is detected
  on connect via `check_is_debian_13` → `debian_13_adapter` (in the platform registry).
- `hcloud` SDK is an optional import (`_HETZNER_AVAILABLE`).
- `log_records` fixture attaches its handler to the `"yascheduler"` logger only
  (`tests/e2e/conftest.py::_YASCHEDULER_LOGGER`). The daemon's top-level
  `logging.getLogger("Orchestrator")` is a child of **root**, not `"yascheduler"`, so
  `CREATED <ip>` and `[CloudProvisionerImpl]` lines are NOT captured; the two
  `yascheduler.application.*` markers above ARE captured.

## Goals / Non-Goals

**Goals:**
- One real-Hetzner e2e test asserting the full cold-start → allocate → download →
  idle-deallocate happy path through real entrypoints (`make_daemon`, `_submit_async`).
- A reusable, safe enablement contract (env-var gate + credentials, no new marker) that
  other providers can copy once confirmed.
- Guaranteed cleanup with a loud-fail-on-leak contract so a failed/aborted test never
  silently leaves a billed VM.
- A configurable `package_upgrade` knob so cloud-init can skip the slow `apt-get upgrade`.

**Non-Goals:**
- e2e tests for `az`/`upcloud`/`vastai` (later changes, same harness).
- Cloud failure-path e2e (setup failure, throttle, never-connected abandon) — those stay
  unit-tested; this is the **happy path** only.
- Wiring the test into CI — it is manual/env-gated for now.
- Any change to the Hetzner provider code, `ConfigCloudHetzner`, the cloud-section
  parser, the orchestrator, or the DB schema.

## Decisions

### D1 — Enablement: env-only gate, no new marker
Run iff `YASCHEDULER_TEST_HETZNER == "1"` AND `YASCHEDULER_CLOUDS_HETZNER_TOKEN` is
non-empty; otherwise `pytest.skip(...)` naming the missing var. The test carries the
existing `e2e` marker (auto-applied by `conftest.pytest_collection_modifyitems` for any
file under `tests/e2e/`). **No `cloud` marker is added** — it would be a redundant axis
since the env gate already selects; CI's `-m e2e` collects and skips the test (skip is
not failure), and a local `-m e2e` with creds set runs it.

**Why two env vars (not just the token):** the token alone is ambiguous — a stale token
in a shell rc could silently run a billed test. The explicit `YASCHEDULER_TEST_HETZNER=1`
opt-in makes intent deliberate.

**Rejected:** (a) a new `cloud` marker — redundant with the env gate and adds a
declarative line without changing selection semantics; (b) marker-only — markers carry
no secrets and a skip-on-missing-env is clearer.

### D2 — Config: cheap defaults, env-overridable, hard cap at 1 node
`[clouds]` section in the test INI:
```
hetzner_token          = $YASCHEDULER_CLOUDS_HETZNER_TOKEN
hetzner_max_nodes      = 1
hetzner_server_type    = $YASCHEDULER_CLOUDS_HETZNER_SERVER_TYPE   or cx23
hetzner_location       = $YASCHEDULER_CLOUDS_HETZNER_LOCATION       or hel1
hetzner_image_name     = $YASCHEDULER_CLOUDS_HETZNER_IMAGE_NAME     or debian-13
hetzner_idle_tolerance = 5
```
`max_nodes=1` is the hard cost ceiling (one VM). `idle_tolerance=5` makes the deallocate
assertion observable inside the test window without burning minutes; the parser enforces
`>= 1`. `cx23`/`hel1`/`debian-13` are current cheap defaults; operators override per
region/availability. `connect_grace` is deliberately NOT set: the DTO default of 60 s is
ample for a VM whose cloud-init skips `apt-get upgrade` (see D6).

### D3 — Fixture: `hetzner_config` lives in the test file
The `hetzner_config` fixture is session-scoped and defined in
`tests/e2e/test_hetzner_live.py`, reusing `postgres_container`, `_db_config`, and
`_init_schema` from `tests/e2e/conftest.py`. It does NOT touch `ssh_pool` (Hetzner
provisions its own VM) and does NOT depend on the function-scoped `uow_factory` or
`log_records` (a session fixture depending on function-scoped ones raises pytest
`ScopeMismatch`); those are consumed by the test function. The shared conftest gains no
cloud-specific fixture. The fixture builds a fresh `keys_dir` (daemon generates a key via
`get_or_create_ssh_key`, registered into the Hetzner project by `get_ssh_key_id`).

**Why in the test file, not conftest:** cloud config is provider-specific and the only
consumer is this test; coupling the shared conftest to one provider would be wrong.

### D4 — Test body: real entrypoints, generous timeouts, RUNNING snapshot
Mirrors `test_full_cycle`'s discipline (drive `_submit_async`, assert via `uow_factory`,
grep `log_records`) but adapts to cloud reality:

1. `make_daemon(hetzner_config)` → `orchestrator.start()` as a background task.
2. Submit **2** jobs via `_submit_async` (engine `test_shell`), each in its own temp CWD
   with a distinct `1.input` payload.
3. Assert both `TO_DO` before any node exists.
4. Poll `uow.nodes.list_all()` until a row with `cloud == "hetzner"` appears; record its
   IP in `observed_ips`. Timeout **600 s** — VM create + boot + cloud-init routinely
   takes minutes (less so with `package_upgrade=false`).
5. Poll until both tasks `DONE`, capturing each task's `RUNNING` snapshot
   (`allocated_ip`) en route. Timeout **600 s**.
6. Assert outputs exist and match `1.input`.
7. Assert both tasks ran on the single hetzner node (only 1 node exists; both
   `allocated_ip` equal that node's IP — it serializes since `max_nodes=1` and
   `test_shell` sleeps 3 s).
8. Grep `log_records` for the two capturable cloud-path markers (see D7).
9. Poll `uow.nodes.list_all()` until the hetzner node row is gone (idle deallocate
   fired); timeout `idle_tolerance + 120 s`.

**Why 2 jobs, not more:** one VM, one engine slot — more jobs extend wall time without
adding coverage. Two is the minimum that proves allocation + result download + reuse.

### D5 — Cleanup: observed-IP delete + loud-fail, in `finally` (NO sweep)
The `finally` block (runs even on assertion failure / exception):
1. `orchestrator.stop()` + best-effort await of the bg task (swallow
   `CancelledError`/`TimeoutError`).
2. For every node IP in `observed_ips`: `await hetzner_delete_node(log, cfg, ip)`.
3. **Leak guard:** after the delete attempt, call `find_srv(client, ip)`; if it still
   returns the server (delete failed or raised), raise `pytest.fail(...)` with a message
   of the form `Hetzner VM <ip> was NOT deleted — manual cleanup required`, and emit an
   ERROR log with the same IP.

**No name-prefix sweep:** a start-of-test server-list snapshot + name-prefix deletion is
rejected — it is useless after a `SIGKILL` (the only case where `finally` doesn't run is
exactly when a sweep-at-startup on the *next* run would be needed, but that is an
out-of-band reaper concern), and it conflicts with parallel test runs in the same
project. The honest boundary: the loud-fail contract covers every **in-process** failure
(a leaked VM produces a failing test naming its IP); a hard process kill is an
operational concern outside this change's scope. `max_nodes=1` bounds the worst case to
one VM.

### D6 — `package_upgrade` knob on `LocalSettings`
Add `cloud_package_upgrade: bool = True` to `LocalSettings` (default preserves existing
behavior). `_get_cloud_config_data` returns
`CloudInitConfig(package_upgrade=self.local_config.cloud_package_upgrade, packages=pkgs)`
instead of hardcoding `True`. `_parse_local_section` adds
`sec.getboolean("cloud_package_upgrade")` (the `_local_valid_fields()` introspection
already accepts the new key without an "unknown field" warning). The test INI sets
`cloud_package_upgrade = false` under `[local]`, so cloud-init skips the slow
`apt-get upgrade` and the default `connect_grace=60` is ample.

**Why `LocalSettings` (not `ConfigCloud*`):** the hardcode is one place in
`CloudProvisionerImpl._get_cloud_config_data`, agnostic to which provider; the knob
naturally lives where the hardcode is, read from the already-injected `local_config`.

### D7 — Log assertions scoped to **capturable** cloud markers
The `log_records` fixture attaches to the `"yascheduler"` logger only. The two
capturable markers (both on `yascheduler.application.*` module loggers):
- **Provisioning** — `[AllocateTask][allocate_task][CLOUD_DONE] task_id=%s ip=%s
  provider=%s` (`allocate_task.py:413`), emitted by `_persist_node_with_cleanup` after
  the final node row commits. Stronger than `CREATED`: proves the VM was created, set
  up, AND persisted.
- **Teardown** — `[deallocate_node][CLOUD_DELETE] ip=%s cloud=%s`
  (`deallocate_nodes.py:76`), emitted before `clouds.deallocate`.

The test asserts both, with `ip=` / `provider=hetzner` / `cloud=hetzner` matching the
provisioned node. The test does NOT assert on `CREATED <ip>` or `[CloudProvisionerImpl]`
lines — they are on the top-level `"Orchestrator"` logger (child of root), invisible to
`log_records`.

## Risks / Trade-offs

- **[Cost / orphaned VMs on hard crash]** — `SIGKILL`/OOM mid-test skips `finally`.
  → Mitigation: D5's loud-fail covers every in-process failure; `max_nodes=1` bounds the
  worst case to one VM; an out-of-band reaper is a future operational concern (out of
  scope).
- **[Flakiness from Hetzner availability / rate limits]** — `cx23`/`hel1` may be
  temporarily unavailable. → Mitigation: env-overridable knobs (D2); generous timeouts
  (D4); the test is opt-in, not gate-keeping CI.
- **[Idle-deallocate race at `idle_tolerance=5`]** — a deallocate cycle could fire before
  the allocator reuses the free node for task 2, causing a second VM (still reaches DONE,
  but costs more). → Mitigation: the value is tunable; the spec gives guidance to start
  at ~5 and raise toward ~10 if the deallocate window proves too tight. The test does NOT
  assert exact VM count (only "both DONE + final VM deleted"), so a 2nd VM is non-fatal.
- **[Credential leakage in logs]** — the token flows into the INI and
  `ConfigCloudHetzner.token`. → Mitigation: never log `cfg.token` or the INI path
  contents; cleanup helpers log only IPs. Existing cloud-path logs already redact (IPs,
  not tokens).
- **[Stale SSH key accumulation on the Hetzner project]** — each run registers a fresh
  key. → Mitigation: acceptable for an opt-in manual test; `get_ssh_key_id`'s fingerprint
  recovery reuses across runs within a project; cleanup focus is VMs (the billed
  resource). A key-reap helper is a future enhancement.

## Migration Plan

None for behavior. The change is additive: one new test file; one new `LocalSettings`
field (default `True` → no behavior change for existing operators); one read-site change
in the manager; one `getboolean` line in the parser. Default `pytest`/CI behavior is
unchanged (the test skips). Rollback = delete the test file + revert the three small
production-code edits.

## Open Questions

All resolved in this design (see Decisions). No outstanding unknowns.
