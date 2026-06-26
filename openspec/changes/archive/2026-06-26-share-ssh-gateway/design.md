## Context

`make_daemon` (`yascheduler/entrypoints/di.py:130-214`) is the daemon's
composition root. On the production path (`clouds is None`) it currently
constructs two independent `SSHMachineGateway` instances:

```
di.py:171  → CloudProvisionerImpl(machine_gateway=SSHMachineGateway(log=log), ...)
di.py:191  → gateway = SSHMachineGateway(log=log)
            Orchestrator(gateway=gateway, ...)
```

Each gateway owns its own `_machines: dict[str, _MachineState]` registry
(`gateway.py:310`). The cloud gateway's entries are populated by
`_setup_vm → _connect_to_vm → machine_gateway.connect(...)` (manager.py:393)
but never removed: `CloudProvisionerImpl.allocate` does not disconnect on
success or failure, and `CloudProvisionerImpl.stop` is a no-op
(`manager.py:90-92`, comment "compatibility hook"). The orchestrator's
gateway is cleaned up via `Orchestrator.stop → self._gateway.disconnect_all()`
(orchestrator.py:600), but the cloud gateway is not.

Net effect:

1. **Leak**: every allocated cloud node leaves one SSH connection open for the
   process lifetime (cloud gateway never drains).
2. **Double-connect**: the orchestrator's `_connect_machine_producer` filter
   `not self._gateway.contains(n.ip)` (orchestrator.py:224) checks only its
   own registry. For a freshly allocated cloud VM the entry is absent, so
   `_connect_machine_consumer` opens a second connection to the same VM.

## Goals / Non-Goals

**Goals:**

- Eliminate the per-allocation SSH connection leak on the production path.
- Eliminate the double-connection to cloud VMs.
- Close cloud-gateway connections at daemon shutdown.
- Minimal code change; no public API change; no DB schema change.

**Non-Goals:**

- Refactoring the pre-built-clouds (`clouds is not None`) path — it is
  test-only and has no real leak.
- Removing the now-redundant `gateway.disconnect_all()` call in
  `Orchestrator.stop()` — kept for explicit ownership clarity.
- Adding a `gateway` parameter to `make_daemon` — YAGNI; no caller needs it.
- Changing the `MachineGateway` Protocol or the `CloudProvisionerImpl.machine_gateway`
  field type (stays `SSHMachineGateway` concrete).

## Decisions

### Decision 1: Share one gateway instance on the production path

Hoist `gateway = SSHMachineGateway(log=log)` above the `clouds is None`
branch and pass `machine_gateway=gateway` to `CloudProvisionerImpl` and
`gateway=gateway` to `Orchestrator` on that branch.

**Why over alternatives:**

- *Alternative A — ephemeral setup connection*: add `disconnect()` to
  `_setup_vm`'s `finally` and a real `clouds.stop()`. Rejected: keeps the
  double-connection (one setup-time + one production-time connection to the
  same VM), and is more code than sharing. Does not address the
  `_connect_machine_producer` filter blindness.
- *Alternative B — remove `machine_gateway` from `CloudProvisionerImpl`*:
  inline an ephemeral asyncssh connection in `_setup_vm`. Rejected: duplicates
  platform detection (`_detect_platform`), backoff wiring (`my_backoff_exc`),
  `setup_node`, and `get_cpu_cores`; YAGNI violation; broad refactor for a
  narrow bug.

The shared instance is correct because cloud nodes have effectively identical
`connect()` parameters from both callers:

| Parameter            | `_connect_to_vm` (cloud)            | `_connect_machine_consumer` (orch)       | Equivalent for cloud nodes?           |
| -------------------- | ----------------------------------- | ---------------------------------------- | ------------------------------------- |
| `username`           | `config.username`                   | `node.username` (= `config.username`)    | Yes — `_setup_vm` sets `Node.username=config.username` (manager.py:360) |
| `port`               | default `22`                        | `node.port` (= `22`)                     | Yes — `_setup_vm` sets `Node(port=22)` (manager.py:361) |
| `client_keys`        | `list_private_keys(local_config.keys_dir)` | `list_private_keys_fn(local_settings.keys_dir)` | Yes — same dir |
| `data_dir`/`engines_dir`/`tasks_dir` | `remote_config.*`        | `remote_defaults.*` (same object)        | Yes                                   |
| `jump_host`/`jump_username` | per-cloud `ConfigCloud`            | lookup by `cloud.prefix == node.cloud`   | Yes — same lookup, same values        |
| `connect_timeout`    | `adapter.create_node_conn_timeout` (~30s) | `10` (hardcoded)                   | **No** — but only matters at connect time, which already succeeded |

