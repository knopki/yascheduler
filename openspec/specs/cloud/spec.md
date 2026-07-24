# Cloud

## Purpose

The cloud subsystem exists as an isolated boundary to decouple cloud-provider lifecycle management from the core scheduler — allowing providers (Hetzner, Upcloud, Azure, VastAI) to be added, removed, or maintained without affecting task allocation, SSH orchestration, or the domain model.
## Requirements
### Requirement: CloudConfig structural Protocol

The system SHALL define a structural `@runtime_checkable` `CloudConfig` Protocol
in `yascheduler.domain.ports` exposing `prefix: str`, `max_nodes: int`,
`idle_tolerance: int`, `connect_grace: int`, `username: str`,
`jump_username: str | None`, `jump_host: str | None`, `jump_port: int`. The
Protocol SHALL be importable via the `yascheduler.domain` facade and the deep
path `yascheduler.domain.ports`.

The `connect_grace` field SHALL declare per-provider defaults on each DTO:
`ConfigCloudHetzner.connect_grace = 60`, `ConfigCloudUpcloud.connect_grace = 60`,
`ConfigCloudAzure.connect_grace = 120`, `ConfigCloudVastAI.connect_grace = 120`.
The DTO default SHALL be the sole source — the INI parser SHALL NOT parse
`connect_grace`.

The `jump_port` field SHALL declare default `22` on each DTO. The INI parser
SHALL read it from the `{prefix}_jump_port` key (default `22`).

#### Scenario: connect_grace defaults on all four DTOs

- **WHEN** each DTO is constructed without an explicit `connect_grace`
- **THEN** `connect_grace == 60` for Hetzner/Upcloud and `connect_grace == 120` for Azure/VastAI

#### Scenario: jump_port default on all four DTOs

- **WHEN** each DTO is constructed without an explicit `jump_port`
- **THEN** `jump_port == 22`

### Requirement: Cloud config DTOs

The system SHALL define `ConfigCloudAzure`, `ConfigCloudHetzner`,
`ConfigCloudUpcloud`, `ConfigCloudVastAI`, `AzureImageReference`, and the
`ConfigCloud` Union alias as `@dataclass(frozen=True)` stdlib dataclasses with no
`attrs` dependency, no INI-parsing methods, and importable via the
`yascheduler.infra.cloud` subpackage facade.

`AzureImageReference.from_urn` SHALL be retained as a classmethod (a pure URN
string parser `publisher:offer:sku:version`, NOT an INI parser).

Each `ConfigCloud*` DTO SHALL declare `package_upgrade: bool = True` and
`jump_port: int = 22`.

#### Scenario: AzureImageReference.from_urn retained

- **WHEN** `AzureImageReference.from_urn("Debian:debian-11-daily:11-backports-gen2:latest")` is called
- **THEN** an `AzureImageReference(publisher="Debian", offer="debian-11-daily", sku="11-backports-gen2", version="latest")` is returned

#### Scenario: jump_port field present on all four DTOs

- **WHEN** each `ConfigCloud*` DTO is constructed without an explicit `jump_port`
- **THEN** the resulting instance has a `jump_port` attribute equal to `22`

### Requirement: Cloud config parser registry and functions

The system SHALL define
`CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]]` mapping
each cloud provider prefix (`az`, `hetzner`, `upcloud`, `vastai`) to its parser
function.

`parse_clouds(cfg, remote) -> list[CloudConfig]` SHALL derive `cloud_prefixes`
from `[clouds]` section options (split on `_`, take the first segment), inherit
`remote.username` into `[clouds]` for any prefix whose `{prefix}_user` is absent,
dispatch each prefix to the registry, and return the list of DTOs.

Each per-prefix parser SHALL read `{prefix}_package_upgrade` (default `True`) and
`{prefix}_jump_port` (integer, default `22`, range 1–65535). The parser SHALL
raise `ValueError` for `jump_port` outside 1–65535 or for non-integer values.

#### Scenario: parse_clouds inherits remote username

