## Why

`create_node` returns a bare `str` (IP), and `delete_node` takes `host: str` (also IP). This forces `CloudProvisionerImpl.allocate()` to construct Node fields manually from the IP and config — the adapter has no way to communicate non-default connection parameters (custom port, jump host) back to the provisioner. Additionally, `delete_node` should identify the cloud resource by `Node.external_id` (the provider's native ID), not `Node.hostname` (SSH address), which conflates provider identity with network address.

Without this change: adding a provider with non-standard SSH parameters requires workarounds; the external_id field exists but is never used for deletion; the type contract is weaker than it should be.

## What Changes

- **NEW** `CloudCreateNodeDTO` frozen dataclass in `infra/cloud/dto.py`:
  `external_id: str, hostname: str, username: str = "root", port: int = 22, jump_host: str | None = None, jump_port: int = 22, jump_username: str = "root"`
- **MODIFIED** `CreateNodeCallable` protocol: return type changes from `str` to `CloudCreateNodeDTO`
- **MODIFIED** `DeleteNodeCallable` protocol: parameter `host: str` renamed to `external_id: str`
- **MODIFIED** All 4 provider create functions (`az_create_node`, `hetzner_create_node`, `upcloud_create_node`, `vastai_create_node`): wrap the IP result in `CloudCreateNodeDTO(external_id=ip, hostname=ip, username=cfg.username, ...)`; other fields sourced from their config DTO
- **MODIFIED** All 4 provider delete functions: parameter `host` renamed to `external_id`; internal behaviour unchanged (still matches by IP)
- **MODIFIED** `CloudProvisionerImpl.allocate()`: maps `CloudCreateNodeDTO → Node` fields (hostname, external_id, username, port, jump*) instead of inline `replace(hostname=ip_addr, external_id=ip_addr, ...)`
- **MODIFIED** `CloudProvisionerImpl._setup_vm()`: jump resolution fills only fields still `None` on the Node, so DTO-sourced jump values are preserved
- **MODIFIED** `CloudProvisionerImpl.deallocate()`: calls `adapter.delete_node(cfg=config, external_id=node.external_id)` instead of `host=node.hostname`; error-handling paths in `allocate()` also switch to `external_id`
- **FIXED** UpCloud typo: `upcload_delete_node` → `upcloud_delete_node` in `providers/__init__.py`, `adapters.py`, `providers/upcloud.py`

## Capabilities

### Modified Capabilities

- `cloud`: `create_node` return type changes from `str` to `CloudCreateNodeDTO`; `delete_node` parameter `host` renamed to `external_id`; `CloudProvisionerImpl` allocate/deallocate mapping updated; jump resolution in `_setup_vm` becomes conditional so DTO-sourced jump fields are preserved; provider create functions wrap IP in DTO

## Impact

- `yascheduler/infra/cloud/protocols.py` — `CreateNodeCallable` return type, `DeleteNodeCallable` param
- `yascheduler/infra/cloud/dto.py` — new file
- `yascheduler/infra/cloud/providers/az.py` — create returns DTO, delete param rename
- `yascheduler/infra/cloud/providers/hetzner.py` — create returns DTO, delete param rename
- `yascheduler/infra/cloud/providers/upcloud.py` — create returns DTO, delete param rename + typo fix
- `yascheduler/infra/cloud/providers/vastai.py` — create returns DTO, delete param rename
- `yascheduler/infra/cloud/providers/__init__.py` — re-export rename
- `yascheduler/infra/cloud/adapters.py` — `get_upcloud_adapter` references renamed function
- `yascheduler/infra/cloud/manager.py` — allocate/deallocate mapping and jump resolution
- `yascheduler/infra/cloud/__init__.py` — may export `CloudCreateNodeDTO`
- Tests: unit mocks for provisioner tests, e2e live tests return value adaptation
- No change to: Node model, DB schema, domain ports, ConfigCloud* DTOs, cloud config parsers, cloud-init
- Non-goal: provider refactoring to use real provider-native external IDs (separate follow-up for Hetzner/VastAI)
