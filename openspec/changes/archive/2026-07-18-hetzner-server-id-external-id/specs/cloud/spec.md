## MODIFIED Requirements

### Requirement: CloudCreateNodeDTO as create_node result

The system SHALL define `CloudCreateNodeDTO` as a `@dataclass(frozen=True)` in `yascheduler.infra.cloud.dto`:

- `external_id: str` — the cloud provider's native resource identifier
- `hostname: str` — the SSH-accessible address of the created VM
- `username: str = "root"` — the SSH login user
- `port: int = 22` — the SSH port
- `jump_host: str | None = None` — optional jump / bastion host
- `jump_port: int = 22` — jump host SSH port
- `jump_username: str = "root"` — jump host SSH login user

`CloudCreateNodeDTO`, `CreateNodeCallable`, and `DeleteNodeCallable` are unchanged by this change.

**Hetzner-specific changes:**

`hetzner_create_node` SHALL return a `CloudCreateNodeDTO` with `external_id` set to `str(server.id)` (the numeric Hetzner server ID) and `hostname` set to the VM's IP address. Other providers continue to set both `external_id` and `hostname` to the VM's IP address.

`hetzner_delete_node` SHALL resolve the server via `client.servers.get_by_id(int(external_id))` — an O(1) lookup that does NOT iterate all servers. The `find_srv` function (which listed all servers to find a match by IP) SHALL be removed.

`hetzner_delete_node` SHALL handle the case where `client.servers.get_by_id` raises `APIException` with `code="not_found"` (server already deleted) as a server-not-found condition — the function SHALL log "NODE %s NOT DELETED AS UNKNOWN" and return without error.

#### Scenario: hetzner_create_node returns DTO with server ID as external_id
- **WHEN** `hetzner_create_node` succeeds
- **THEN** the return value is a `CloudCreateNodeDTO` whose `external_id` equals `str(server.id)` (the numeric Hetzner server ID) and whose `hostname` equals the VM's IP address

#### Scenario: hetzner_delete_node resolves by server ID without listing all servers
- **WHEN** `hetzner_delete_node(cfg, external_id=node.external_id)` is called
- **THEN** the provider resolves the server via `client.servers.get_by_id(int(external_id))` — an O(1) lookup that SHALL NOT iterate `client.servers.get_all()`

#### Scenario: hetzner_delete_node handles already-deleted server (APIException not_found)
- **WHEN** `hetzner_delete_node` is called for a server that no longer exists (already deleted)
- **THEN** `client.servers.get_by_id(int(external_id))` raises `APIException("not_found")`, the function logs "NODE %s NOT DELETED AS UNKNOWN" and returns without error

#### Scenario: find_srv removed

- **WHEN** the code is inspected after the change
- **THEN** the `find_srv` function SHALL NOT exist in `yascheduler/infra/cloud/providers/hetzner.py`