- **WHEN** `parse_clouds(cfg, remote)` is called and `[clouds]` lacks `hetzner_user` but `remote.username == "root"`
- **THEN** the parser reads `hetzner_user = "root"` when constructing `ConfigCloudHetzner`

#### Scenario: per-prefix jump_port defaults to 22 when key absent

- **GIVEN** an INI with a `[clouds]` section carrying `hetzner_token = tk` and NO `hetzner_jump_port`
- **WHEN** `parse_config(path)` constructs the `Config`
- **THEN** the resulting `ConfigCloudHetzner.jump_port == 22`

#### Scenario: per-prefix jump_port read from [clouds] section

- **GIVEN** an INI with `[clouds] hetzner_token = tk` and `hetzner_jump_port = 2222`
- **WHEN** `parse_config(path)` constructs the `Config`
- **THEN** the resulting `ConfigCloudHetzner.jump_port == 2222`

#### Scenario: per-prefix parser rejects jump_port below 1

- **GIVEN** an INI with `[clouds] az_jump_port = 0`
- **WHEN** `parse_config(path)` is called
- **THEN** `ValueError` is raised

#### Scenario: per-prefix parser rejects jump_port at or above 65536

- **GIVEN** an INI with `[clouds] upcloud_jump_port = 70000`
- **WHEN** `parse_config(path)` is called
- **THEN** `ValueError` is raised

### Requirement: Provider VM lifecycle modules

The system SHALL provide provider-specific VM lifecycle modules. Provider modules
SHALL import their config DTOs (`ConfigCloudAzure`, etc., `AzureImageReference`)
from `yascheduler.infra.cloud` (the subpackage facade), NOT via deep paths.

Optional provider SDKs SHALL be handled gracefully: the system SHALL skip
providers whose SDK is not installed, logging a warning instead of raising
`ImportError`.

`CloudInitConfig.render()` SHALL output a `"#cloud-config\n"`-prefixed JSON
serialization of all fields.

**Change notes**: The graceful-skip mechanism is now centralized in the adapter
resolution layer. Provider modules no longer carry `_*_AVAILABLE` flags or inline
`ImportError` guards. The import-path constraint (config DTOs from the subpackage
facade) is pre-existing and carried forward unchanged. Behavior is unchanged.

#### Scenario: CloudInitConfig render output

