# Explore Brief — share-ssh-gateway

## Problem

`make_daemon` (yascheduler/entrypoints/di.py:171 and :191) constructs **two**
independent `SSHMachineGateway` instances:

- One inside `CloudProvisionerImpl(machine_gateway=SSHMachineGateway(log=log), ...)`
- One passed to `Orchestrator(gateway=SSHMachineGateway(log=log), ...)`

Each holds its own `_machines` registry. Consequences:

1. `_setup_vm` (manager.py:296) connects the freshly created VM in the
   **cloud** gateway. `allocate()` never disconnects; `CloudProvisionerImpl.stop()`
   is a no-op (manager.py:90-92). Every allocated cloud node leaves one SSH
   connection open for the lifetime of the process.
2. The orchestrator's `_connect_machine_producer` (orchestrator.py:224) checks
   `not self._gateway.contains(n.ip)` against its own registry only — for a
   freshly allocated cloud VM this is False, so `_connect_machine_consumer`
   opens a **second** connection to the same VM. Double SSH load, potential
   `MaxSessions` pressure.
3. `Orchestrator.stop()` (orchestrator.py:599-600) calls `clouds.stop()` (no-op)
   then `self._gateway.disconnect_all()` (its own only). The cloud gateway's
   connections are never cleaned up at shutdown either.

## Alternatives Rejected

- **A. Ephemeral setup connection** — add `disconnect()` to `_setup_vm`'s
  `finally` and make `clouds.stop()` real. Rejected: keeps the double-connect
  (one setup-time + one production-time) and is more code than sharing.
- **B. Remove `machine_gateway` from `CloudProvisionerImpl`** — inline an
  ephemeral asyncssh connection in `_setup_vm`. Rejected: duplicates platform
  detection, backoff, `setup_node`, `get_cpu_cores`; YAGNI violation.

## Selected Approach

**Single shared gateway in `make_daemon`.** Hoist `SSHMachineGateway(log=log)`
above the `clouds is None` branch; pass the same instance to both
`CloudProvisionerImpl` and `Orchestrator`. Make `CloudProvisionerImpl.stop()`
delegate to `machine_gateway.disconnect_all()`.

## Behavior Mapping

### `make_daemon` construction (di.py)

| Path                       | Today                                                | After                                              |
| -------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| `clouds is None` (prod)    | Two gateways; cloud gateway leaks; double-connect    | ONE gateway shared by clouds + Orchestrator        |
| `clouds is not None` (tests) | Two gateways (caller's clouds + fresh orch gateway) | Unchanged — caller-owned clouds keeps its gateway  |

Rationale for leaving pre-built-clouds path alone: it is exercised only by
unit tests (`tests/unit/test_di.py:235-278`), no real allocations happen, no
real leak. Production enters via `daemon_common.run_daemon` without `clouds=`.

### `connect()` parameter compatibility (cloud vs orchestrator)

For cloud nodes, parameters are effectively identical because `_setup_vm`
returns `Node(... username=config.username, port=22)` (manager.py:360), so the
orchestrator's later (now skipped) `connect()` would have used the same
`username`/`port`. Only material difference: `connect_timeout`
(`adapter.create_node_conn_timeout` ~30s vs orchestrator's hardcoded `10`).
Harmless post-connect.

For static SSH nodes (added via `yanodes`): unchanged — they do not pass
through `_setup_vm`, orchestrator remains the sole connector.

### `_await_first_machine` (orchestrator.py:494)

Has 30s timeout fallback and `if len(self._gateway) > 0: return` short-circuit.
In cloud-only cold start, both today and after the fix, allocator starts only
after `_await_first_machine` returns; the 30s timeout is the unblocker. **No
new deadlock.** For static-node and mixed deployments, behavior is identical
(event still fires from orchestrator's `_connect_machine_consumer`).

### `Orchestrator.stop()` ordering

```python
await self._clouds.stop()              # NEW: disconnect_all on shared gw
await self._gateway.disconnect_all()   # same instance, now empty → idempotent no-op
```

`disconnect_all` (gateway.py:346-349) iterates `list(self._machines)` with
pop — calling twice is safe. Keep `gateway.disconnect_all()` for explicit
ownership clarity (don't make Orchestrator implicitly depend on clouds'
cleanup).

### `CloudProvisionerImpl.stop()`

Change from no-op to:
```python
async def stop(self) -> None:
    self.log.info("[CloudProvisionerImpl][stop] closing machine_gateway connections")
    await self.machine_gateway.disconnect_all()
```

`MachineGateway` Protocol already declares `disconnect_all` (ports.py:145), so
no port change. `CloudProvisionerImpl.machine_gateway` field type stays
`SSHMachineGateway` (concrete) — no retyping.

## Cross-Module Data Flow

```
daemon_common.run_daemon(config)
    └─> make_daemon(config)
            ├─> gw = SSHMachineGateway(log=log)         # ONE instance
            ├─> clouds = CloudProvisionerImpl(machine_gateway=gw, ...)
            └─> Orchestrator(gateway=gw, clouds=clouds, ...)
                    ├─ start(): _connect_machine_producer filters via gw.contains(ip)
                    │           → cloud nodes already in gw are SKIPPED (no double-connect)
                    └─ stop():
                         ├─ clouds.stop() → gw.disconnect_all() (drains)
                         └─ gw.disconnect_all()           (idempotent no-op)
```

## Open Questions

- None blocking. Pre-built-clouds path intentionally left asymmetric (test-only).
- `Orchestrator.stop()` keeps redundant `gateway.disconnect_all()` for
  readability; could be simplified later as separate cleanup.

## Files Touched

Production code:
- `yascheduler/entrypoints/di.py` — hoist gateway, share between clouds + orch
- `yascheduler/infra/cloud/manager.py` — `stop()` body + contract update

Tests:
- `tests/unit/test_di.py` — assert `clouds.machine_gateway is gw`; patch
  `SSHMachineGateway` in pre-built-clouds test
- `tests/unit/test_cloud_provisioner_impl.py` — rewrite `TestStop` to assert
  `disconnect_all` is called

GRACE-lite artifacts:
- `docs/knowledge-graph.xml` — CrossLink relation update
- `MODULE_CONTRACT` / `CHANGE_SUMMARY` in di.py, manager.py

OpenSpec specs to update (delta):
- `openspec/specs/dependency-injection/spec.md` — add Requirement: single
  shared SSH gateway
- `openspec/specs/cloud-provisioner/spec.md` — add Scenario: stop() closes
  machine_gateway connections
