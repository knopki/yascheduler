## Why

`make_daemon` constructs two independent `SSHMachineGateway` instances — one
inside `CloudProvisionerImpl`, one passed to `Orchestrator`. Each holds its
own `_machines` registry, so connections opened by `_setup_vm` during cloud
allocation are never visible to the orchestrator and never closed
(`CloudProvisionerImpl.stop` is a no-op). Every allocated cloud node leaks one
SSH connection for the lifetime of the process, and the orchestrator opens a
second connection to the same VM because its `contains(ip)` check only inspects
its own registry. The result is unbounded SSH connection growth proportional to
cumulative cloud allocations, plus double SSH-server load per active cloud node.

## What Changes

- Hoist `SSHMachineGateway(log=log)` above the `clouds is None` branch in
  `make_daemon`; pass the same instance to both `CloudProvisionerImpl` and
  `Orchestrator` so a single `_machines` registry spans cloud setup and
  orchestrator runtime.
- `CloudProvisionerImpl.stop` SHALL delegate to
  `machine_gateway.disconnect_all()` instead of being a no-op, so shutdown
  closes connections opened during `_setup_vm`. The orchestrator's existing
  `gateway.disconnect_all()` call in `stop()` becomes an idempotent no-op on
  the (now shared) instance.
- As a side effect of the shared registry, the orchestrator's
  `_connect_machine_producer` filter `not self._gateway.contains(n.ip)` will
  skip cloud nodes already connected by `_setup_vm`, eliminating the
  double-connection without any change to orchestrator code.
- The `clouds is not None` (pre-built clouds) path is left unchanged: it is
  exercised only by unit tests, performs no real allocations, and therefore
  has no actual leak. Production enters via `daemon_common.run_daemon` without
  `clouds=`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dependency-injection`: new Requirement — `make_daemon` SHALL construct a
  single `SSHMachineGateway` instance on the `clouds is None` path and inject
  the same instance into both `CloudProvisionerImpl.machine_gateway` and
  `Orchestrator.gateway`. The pre-built-clouds path keeps its current behavior
  (caller-owned clouds retain their gateway; orchestrator gets its own).
- `cloud-provisioner`: new Requirement — `CloudProvisionerImpl.stop` SHALL
  close all SSH connections held by its `machine_gateway` via
  `disconnect_all()`. Replaces the prior no-op "compatibility hook" semantics.

## Impact

Production code:
- `yascheduler/entrypoints/di.py` — move `SSHMachineGateway(log=log)` above
  the `clouds is None` branch; pass the same instance to `CloudProvisionerImpl`
  and `Orchestrator` on that branch.
- `yascheduler/infra/cloud/manager.py` — replace `stop()` body with a
  `machine_gateway.disconnect_all()` call; update contract and `CHANGE_SUMMARY`.

Tests:
- `tests/unit/test_di.py` — assert `clouds.machine_gateway is
  orch_kwargs["gateway"]` on the `clouds is None` path; patch
  `SSHMachineGateway` in `test_uses_provided_clouds` for parity.
- `tests/unit/test_cloud_provisioner_impl.py` — rewrite `TestStop.test_stop`
  to inject a mock gateway whose `disconnect_all` is an `AsyncMock` and assert
  it is awaited.

Behavioral:
- For cloud nodes, the orchestrator's hardcoded `connect_timeout=10` and
  `port=node.port` are no longer applied (because `connect()` is no longer
  called for them) — material values come from `_setup_vm`'s call instead
  (`adapter.create_node_conn_timeout`, port 22). For cloud nodes these are
  equivalent because `_setup_vm` returns `Node(... username=config.username,
  port=22)`.
- For static SSH nodes (added via `yanodes`), nothing changes — the
  orchestrator remains the sole connector.
- `_await_first_machine` (30s timeout fallback) is unaffected; no new deadlock.

GRACE-lite:
- `docs/knowledge-graph.xml` — update `M-DI → M-SSH-GATEWAY` CrossLink
  relation to reflect single shared instance.
- `MODULE_CONTRACT` / `CHANGE_SUMMARY` updates in `di.py` and `manager.py`.

No public API changes. No DB schema changes. No new dependencies.
