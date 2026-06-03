## Context

Phase 4 part 2. `CloudProvisioner` port defined in `domain/ports.py`. Phase 2
provided `NodeRepository`. Phase 4 part 1 provided `SSHMachineGateway`.
Cloud modules currently use `DB` and `RemoteMachine` directly — this design
replaces them with ports.

## Goals / Non-Goals

**Goals:**
- Implement `CloudProvisioner` Protocol with multi-provider support.
- Move provider SDK code to `adapters/cloud/providers/`.
- Switch cloud code from `db.py` to `NodeRepository` (via UoW).
- Switch cloud code from `RemoteMachine` to `SSHMachineGateway`.
- Keep old classes as wrappers for unmigrated callers.

**Non-Goals:**
- No new cloud providers.
- No changes to cloud-init templates or SSH key management logic.
- No CLI cleanup (Phase 5).

## Decisions

### D1: CloudProvisionerImpl wraps provider SDKs

```python
class CloudProvisionerImpl:
    def __init__(self, providers: list[CloudProvider], node_repo: NodeRepository,
                 machine_gateway: MachineGateway, config: CloudConfig):
        ...

    async def allocate(self, platforms: list[str]) -> Node:
        provider = self._select_best_provider(platforms)
        ip = await provider.create_node()
        await self._wait_ssh(ip)
        node = Node(ip=ip, ncpus=..., cloud=provider.name, enabled=True)
        await self._node_repo.add(node)
        return node

    async def deallocate(self, ip: str):
        node = await self._node_repo.get(ip)
        provider = self._providers[node.cloud]
        await provider.delete_node(ip)
        await self._node_repo.remove(ip)

    async def capacity(self) -> dict[str, int]:
        return {p.name: p.available for p in self._providers}
```

### D2: Provider SDK code moves as-is

Provider files (`az.py`, `hetzner.py`, `upcloud.py`) move to
`adapters/cloud/providers/` with minimal changes. Each provider exposes
`create_node()` and `delete_node()` callables — same contract as current
`CloudAdapter`.

### D3: CloudAPI absorbed into CloudProvisionerImpl

`CloudAPI` currently does: create VM, wait SSH, cloud-init-wait, setup node,
return RemoteMachine. This logic moves into `CloudProvisionerImpl.allocate()`.
The VM creation → SSH wait → cloud-init → setup becomes a single orchestrated
flow in the adapter.

### D4: NodeRepository replaces db.py for cloud code

Before:
```python
await self.db.add_tmp_node(cloud, username)  # provisional IP
await self.db.commit()
# ... create VM ...
await self.db.add_node(ip, ncpus, cloud, username)
await self.db.commit()
```

After:
```python
await uow.nodes.add_tmp(provisional_ip, cloud)
await uow.commit()
# ... create VM ...
await uow.nodes.add(Node(ip, ncpus, enabled=True, cloud=cloud))
await uow.commit()
```

### D5: Compatibility wrappers preserved

`CloudAPIManager` and `CloudAPI` become thin wrappers for any code still
importing them directly (e.g., AiiDA plugin, external scripts). Wrappers
create a `CloudProvisionerImpl` internally and delegate.

### D6: Connection pool for cloud DB operations

Cloud provisioning uses `NodeRepository` which operates through pg8000.
Since cloud code runs inside the daemon's asyncio loop, DB operations use
the same `ThreadPoolExecutor(max_workers=1)` as other persistence code
(Phase 5.5 will upgrade to a pool).

## Risks / Trade-offs

- **Provider SDKs are optional dependencies**: Azure, Hetzner, UpCloud SDKs
  are `[project.optional-dependencies]`. The adapter must handle missing SDKs
  gracefully (skip unavailable providers, log warning).
- **CloudAPI.create_node() is complex**: SSH key generation, cloud-config
  rendering, VM creation, SSH wait, cloud-init wait, node setup. Moving this
  into the adapter requires careful extraction — risk of breaking subtle
  retry/error handling. Mitigation: characterization tests.
- **Concurrent allocation tracking**: Current `CloudAPIManager` tracks
  in-flight allocations via `on_task` set to prevent duplicate requests.
  This logic must be preserved in the adapter.
