## MODIFIED Requirements

### Requirement: CloudCreateNodeDTO as create_node result

The system SHALL define `CloudCreateNodeDTO` as a `@dataclass(frozen=True)` in
`yascheduler.infra.cloud.dto` with: `external_id: str`, `hostname: str`,
`username: str = "root"`, `port: int = 22`, `jump_host: str | None = None`,
`jump_port: int = 22`, `jump_username: str = "root"`. The DTO SHALL be importable
via the `yascheduler.infra.cloud` subpackage facade.

`CreateNodeCallable` SHALL return `CloudCreateNodeDTO`. `DeleteNodeCallable`
SHALL accept `external_id: str` as the resource identifier parameter.

Each provider `*_create_node` SHALL return a `CloudCreateNodeDTO` with
`external_id` set to the VM's IP address for Azure and Upcloud, to
`str(server.id)` for Hetzner, and to the VastAI instance id (the identifier
issued by VastAI at instance creation) for VastAI; `hostname` set to the VM's
IP (all providers); and `username`, `port`, `jump_host`, `jump_port`,
`jump_username` sourced from the provider's config DTO (with their respective
defaults). For VastAI, `port` SHALL be the SSH port reported by the instance
at readiness, NOT a fixed default.

Each provider `*_delete_node` SHALL accept `external_id` and use it to locate
the resource. Provider-internal logic may match by IP for Azure and Upcloud;
Hetzner resolves via `client.servers.get_by_id(int(external_id))` — an O(1)
lookup that SHALL NOT iterate `client.servers.get_all()`; VastAI SHALL delete
the instance identified by `external_id` (the instance id), and the delete
SHALL be idempotent (an already-deleted instance is handled without raising).

#### Scenario: create_node returns DTO with IP-based identity

- **WHEN** `az_create_node` or `upcloud_create_node` succeeds
- **THEN** the return value is a `CloudCreateNodeDTO` whose `external_id` and `hostname` equal the VM's IP address

#### Scenario: hetzner_create_node returns DTO with server ID as external_id

- **WHEN** `hetzner_create_node` succeeds
- **THEN** the return value is a `CloudCreateNodeDTO` whose `external_id` equals `str(server.id)` (the numeric Hetzner server ID) and whose `hostname` equals the VM's IP address

#### Scenario: vastai_create_node returns DTO with instance id as external_id

- **WHEN** `vastai_create_node` succeeds and the instance has reached the ready state
- **THEN** the return value is a `CloudCreateNodeDTO` whose `external_id` equals the VastAI instance id, whose `hostname` equals the instance's SSH host (IP), whose `port` equals the instance's SSH port, and whose `username` is `"root"`

#### Scenario: create_node DTO carries config-derived connection parameters

- **WHEN** the DTO is constructed by a provider create function
- **THEN** `username` equals `cfg.username`, and the remaining connection fields (`port`, `jump_*`) carry the values from the provider's config DTO or their dataclass defaults

#### Scenario: delete_node identifies resource by external_id

- **WHEN** `adapter.delete_node(cfg=config, external_id=node.external_id)` is called
- **THEN** Azure and Upcloud locate the cloud resource by IP (external_id); Hetzner resolves via `client.servers.get_by_id(int(external_id))` (O(1), no `get_all()` iteration); VastAI deletes the instance identified by `external_id` (the instance id)

#### Scenario: hetzner_delete_node handles already-deleted server

- **WHEN** `hetzner_delete_node` is called for a server that no longer exists (already deleted)
- **THEN** `client.servers.get_by_id(int(external_id))` raises `APIException("not_found")`, the function logs "NODE %s NOT DELETED AS UNKNOWN" and returns without error

#### Scenario: vastai_delete_node deletes by instance id

- **WHEN** `vastai_delete_node(cfg, external_id="<instance_id>")` is called
- **THEN** the instance identified by `external_id` is deleted and billing stops; an already-deleted instance is handled without raising (idempotent delete)