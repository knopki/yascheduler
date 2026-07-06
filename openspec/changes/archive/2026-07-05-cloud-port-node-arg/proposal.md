# Proposal: cloud-port-node-arg

## Why

The `CloudProvisioner` port is asymmetric and primitive-obsessed: `allocate`
takes a bare `NodeId` (forcing `CloudProvisionerImpl.allocate` to *construct* a
fresh `Node` identity internally instead of threading the existing one), while
`deallocate(cloud: str, ip: str)` unpacks two scalars even though all three
callers already hold the full `Node`. Making both methods take `Node` removes
the unpacking, lets `allocate` build the enabled node via `replace` on the
identity it was handed (Node as the single source of truth — the same principle
`simplify-cloud-connect-node-args` established for `connect`), and — critically
— **freezes the port signature** so the later `node_id`-based VM-identity work
(deferred Variant C) can enrich `Node` without re-touching the port.

## What Changes

- **BREAKING** (internal port): `CloudProvisioner.allocate(provider: str,
  tmp_node_id: NodeId) -> Node` becomes `allocate(provider: str, node: Node) ->
  Node`. The caller passes the tmp-node `Node` (from `insert`) whose `node_id`
  is reused as the real identity; `allocate` overlays the provisioned `ip` and
  cloud `username` via `dataclasses.replace` rather than constructing a new
  `Node`.
- **BREAKING** (internal port): `CloudProvisioner.deallocate(cloud: str, ip:
  str) -> None` becomes `deallocate(node: Node) -> None`. The adapter reads
  `node.cloud` (provider) and `node.ip` (cloud SDK host) internally. VM
  identification stays IP-based inside the provider adapters (unchanged — that
  is the deferred Variant C).
- `CloudProvisionerImpl.allocate`: after `adapter.create_node(...)` returns the
  VM ip, construct the identity via `replace(node, ip=ip_addr,
  cloud=adapter.name, username=config.username)` (was a fresh `Node(...)`), then
  thread that single `Node` into `_setup_vm`. `_setup_vm` still returns
  `replace(node, enabled=True, ncpus=ncpus)`.
- `CloudProvisionerImpl.deallocate(node)`: resolve provider from `node.cloud`
  (warn+return when `None`), delete the VM at `node.ip`.
- `allocate_task`: `_select_and_insert_tmp` returns the tmp `Node` (in
  `_TmpSelection`, replacing the bare `node_id`); `_allocate_cloud_node` passes
  that `Node` to `clouds.allocate`; `_persist_node_with_cleanup` calls
  `clouds.deallocate(node)`.
- `deallocate_node` and `abandon_node`: call `clouds.deallocate(node)` (was
  `clouds.deallocate(node.cloud, node.ip)`).
- Update the three port test doubles/assertions:
  `FakeCloudProvisioner.allocate/deallocate` in
  `test_cloud_alloc_session_lifecycle.py`, the stub in `test_domain_ports.py`,
  and the direct `prov.allocate(...)` / `prov.deallocate(...)` calls in
  `test_cloud_provisioner_impl.py`.
- Public contracts unchanged: CLI surface, INI config, DB schema, AiiDA
  entrypoint, the tmp-node single-row UPDATE lifecycle, and effective cloud
  behavior (same VM created/deleted, same host/user on the wire).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `domain-ports`: `CloudProvisioner.allocate` takes `node: Node` (was
  `tmp_node_id: NodeId`); `deallocate` takes `node: Node` (was `cloud: str, ip:
  str`). Scenarios updated to the new signatures.
- `cloud`: `CloudProvisionerImpl.allocate` receives `node: Node`, derives the
  identity via `replace` (no fresh `Node` construction), and `deallocate(node)`
  reads `node.cloud`/`node.ip` internally.
- `use-cases`: `AllocateTask` `_select_and_insert_tmp`/`_TmpSelection` carry the
  tmp `Node`; `clouds.allocate(selection, node)` and `clouds.deallocate(node)`
  call shapes; `DeallocateIdleNodes` `deallocate_node` calls
  `clouds.deallocate(node)`.

## Impact

- Code: `yascheduler/domain/ports.py`, `yascheduler/infra/cloud/manager.py`,
  `yascheduler/application/allocate_task.py`,
  `yascheduler/application/deallocate_nodes.py`,
  `yascheduler/application/abandon_node.py`.
- Tests: `tests/unit/test_domain_ports.py`,
  `tests/unit/test_cloud_alloc_session_lifecycle.py`,
  `tests/unit/test_cloud_provisioner_impl.py`,
  `tests/unit/test_application_use_cases.py`,
  `tests/unit/test_allocate_task_failure_modes.py` (asserts on
  `clouds.allocate`/`clouds.deallocate` call args),
  `tests/unit/test_abandon_node.py` (asserts on `clouds.deallocate` call args),
  `tests/integration/test_never_connected_node_abandon.py` (asserts on
  `orch._clouds.deallocate` call args).
- No dependency, schema, migration, or CLI changes.