### Decision 2: Make `CloudProvisionerImpl.stop` delegate to `disconnect_all`

Replace the no-op body with `await self.machine_gateway.disconnect_all()`.

**Why:** the `MachineGateway` Protocol already declares `disconnect_all`
(`ports.py:145`). `disconnect_all` is idempotent (`gateway.py:346-349`
iterates `list(self._machines)` with pop). With a shared gateway, both
`clouds.stop()` and `Orchestrator.stop()`'s explicit `gateway.disconnect_all()`
target the same instance; the second call is a safe no-op.

Keeping both calls preserves explicit ownership: the orchestrator does not
*rely* on clouds cleaning up its gateway. The redundancy is harmless.

### Decision 3: Leave the pre-built-clouds path unchanged

`make_daemon(config, clouds=my_clouds)` (`di.py:177-190`) keeps creating a
fresh `SSHMachineGateway` for the orchestrator. The caller-supplied `clouds`
retain whatever gateway they were built with.

**Why:** only unit tests use this path (`tests/unit/test_di.py:235-278`); they
do not perform real allocations, so there is no actual leak to fix. Adding a
`gateway` parameter for symmetry would expand the public API surface for no
concrete benefit today. If production ever needs to pre-build clouds, a
follow-up can add the parameter.

### Decision 4: No change to `_setup_vm`, `allocate`, or orchestrator connection code

- `_setup_vm` does not need a `finally: disconnect` — the connection is meant
  to be long-lived (used by the orchestrator after allocation).
- `allocate` does not need to disconnect on success — same reason.
- `allocate` does not need to disconnect on failure — today it calls
  `adapter.delete_node` which destroys the VM; the leaked entry points to a
  dead connection that the daemon's `disconnect_all` at shutdown will reap.
  (Pre-existing minor inefficiency, not introduced by this change; not in
  scope.)
- `_connect_machine_producer`'s `not self._gateway.contains(n.ip)` filter
  naturally skips cloud nodes already connected by `_setup_vm` once the
  registries are merged. No orchestrator code change required.

## Risks / Trade-offs

- **Cloud nodes lose the orchestrator's `connect_timeout=10`** → Mitigation:
  irrelevant post-connect. The value only bounds the initial SSH handshake,
  which already completed in `_setup_vm` with `adapter.create_node_conn_timeout`.
  No runtime impact.
- **Future divergence between cloud-side and orch-side `connect()` parameters
  goes unnoticed** → Mitigation: add a unit-test assertion in
  `tests/unit/test_di.py` that locks in `clouds.machine_gateway is
  orch_kwargs["gateway"]`. Any future code that tries to give clouds a
  separate gateway will fail the test.
- **Subtle behavioral change: orchestrator's `_connect_machine_consumer` no
  longer fires `_machine_connected_event` for cloud nodes** → Mitigation:
  `_await_first_machine` (`orchestrator.py:494`) already has a 30s timeout
  fallback and short-circuits on `len(gateway) > 0`. In cloud-only cold start
  today, the timeout — not the event — unblocks the daemon (the allocator
  starts only after `_await_first_machine` returns). Behavior is unchanged
  before and after the fix.
- **`stop()` semantics change from "no-op" to "closes connections"** →
  Mitigation: no caller relies on `stop()` being a no-op. Existing
  `TestStop.test_stop` only asserts the call doesn't raise; it will be
  rewritten to assert `disconnect_all` is awaited.

## Migration Plan

Single-PR change, no migration:

1. Apply the diff to `di.py` and `manager.py` (production code).
2. Update unit tests (`test_di.py`, `test_cloud_provisioner_impl.py`).
3. Update GRACE-lite artifacts (`CHANGE_SUMMARY`, `MODULE_CONTRACT` in both
   files; `docs/knowledge-graph.xml` CrossLink).
4. Run `uv run pytest -m unit`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run lint-imports`,
   `python3 scripts/grace_check.py`, `openspec validate --all --json`.

**Rollback:** revert the single PR. No data migration, no schema impact.

## Open Questions

None blocking. The asymmetric pre-built-clouds path is intentional; revisit if
production ever pre-builds clouds.
