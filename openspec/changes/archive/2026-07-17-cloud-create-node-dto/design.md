## Context

Cloud adapter `create_node` returns a bare `str` (IP), forcing `CloudProvisionerImpl.allocate()` to manually construct Node fields from the IP and config. `delete_node` accepts `host: str` (also IP), but the cloud resource identity is `Node.external_id` — conflating provider identity with SSH address.

The adapter has no way to communicate non-default connection parameters (custom SSH port, jump host) back to the provisioner. Providers that require non-standard connectivity need workarounds.

## Goals / Non-Goals

**Goals:**
- `create_node` returns `CloudCreateNodeDTO` with all SSH-connection fields (hostname, username, port, jump)
- `delete_node` identifies the cloud resource by `external_id`, not `hostname`
- Adapters control the connection parameters of their created nodes

**Non-Goals:**
- Changes to Node model or DB schema (Node.external_id already exists)
- Refactoring providers to use provider-native external IDs (Hetzner, VastAI — separate follow-up)
- Changes to ConfigCloud* DTOs
- Changes to domain ports
- Changes to CloudAdapter operational fields (op_limit, timeouts)
- Changes to cloud-init

## Decisions

### DTO to Node mapping: inline in allocate()

`CloudProvisionerImpl.allocate()` maps DTO fields to Node via a single `replace()` call. No helper function or DTO method — the mapping is a mechanical field copy with no reuse across call sites.

```python
dto = await adapter.create_node(cfg=config, key=key, cloud_config=...)
node = replace(
    node,
    hostname=dto.hostname,
    external_id=dto.external_id,
    username=dto.username,
    port=dto.port,
    jump_host=dto.jump_host,
    jump_port=dto.jump_port,
    jump_username=dto.jump_username,
)
```

This replaces the current inline `replace(hostname=ip_addr, external_id=ip_addr, ...)`.

### Jump fields sourced by each adapter

`_setup_vm` no longer resolves jump fields. Each adapter sources jump fields from its own config DTO and includes them in `CloudCreateNodeDTO`. If the provider config has no jump host configured, the DTO carries `jump_host=None` and SSH connects directly.

This replaces the old `_setup_vm` jump-resolution logic (CloudConfig -> remote defaults fallback). Each adapter reads `cfg.jump_host`, `cfg.jump_port`, `cfg.jump_username` and sets them on the DTO. Remote defaults (`config.remote.*`) no longer apply to cloud nodes — jump configuration for a cloud provider belongs in that provider's config section.

### delete_node uses external_id

`CloudProvisionerImpl.deallocate()` and both error-handling paths in `allocate()` call `adapter.delete_node(cfg=config, external_id=node.external_id)` instead of `host=node.hostname`. All four provider `delete_node` functions rename the parameter accordingly; internal matching still uses IP-based lookup.

### CloudCreateNodeDTO location

New file `yascheduler/infra/cloud/dto.py`:

```python
@dataclass(frozen=True)
class CloudCreateNodeDTO:
    external_id: str
    hostname: str
    username: str = "root"
    port: int = 22
    jump_host: str | None = None
    jump_port: int = 22
    jump_username: str = "root"
```

Exported via `yascheduler/infra/cloud/__init__.py`.

### Provider create functions wrap IP in DTO

All four `*_create_node` functions follow the same pattern:

```python
ip_addr = ...  # existing logic unchanged
return CloudCreateNodeDTO(
    external_id=ip_addr,
    hostname=ip_addr,
    username=cfg.username,
    jump_host=cfg.jump_host,
    jump_port=cfg.jump_port,
    jump_username=cfg.jump_username or "root",
)
```

Port is not a field on ConfigCloud* DTOs, so the dataclass default of 22 applies. Future provider-specific configs can add a port field.

### Provider delete functions rename parameter

All four `*_delete_node` functions change signature: `host: str` -> `external_id: str`. Body unchanged.

### UpCloud typo fix

`upcload_delete_node` -> `upcloud_delete_node` in `providers/upcloud.py`, `providers/__init__.py`, `adapters.py`.

### Protocol changes

```python
class CreateNodeCallable(Protocol[TConfigCloud_contra]):
    async def __call__(self, cfg: ..., key: ..., cloud_config: ...) -> CloudCreateNodeDTO: ...

class DeleteNodeCallable(Protocol[TConfigCloud_contra]):
    async def __call__(self, cfg: ..., external_id: str) -> None: ...
```

### Testing strategy

- **Unit tests (existing `test_cloud_provisioner_impl.py`)**: update mocks to return `CloudCreateNodeDTO`; assert DTO fields mapped to Node correctly in `allocate`; assert `delete_node` called with `external_id` in `deallocate` and error paths; assert `_setup_vm` does not overwrite jump
- **Dedicated DTO test**: construction, defaults, immutability
- **E2e tests**: update return value assertions and mocks for Hetzner live test
- **No standalone unit tests for mapping function** (inline replace is not extracted)

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Provider creates DTO with wrong fields (e.g., missing external_id) | DTO is frozen; missing required field = type error at call site |
| Jump from remote defaults no longer applies to cloud nodes | Intended — jump config for a cloud provider belongs in that provider's INI section, not remote.* |
| Test mocks that return str will break | Tests are updated in the same change |
| Existing cloud nodes have external_id=ip, which is same as hostname — deallocate still works | external_id is already set; deallocate using external_id produces the same value as before |
