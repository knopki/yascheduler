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
in `yascheduler.domain.ports` capturing the 8-field surface that
application-layer consumers (`deallocate_nodes`, `orchestrator`) read:
`prefix: str`, `max_nodes: int`, `idle_tolerance: int`, `connect_grace: int`,
`username: str`, `jump_username: str | None`, `jump_host: str | None`,
`jump_port: int`.

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

The `jump_port` field SHALL declare default `22` on each DTO. The INI parser
SHALL read it from the `{prefix}_jump_port` key (default `22`).

The Protocol SHALL be importable via the `yascheduler.domain` facade and the deep
path `yascheduler.domain.ports`. The composition root and parser SHALL NOT
contain `cast(...)` CloudConfig/ConfigCloud bridges.

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

Each DTO SHALL declare a `jump_port: int` field (default `22`), the SSH port of
the provider's bastion / jump host leg. Unlike `package_upgrade`, `jump_port`
SHALL be on the `CloudConfig` Protocol because the cloud allocator stamps it
onto `Node.jump_port` alongside `jump_host` / `jump_username`.

#### Scenario: AzureImageReference.from_urn retained
- **WHEN** `AzureImageReference.from_urn("Debian:debian-11-daily:11-backports-gen2:latest")` is called
- **THEN** an `AzureImageReference(publisher="Debian", offer="debian-11-daily", sku="11-backports-gen2", version="latest")` is returned

#### Scenario: jump_port field present on all four DTOs

- **WHEN** each `ConfigCloud*` DTO is constructed without an explicit `jump_port`
- **THEN** the resulting instance has a `jump_port` attribute equal to `22`

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

Each per-prefix parser SHALL read the optional `{prefix}_jump_port` key as an
integer (default `22`) and surface it on the DTO's `jump_port` field. The parser
SHALL validate the range 1–65535 (mirroring the `yascheduler_nodes.jump_port`
DB `CHECK` constraint) at parse time, raising `ValueError` on any value outside
that range or on a non-integer value. The `{prefix}_jump_port` key SHALL
auto-register via the DTO field set so unknown-field warnings do NOT fire on it.

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
async, `deallocate` async, `select_provider` sync). It SHALL NOT access the
database, hold a `NodeRepository`, or open a Unit of Work.

`allocate(provider: str, node: Node) -> Node` SHALL receive a tmp-node `Node`
(the row already exists) and mutate it — SHALL NOT construct a fresh `Node`.
After VM creation, `allocate` SHALL resolve jump fields atomically from one
source: the matching `CloudConfig` when it sets both `jump_host` and
`jump_username`, otherwise from `config.remote.*` (fallback). Jump_host,
jump_port, and jump_username SHALL all come from the same source. Jump stamping
SHALL happen before the node is persisted as enabled.

`allocate` SHALL connect the node via `machine_repository.connect(...)` with no
`jump_host` / `jump_username` arguments. After cloud-init, engine setup, and
CPU detection, the returned `Node` carries `enabled=True`, `ncpus`, and the
stamped jump fields. On VM creation or setup failure, `allocate` SHALL raise
`CloudAllocateError` or `CloudSetupError`.

`deallocate(node: Node)` deletes the VM via the provider named by `node.cloud`,
using `node.hostname` as the cloud SDK host identifier. When `node.cloud` is
`None`, or when the named provider has no registered adapter or config,
`deallocate` SHALL log a warning and return without deleting.

`select_provider(platforms, current_counts) -> str | None` delegates to a pure
selection function and returns the selected adapter's name (or `None` on no
capacity or when the selected provider's op semaphore is locked).

#### Scenario: Allocate raises on VM creation failure

- **WHEN** `allocate(provider, node)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` is raised; the caller catches and cleans up the tmp-node by `remove(node.node_id)`

#### Scenario: No DB access from adapter

- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

#### Scenario: allocate stamps jump from CloudConfig when leg is authoritative

