# Cloud

## Purpose

The cloud subsystem: the `CloudConfig` domain Protocol and the frozen
`ConfigCloud*` DTOs, the per-prefix parser registry, the provider-specific VM
lifecycle modules, the `CloudProvisioner` port, and the `CloudProvisionerImpl`
adapter managing cloud provider selection, VM provisioning (allocate/deallocate),
cloud-init rendering, SSH key management, node setup after provisioning, and
concurrent-allocation throttling.

## Requirements

### Requirement: CloudConfig structural Protocol

The system SHALL define a structural `@runtime_checkable` `CloudConfig` Protocol
in `yascheduler.domain.ports` capturing the 7-field surface that
application-layer consumers (`deallocate_nodes`, `orchestrator`) read:
`prefix: str`, `max_nodes: int`, `idle_tolerance: int`, `connect_grace: int`,
`username: str`, `jump_username: str | None`, `jump_host: str | None`.

The concrete `ConfigCloud*` DTOs SHALL explicitly inherit the Protocol (a typing
aid; structural matching per PEP 544 still applies). Application-layer consumers
SHALL type their `config_clouds` / `active_clouds` parameters as
`Sequence[CloudConfig]` (domain Protocol), NOT `Sequence[ConfigCloud]` (infra
Union), keeping `application → infra` TYPE_CHECKING-only.

The `connect_grace` field SHALL declare per-provider defaults on each DTO:
`ConfigCloudHetzner.connect_grace = 60`, `ConfigCloudUpcloud.connect_grace = 60`,
`ConfigCloudAzure.connect_grace = 120`, `ConfigCloudVastAI.connect_grace = 120`.
The INI parser SHALL NOT parse `connect_grace` from the INI file — the DTO
default is the sole source.

The Protocol SHALL be importable via the `yascheduler.domain` facade and the deep
path `yascheduler.domain.ports`. The composition root and parser SHALL NOT
contain `cast(...)` CloudConfig/ConfigCloud bridges.

#### Scenario: connect_grace defaults on all four DTOs
- **WHEN** each DTO is constructed without an explicit `connect_grace`
- **THEN** `connect_grace == 60` for Hetzner/Upcloud and `connect_grace == 120` for Azure/VastAI

### Requirement: Cloud config DTOs

The system SHALL define `ConfigCloudAzure`, `ConfigCloudHetzner`,
`ConfigCloudUpcloud`, `ConfigCloudVastAI`, `AzureImageReference`, and the
`ConfigCloud` Union alias as `@dataclass(frozen=True)` stdlib dataclasses with no
`attrs` dependency and no INI-parsing methods on the DTOs.

`AzureImageReference.from_urn` SHALL be retained as a classmethod (a pure URN
string parser `publisher:offer:sku:version`, NOT an INI parser). The DTOs SHALL
be importable via the `yascheduler.infra.cloud` subpackage facade.
`AzureImageReference` SHALL NOT inherit `CloudConfig`. The runtime
`from yascheduler.domain import CloudConfig` import in the DTO module is
permitted by the layers contract (`infra` sits above `domain`); no circular-
import risk (`domain/ports.py` imports only stdlib `typing`).

Each DTO SHALL declare a `package_upgrade: bool` field (default `True`),
controlling the cloud-init `package_upgrade` flag on freshly-provisioned VMs for
that provider. `package_upgrade` SHALL NOT be on the `CloudConfig` Protocol — it
is read only by infra (`CloudProvisionerImpl`), like `token`/`vm_size`.

#### Scenario: AzureImageReference.from_urn retained
- **WHEN** `AzureImageReference.from_urn("Debian:debian-11-daily:11-backports-gen2:latest")` is called
- **THEN** an `AzureImageReference(publisher="Debian", offer="debian-11-daily", sku="11-backports-gen2", version="latest")` is returned

### Requirement: Cloud config parser registry and functions

The system SHALL define
`CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]]`
mapping each cloud provider prefix (`az`, `hetzner`, `upcloud`, `vastai`) to its
parser function. Adding a new provider SHALL require only: (1) a frozen DTO,
(2) a parser function, (3) one `CLOUD_CONFIG_PARSERS` entry — no edit to
`Config` assembly.

`parse_clouds(cfg, remote) -> list[CloudConfig]` SHALL derive `cloud_prefixes`
from `[clouds]` section options (split on `_`, take the first segment), inherit
`remote.username` into `[clouds]` for any prefix whose `{prefix}_user` is absent,
dispatch each prefix to the registry, and return the list of DTOs. Validation
SHALL run inside the per-prefix parser functions before constructing the DTO —
not in `__post_init__`.

Each per-prefix parser SHALL read the optional `{prefix}_package_upgrade` key
with default `True`; the known key set derives from the DTO fields, so
`{prefix}_package_upgrade` auto-registers and unknown-field warnings do NOT fire.

#### Scenario: parse_clouds inherits remote username
- **WHEN** `parse_clouds(cfg, remote)` is called and `[clouds]` lacks `hetzner_user` but `remote.username == "root"`
- **THEN** the parser reads `hetzner_user = "root"` when constructing `ConfigCloudHetzner`

### Requirement: Provider VM lifecycle modules

The system SHALL provide provider-specific VM lifecycle modules. Provider
modules SHALL import their config DTOs (`ConfigCloudAzure`, etc.,
`AzureImageReference`) from `yascheduler.infra.cloud` (the subpackage facade),
NOT via deep paths.