- **WHEN** `CloudInitConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the output is `"#cloud-config\n"`-prefixed JSON serialization of all fields

#### Scenario: Missing SDK skips provider gracefully

- **WHEN** a provider's SDK is not installed
- **THEN** the system skips that provider, logs a warning, and continues without crashing

### Requirement: CloudProvisionerImpl implements CloudProvisioner

`CloudProvisionerImpl` SHALL satisfy the `CloudProvisioner` Protocol (`allocate`
async, `deallocate` async, `select_provider` sync). It SHALL NOT access the
database, hold a `NodeRepository`, or open a Unit of Work.

`allocate(provider: str, node: Node) -> Node` SHALL receive a tmp-node (the row
already exists) and mutate it — SHALL NOT construct a fresh `Node`. After
`adapter.create_node`, `allocate` SHALL run SSH setup via `_setup_vm`. On VM
creation failure `allocate` SHALL raise `CloudAllocateError`; on setup failure it
SHALL raise `CloudSetupError`.

`deallocate(node: Node)` SHALL delete the VM via the provider named by
`node.cloud`, using `node.external_id` as the cloud SDK identifier. When
`node.cloud` is `None`, or the named provider has no registered adapter or
config, `deallocate` SHALL log a warning and return without deleting.

`select_provider(platforms, current_counts) -> str | None` SHALL delegate to a
pure selection function and return the selected adapter's name (or `None` on no
capacity or when the selected provider's op semaphore is locked).

#### Scenario: Allocate raises on VM creation failure

- **WHEN** `allocate(provider, node)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` is raised; the caller catches and cleans up the tmp-node by `remove(node.node_id)`

#### Scenario: No DB access from adapter

- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

#### Scenario: allocate maps DTO fields onto Node

- **WHEN** `allocate` runs and `adapter.create_node` returns a `CloudCreateNodeDTO(external_id="1.2.3.4", hostname="1.2.3.4", username="yascheduler", port=2222)`
- **THEN** the resulting `Node` has `hostname="1.2.3.4"`, `external_id="1.2.3.4"`, `username="yascheduler"`, `port=2222`

#### Scenario: _setup_vm preserves DTO-sourced jump values

- **WHEN** the Node after DTO mapping already has `jump_host="dto-jump.example.com"` (not `None`)
- **THEN** `_setup_vm` does NOT overwrite `jump_host`, `jump_port`, or `jump_username` — the DTO-sourced values are preserved

#### Scenario: allocate connects without jump kwargs

- **WHEN** `allocate` opens the setup SSH session via `machine_repository.connect`
- **THEN** the call is `connect(node=node, client_keys=keys, connect_timeout=adapter.create_node_conn_timeout, data_dir=..., engines_dir=..., tasks_dir=...)` — no `jump_host` / `jump_username` keyword arguments

#### Scenario: allocate setup does not write ncpus onto the Node

- **WHEN** `allocate` reaches the final `replace(node, enabled=True, ...)` after setup
- **THEN** the resulting `Node.ncpus is None` (no `ncpus=` kwarg is passed); the standalone `get_cpu_cores()` call is NOT made inside the setup path

#### Scenario: deallocate uses external_id to identify VM

- **WHEN** `deallocate(node)` is called and `node.cloud` is a known provider with a registered adapter and config
- **THEN** `adapter.delete_node(cfg=config, external_id=node.external_id)` is called (NOT `host=node.hostname`)

#### Scenario: setup failure deletes VM by external_id

- **WHEN** setup raises `CloudSetupError` or a generic `Exception`
- **THEN** `machine_repository.disconnect(node.node_id)` is awaited BEFORE `adapter.delete_node(cfg=config, external_id=node.external_id)`

#### Scenario: deallocate warns on missing or unknown cloud

- **WHEN** `deallocate(node)` is called and `node.cloud` is `None`, or the named provider has no adapter or config
- **THEN** a warning is logged and the method returns without calling `delete_node`

### Requirement: Cloud-init rendering and SSH key management

SSH key generation, loading, and name extraction SHALL live in the cloud
subsystem. The cloud-init user-data renderer SHALL be a single concrete frozen
dataclass `CloudInitConfig`. Provider `*_create_node` callables SHALL type their
`cloud_config` parameter as `CloudInitConfig | None` (the concrete class).

#### Scenario: SSH keys module location

- **WHEN** SSH key generation or loading is needed
- **THEN** the code lives in the cloud subsystem

### Requirement: Cloud-init package_upgrade sourced from per-cloud config

The system SHALL build the `CloudInitConfig` with `package_upgrade` sourced from
`config.package_upgrade` (default `True`), NOT from a global setting and NOT
hardcoded.

#### Scenario: package_upgrade sourced from per-cloud config

- **WHEN** `CloudInitConfig` is built during cloud provisioning
- **THEN** `package_upgrade` is sourced from `config.package_upgrade` (default `True`), not from a global setting or hardcoded value

### Requirement: CloudProvisionerImpl.stop closes machine_repository connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_repository` by awaiting `machine_repository.disconnect_all()`.

#### Scenario: stop drains all machine connections

- **WHEN** `CloudProvisionerImpl.stop()` is called
- **THEN** `machine_repository.disconnect_all()` is awaited, closing every SSH connection held by the repository

### Requirement: Setup-failure disconnects machine_repository session

`CloudProvisionerImpl.allocate` SHALL `await
machine_repository.disconnect(node.node_id)` on the setup-failure path BEFORE
`adapter.delete_node(...)`. Both `except` blocks following setup SHALL disconnect
BEFORE deleting the VM.

#### Scenario: Setup failure disconnects before VM deletion

- **WHEN** setup raises `CloudSetupError` or a generic `Exception`
- **THEN** `machine_repository.disconnect(node.node_id)` is awaited BEFORE `adapter.delete_node(...)`

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