- **WHEN** `allocate` runs for a node with `cloud="hetzner"` and the `hetzner` `CloudConfig` has `jump_host="jump.example.com"`, `jump_username="jumper"`, `jump_port=2222`
- **THEN** the `replace(node, enabled=True, ...)` call produces a `Node` with `jump_host="jump.example.com"`, `jump_username="jumper"`, and `jump_port=2222`, and the subsequent `repository.connect(node=node, ...)` call passes no `jump_host` / `jump_username` arguments

#### Scenario: allocate falls back to remote defaults when CloudConfig lacks jump

- **WHEN** `allocate` runs for a node whose matching `CloudConfig` does NOT set both `jump_host` and `jump_username`, and `config.remote.jump_host` is set with `config.remote.jump_port=2222`
- **THEN** the `replace(node, enabled=True, ...)` call produces a `Node` whose `jump_host` / `jump_username` / `jump_port` come from `config.remote.*`

#### Scenario: allocate does not mix cloud jump_host with remote jump_port

- **WHEN** `allocate` runs for a node whose matching `CloudConfig` sets `jump_host` but NOT `jump_username`, and `config.remote.jump_port=2222`
- **THEN** the `replace(node, enabled=True, ...)` call produces a `Node` whose `jump_host`, `jump_username`, AND `jump_port` ALL come from `config.remote.*` (the cloud leg is not half-authoritative — fallback is all-or-nothing)

#### Scenario: allocate connects without jump kwargs

- **WHEN** `allocate` opens the setup SSH session via `machine_repository.connect`
- **THEN** the call is `connect(node=node, client_keys=keys, connect_timeout=adapter.create_node_conn_timeout, data_dir=..., engines_dir=..., tasks_dir=...)` — no `jump_host` / `jump_username` keyword arguments

#### Scenario: allocate setup does not write ncpus onto the Node

- **WHEN** `allocate` reaches the final `replace(node, enabled=True, ...)` after setup
- **THEN** the resulting `Node.ncpus is None` (no `ncpus=` kwarg is passed); the standalone `get_cpu_cores()` call is NOT made inside the setup path

#### Scenario: allocate DONE log is None-safe for ncpus

- **WHEN** `allocate` emits its DONE log line for a cloud node whose `ncpus is None`
- **THEN** the log line formats `node.ncpus` with a `None`-safe specifier (e.g. `%s`) and does NOT raise `TypeError`

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
hardcoded. The `packages` list continues to derive from platform-matched engines'
`platform_packages`.

#### Scenario: package_upgrade sourced from per-cloud config
- **WHEN** `CloudInitConfig` is built during cloud provisioning
- **THEN** `package_upgrade` is sourced from `config.package_upgrade` (default `True`), not from a global setting or hardcoded value

### Requirement: CloudProvisionerImpl.stop closes machine_repository connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_repository` by awaiting `machine_repository.disconnect_all()`.
`disconnect_all` is idempotent, so calling it from both `clouds.stop()` and
`Orchestrator.stop()` (shared instance) is safe.

#### Scenario: stop drains all machine connections
- **WHEN** `CloudProvisionerImpl.stop()` is called
- **THEN** `machine_repository.disconnect_all()` is awaited, closing every SSH connection held by the repository

### Requirement: Setup-failure disconnects machine_repository session

`CloudProvisionerImpl.allocate` SHALL disconnect the `machine_repository`
session for the failed node identity before deleting the VM on the
setup-failure path. Both `except` blocks following setup SHALL disconnect
BEFORE deleting the VM. Disconnect is a safe no-op when the `node_id` is
absent from sessions. The success path is unchanged: on a successful setup,
the session stays registered for orchestrator reuse.

#### Scenario: Setup failure disconnects before VM deletion
- **WHEN** setup raises `CloudSetupError` or a generic `Exception`
- **THEN** `machine_repository.disconnect(node.node_id)` is awaited BEFORE `adapter.delete_node(...)`
