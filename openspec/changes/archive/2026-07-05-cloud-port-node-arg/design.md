# Design: cloud-port-node-arg

## Context

The `CloudProvisioner` port (`yascheduler/domain/ports.py`) currently exposes:

```python
async def allocate(self, provider: str, tmp_node_id: NodeId) -> Node: ...
async def deallocate(self, cloud: str, ip: str) -> None: ...
```

`CloudProvisionerImpl.allocate` (`infra/cloud/manager.py`) receives only a
`NodeId`, so after `adapter.create_node()` yields the VM ip it must *construct*
the identity `Node` from scratch (`manager.py:200-208`), pulling
`cloud=adapter.name`, `username=config.username`, `port=22` out of thin air.
`deallocate` receives `cloud`/`ip` scalars, and all three callers unpack them
from a `Node` they already hold: `deallocate_nodes.py:83`, `abandon_node.py:60`,
`allocate_task.py:408`.

Both `allocate` and `deallocate` provider adapters identify the VM by IP
(Azure tag `yascheduler_ip`, Hetzner `public_net.ipv4.ip`, VastAI
`public_ipaddr`). That IP-based identity is intentionally left untouched here;
migrating to a `node_id`-derived VM tag is the deferred Variant C.

## Goals / Non-Goals

**Goals:**

- Make the port `Node`-centric and symmetric: both `allocate` and `deallocate`
  take `node: Node`.
- Let `allocate` derive the enabled node from the passed identity via
  `dataclasses.replace` — no fresh `Node` construction.
- Freeze the port signature so Variant C can enrich `Node` (e.g. a `cloud_id`
  field) without another port change.
- Preserve all effective behavior: same VM created/deleted, same tmp-node
  single-row UPDATE lifecycle, same host/user on the wire.

**Non-Goals:**

- Changing how provider adapters locate a VM (still IP-based) — Variant C.
- Adding any new `Node` field, DB column, or migration.
- Touching `select_provider`, `stop`, CLI, INI config, or the AiiDA entrypoint.

## Decisions

### D1: `allocate(provider: str, node: Node) -> Node`

The caller already inserts a tmp-node `Node` (from `uow.nodes.insert(NewNode(...))`)
whose `node_id` is reused as the real identity. Pass that whole `Node` in.

Inside `allocate`, after `create_node` returns `ip_addr`, replace the transport
fields on the passed node:

```python
node = replace(node, ip=ip_addr, cloud=adapter.name, username=config.username)
```

then thread it through `_setup_vm` exactly as today (which returns
`replace(node, enabled=True, ncpus=ncpus)`).

**Why override `cloud`/`username` via `replace` rather than trust the tmp
node?** The tmp-node row is inserted as `NewNode(cloud=selected_name,
enabled=False)` with `username` defaulting to `"root"`. `selected_name ==
provider == adapter.name`, so `cloud` is already correct — but overriding keeps
`allocate` authoritative over adapter-derived fields and avoids coupling to the
caller's insert defaults. `username` comes from `config.username` (the cloud
config), which the tmp node does not carry, so it MUST be overlaid. `port` stays
22 (unchanged from today; the tmp node already has `port=22` default, so no
override needed).

**Alternative considered — keep `tmp_node_id: NodeId`, pass `Node` only to
`deallocate`.** Rejected: leaves the port asymmetric and still forces `allocate`
to construct a `Node`; misses the signature-freeze goal.

**Alternative — introduce a dedicated `CloudNodeRequest` value object.**
Rejected as YAGNI: `Node` already carries every field `allocate` needs
(`node_id`, `port`), and Variant C will extend `Node` anyway.

### D2: `deallocate(node: Node) -> None`

Read `node.cloud` and `node.ip` inside the adapter:

```python
async def deallocate(self, node: Node) -> None:
    if node.cloud is None:
        self.log.warning("[CloudProvisionerImpl][deallocate][NO_CLOUD] node_id=%s", node.node_id)
        return
    adapter = self.adapters.get(node.cloud)
    ...
    await adapter.delete_node(log=self.log, cfg=config, host=node.ip)
```

**Why a `node.cloud is None` guard?** The port typed `cloud: str` before, and
callers guarded `if node.cloud:` before calling. Moving the guard into
`deallocate` centralizes it and matches the existing `adapter is None` /
`config is None` warn-and-return style (`manager.py:267-282`). Callers
`deallocate_node` and `abandon_node` already gate on `if node.cloud:` /
`if node.cloud is not None:` — those guards stay (they also bracket DB
disable/remove work), so `deallocate` is only ever reached with a non-None
`cloud` in practice; the internal guard is defense-in-depth for the port
contract.

**Alternative — `deallocate(cloud: str, node: Node)`.** Rejected: `node.cloud`
already carries the provider; passing it separately reintroduces the
primitive-unpacking the change removes.

### D3: `_TmpSelection` carries the tmp `Node`

`_select_and_insert_tmp` already has the inserted `Node` (`tmp_node` at
`allocate_task.py:283`). Change `_TmpSelection` from `(name: str, node_id:
NodeId)` to `(name: str, node: Node)`. Downstream:

- `_allocate_cloud_node(clouds, uow_factory, selected_name, tmp_node, task_id)`
  calls `clouds.allocate(selected_name, tmp_node)`; on failure it still cleans
  up via `tmp_node.node_id`.
- `_cleanup_tmp_node_best_effort` still takes `tmp_node_id: NodeId` (cleanup is
  node_id-keyed); the caller passes `tmp_node.node_id`.
- `_persist_node_with_cleanup` calls `clouds.deallocate(node)` (was
  `clouds.deallocate(cloud_name, node.ip)`); the `cloud_name or selected_name`
  fallback is dropped since `deallocate` reads `node.cloud` and the returned
  node always carries `cloud=adapter.name`.
- `allocate_task` body keeps `tmp_node_id: NodeId | None` for the `finally`
  cleanup by reading `selected.node.node_id`.

**Why keep `_cleanup_tmp_node_best_effort` node_id-keyed?** Cleanup is a DB
`remove(node_id)`, a persistence concern, not a cloud concern — no reason to
pass the whole `Node`.

### D4: Callers `deallocate_node` / `abandon_node`

Both change `clouds.deallocate(node.cloud, node.ip)` → `clouds.deallocate(node)`.
Their surrounding `if node.cloud` guards and DB bracketing are unchanged.

## Risks / Trade-offs

- **Internal breaking change to a port** — three implementers (`impl` + two test
  doubles) and ~8 call/assert sites must change in lockstep. Mitigated: the type
  checker (`zuban`) flags every mismatch; scope is fully enumerated in the
  proposal Impact.
- **`deallocate(node)` hides the provider lookup** behind `node.cloud`, so a
  node with `cloud=None` silently no-ops. This matches today's caller guards and
  is logged; acceptable.
- **Overlaying `cloud`/`username` in `allocate`** is slightly redundant with the
  tmp node's `cloud`, but keeps `allocate` authoritative and is cheap (frozen
  `replace`). Trade-off accepted for clarity.