Optional provider SDKs SHALL be handled gracefully: the system SHALL skip
providers whose SDK is not installed, logging a warning instead of raising
`ImportError`.

`CloudInitConfig.render()` SHALL output a `"#cloud-config\n"`-prefixed JSON
serialization of all fields.

#### Scenario: CloudInitConfig render output
- **WHEN** `CloudInitConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the output is `"#cloud-config\n"`-prefixed JSON serialization of all fields

### Requirement: CloudProvisionerImpl implements CloudProvisioner

`CloudProvisionerImpl` SHALL satisfy the `CloudProvisioner` Protocol (`allocate`
async, `deallocate` async, `select_provider` sync). It SHALL be a pure cloud-API
adapter — it SHALL NOT access the database, SHALL NOT hold a `NodeRepository`,
and SHALL NOT open any Unit of Work. Node persistence is owned by use cases.

`allocate(provider: str, node: Node) -> Node` receives the tmp-node `Node`
(post-persistence identity — the row already exists with the tmp `node_id`).
This reuses the tmp-node row as the real node's identity: the cloud setup SSH
session registers under `node.node_id`, and the caller's persist step is a
single `update(node)` rather than `insert(NewNode) + remove(tmp_node_id)`.

After the VM is created, `allocate` SHALL derive the node identity exactly once
(flipping `ip`, `cloud`, `username` on the passed Node) and thread that single
`Node` object down. `allocate` SHALL NOT construct a fresh `Node`, and the
private helpers SHALL NOT reconstruct one. `port` is carried through unchanged
(the tmp node's `port` default is preserved).

On VM creation/setup failure `allocate` SHALL raise `CloudAllocateError` or
`CloudSetupError` (domain exceptions). `deallocate(node: Node)` deletes the VM
via the provider named by `node.cloud`, using `node.ip` as the cloud SDK host
identifier. When `node.cloud` is `None`, `deallocate` SHALL log a warning and
return without deleting. When the named provider has no registered adapter or
config, `deallocate` SHALL log a warning and return.
`select_provider(platforms, current_counts) -> str | None` delegates to a pure
selection function and returns the selected adapter's name (or `None` on no
capacity OR when the selected provider's op semaphore is locked — throttle).

`allocate` connects the node via the machine repository and registers the
session under `node.node_id`. After cloud-init, engine setup, and CPU detection,
the node identity is returned with `enabled` flipped and `ncpus` populated (the
same identity, NOT a freshly constructed `Node` and NOT a `NewNode`).

#### Scenario: Allocate raises on VM creation failure
- **WHEN** `allocate(provider, node)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` is raised; the caller catches and cleans up the tmp-node by `remove(node.node_id)`

#### Scenario: No DB access from adapter
- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

### Requirement: Cloud-init rendering and SSH key management

SSH key generation, loading, and name extraction SHALL live in the cloud
subsystem. The cloud-init user-data renderer SHALL be a single concrete frozen
dataclass `CloudInitConfig`. There SHALL be no `PCloudConfig` Protocol. Provider
`*_create_node` callables SHALL type their `cloud_config` parameter as
`CloudInitConfig | None` (the concrete class). The `az_create_node` public entry
point SHALL NOT carry a runtime `isinstance` boundary guard narrowing
`cloud_config`.

#### Scenario: SSH keys module location
- **WHEN** SSH key generation or loading is needed
- **THEN** the code lives in the cloud subsystem

### Requirement: Cloud-init package_upgrade sourced from per-cloud config

The system SHALL build the `CloudInitConfig` with `package_upgrade` sourced from
`config.package_upgrade` (default `True`), NOT from a global setting and NOT
hardcoded. The `packages` list continues to derive from platform-matched engines'
`platform_packages`.

#### Scenario: package_upgrade sourced from per-cloud config
- **WHEN** `CloudInitConfig` is built during cloud provisioning
- **THEN** `package_upgrade` is sourced from `config.package_upgrade` (default `True`), not from a global setting or hardcoded value

### Requirement: CloudProvisionerImpl.stop closes machine_repository connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_repository` by awaiting `machine_repository.disconnect_all()`.
`allocate` opens connections during cloud allocation and does not disconnect them
on success. Without `stop()` draining the repository, those connections leak.
`disconnect_all` on `SSHMachineRepository` is idempotent, so calling it from
both `clouds.stop()` and `Orchestrator.stop()` (shared instance) is safe.

#### Scenario: stop drains all machine connections
- **WHEN** `CloudProvisionerImpl.stop()` is called
- **THEN** `machine_repository.disconnect_all()` is awaited, closing every SSH connection held by the repository

### Requirement: Setup-failure disconnects machine_repository session

`CloudProvisionerImpl.allocate` SHALL disconnect the `machine_repository`
session for the failed node identity before deleting the VM on the
setup-failure path. Both `except` blocks following setup (the `CloudSetupError`
handler and the generic `Exception` handler) SHALL disconnect BEFORE deleting
the VM. Without this, a failed allocation would leak a stale `FREE` session
pointing at a deleted VM. Disconnect is a safe no-op when the `node_id` is
absent from sessions, so calling it when setup itself failed (no session
registered) is harmless. The success path is unchanged: on a successful setup,
the session stays registered for orchestrator reuse.

#### Scenario: Setup failure disconnects before VM deletion
- **WHEN** setup raises `CloudSetupError` or a generic `Exception`
- **THEN** `machine_repository.disconnect(node.node_id)` is awaited BEFORE `adapter.delete_node(...)`
