# Cloud

## Purpose

The cloud subsystem: the `CloudConfig` domain Protocol and the frozen
`ConfigCloud*` DTOs (`infra/cloud/cloud_configs.py`), the per-prefix parser
registry and parser functions (`entrypoints/config_parser.py`), the
provider-specific VM lifecycle modules (`infra/cloud/providers/`), the
`CloudProvisioner` port, and the `CloudProvisionerImpl` adapter managing cloud
provider selection, VM provisioning (allocate/deallocate), cloud-init rendering,
SSH key management, node setup after provisioning, and concurrent-allocation
throttling.

## Requirements

### Requirement: CloudConfig structural Protocol

The system SHALL define a structural `@runtime_checkable` `CloudConfig` Protocol
in `yascheduler/domain/ports.py` capturing the 7-field surface that
application-layer consumers (`deallocate_nodes`, `orchestrator`) read:
`prefix: str`, `max_nodes: int`, `idle_tolerance: int`, `connect_grace: int`,
`username: str`, `jump_username: str | None`, `jump_host: str | None`.

The concrete `ConfigCloud*` DTOs in `infra/cloud/cloud_configs.py` SHALL
explicitly inherit the Protocol (a typing aid; structural matching per PEP 544
still applies). Application-layer consumers SHALL type their `config_clouds` /
`active_clouds` parameters as `Sequence[CloudConfig]` (domain Protocol), NOT
`Sequence[ConfigCloud]` (infra Union), keeping `application → infra`
TYPE_CHECKING-only.

The `connect_grace` field SHALL declare per-provider defaults on each DTO:
`ConfigCloudHetzner.connect_grace = 60`, `ConfigCloudUpcloud.connect_grace = 60`,
`ConfigCloudAzure.connect_grace = 120`, `ConfigCloudVastAI.connect_grace = 120`.
The INI parser SHALL NOT parse `connect_grace` from the INI file — the DTO
default is the sole source.

The Protocol SHALL be importable via the `yascheduler.domain` facade and the deep
path `yascheduler.domain.ports`. The composition root (`entrypoints/di.py`) and
parser (`entrypoints/config_parser.py`) SHALL NOT contain `cast(...)`
CloudConfig/ConfigCloud bridges.

#### Scenario: CloudConfig Protocol is runtime_checkable
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
- **THEN** it returns `True`

#### Scenario: DTOs explicitly inherit CloudConfig
- **WHEN** each `ConfigCloud*` DTO's `__mro__` is introspected
- **THEN** `CloudConfig` from `yascheduler.domain` appears in the MRO

#### Scenario: connect_grace defaults on all four DTOs
- **WHEN** each DTO is constructed without an explicit `connect_grace`
- **THEN** `connect_grace == 60` for Hetzner/Upcloud and `connect_grace == 120` for Azure/VastAI

### Requirement: Cloud config DTOs

The system SHALL define `ConfigCloudAzure`, `ConfigCloudHetzner`,
`ConfigCloudUpcloud`, `ConfigCloudVastAI`, `AzureImageReference`, and the
`ConfigCloud` Union alias in `yascheduler/infra/cloud/cloud_configs.py` as
`@dataclass(frozen=True)` stdlib dataclasses with no `attrs` dependency and no
INI-parsing methods (`from_config_parser_section`, `get_valid_config_parser_fields`).

`AzureImageReference.from_urn` SHALL be retained as a classmethod (a pure URN
string parser `publisher:offer:sku:version`, NOT an INI parser). The DTOs SHALL
be importable via the `yascheduler.infra.cloud` subpackage facade; the deep path
is for intra-package use only. `AzureImageReference` SHALL NOT inherit
`CloudConfig`. The runtime `from yascheduler.domain import CloudConfig` import in
`cloud_configs.py` is permitted by the layers contract (`infra` sits above
`domain`); no circular-import risk (`domain/ports.py` imports only stdlib
`typing`).

Each DTO SHALL declare a `package_upgrade: bool` field (default `True`),
controlling the cloud-init `package_upgrade` flag on freshly-provisioned VMs for
that provider. `package_upgrade` SHALL NOT be on the `CloudConfig` Protocol — it
is read only by infra (`CloudProvisionerImpl`), like `token`/`vm_size`.

#### Scenario: DTOs are stdlib frozen dataclasses
- **WHEN** any `ConfigCloud*` DTO is introspected
- **THEN** it is `@dataclass(frozen=True)`, has no `attrs`-defined fields, and raises on field assignment after construction

#### Scenario: AzureImageReference.from_urn retained
- **WHEN** `AzureImageReference.from_urn("Debian:debian-11-daily:11-backports-gen2:latest")` is called
- **THEN** an `AzureImageReference(publisher="Debian", offer="debian-11-daily", sku="11-backports-gen2", version="latest")` is returned

#### Scenario: AzureImageReference.from_urn rejects malformed URN
- **WHEN** `AzureImageReference.from_urn("bad-urn")` is called
- **THEN** `ValueError` is raised

#### Scenario: package_upgrade defaults to True
- **WHEN** each DTO is constructed without a `package_upgrade` argument
- **THEN** the resulting instance has `package_upgrade is True`

### Requirement: Cloud config parser registry and functions

The system SHALL define
`CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]]` in
`entrypoints/config_parser.py` mapping each cloud provider prefix (`az`,
`hetzner`, `upcloud`, `vastai`) to its parser function. The registry lives at the
composition-root layer so `infra → entrypoints` stays R3-legal. Adding a new
provider SHALL require only: (1) a frozen DTO in `infra/cloud/cloud_configs.py`,
(2) a parser function in `entrypoints/config_parser.py`, (3) one
`CLOUD_CONFIG_PARSERS` entry — no edit to `Config.from_config_parser`.

`parse_cloud_section(sec, prefix) -> CloudConfig` SHALL dispatch to
`CLOUD_CONFIG_PARSERS[prefix]`; unknown prefixes raise `KeyError`.
`parse_clouds(cfg, remote) -> list[CloudConfig]` SHALL derive `cloud_prefixes`
from `[clouds]` section options (split on `_`, take the first segment), inherit
`remote.username` into `[clouds]` for any prefix whose `{prefix}_user` is absent,
dispatch each prefix to the registry, and return the list of DTOs. Validation
(`warn_unknown_fields`, `validators.ge(...)`, `_check_az_user`, `opt_str_val`)
SHALL run inside the per-prefix parser functions before constructing the DTO —
not in `__post_init__`.

Each per-prefix parser (`_parse_azure_section`, etc.) SHALL read the optional
`{prefix}_package_upgrade` key via `sec.getboolean(fmt("package_upgrade"),
fallback=True)`; `cloud_valid_fields(prefix)` derives the known key set from
`dataclasses.fields(dto_cls)`, so `{prefix}_package_upgrade` auto-registers and
`warn_unknown_fields` does NOT warn about it.

#### Scenario: Registry maps all four prefixes
- **WHEN** `CLOUD_CONFIG_PARSERS` is inspected
- **THEN** it contains exactly the keys `az`, `hetzner`, `upcloud`, `vastai` mapped to callables

#### Scenario: parse_clouds inherits remote username
- **WHEN** `parse_clouds(cfg, remote)` is called and `[clouds]` lacks `hetzner_user` but `remote.username == "root"`
- **THEN** the parser reads `hetzner_user = "root"` when constructing `ConfigCloudHetzner`

#### Scenario: ConfigCloudAzure rejects username root via parser
- **WHEN** `parse_cloud_section(sec, "az")` parses an `[clouds]` section with `az_user = root`
- **THEN** the parser raises `ValueError("Root user is forbidden on Azure")`

#### Scenario: package_upgrade parsed per provider
- **WHEN** `parse_clouds(cfg, remote)` parses `[clouds]` with `hetzner_package_upgrade = false`
- **THEN** the returned `ConfigCloudHetzner` has `package_upgrade is False`, and the key does NOT warn as unknown

### Requirement: Provider VM lifecycle modules relocated

The system SHALL provide provider-specific VM lifecycle modules at
`infra/cloud/providers/{az,hetzner,upcloud,vastai}.py`. Provider modules SHALL
import their config DTOs (`ConfigCloudAzure`, etc., `AzureImageReference`) from
`yascheduler.infra.cloud` (the subpackage facade, R2-compliant), NOT via deep
paths. The system SHALL move cloud support modules (adapters, protocols, utils)
to `infra/cloud/` preserving their functionality.

Optional provider SDKs SHALL be handled gracefully: the system SHALL skip
providers whose SDK is not installed, logging a warning instead of raising
`ImportError`.

`CloudInitConfig.render()` SHALL output a `"#cloud-config\n"`-prefixed JSON
serialization of all fields.

#### Scenario: Azure provider accessible
- **WHEN** `az_create_node` is imported from `infra.cloud.providers.az`
- **THEN** the function is available and creates Azure VMs

#### Scenario: Provider modules import config DTOs from infra cloud facade
- **WHEN** `infra/cloud/providers/az.py` is inspected for its `ConfigCloudAzure` / `AzureImageReference` import
- **THEN** the import is `from yascheduler.infra.cloud import ConfigCloudAzure, AzureImageReference` (R2 facade path)

#### Scenario: Azure SDK not installed
- **WHEN** the Azure provider is configured but `azure-identity` is not installed
- **THEN** a warning is logged and the provider is excluded from capacity

#### Scenario: CloudInitConfig render output
- **WHEN** `CloudInitConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the output is `"#cloud-config\n"`-prefixed JSON serialization of all fields

### Requirement: CloudProvisionerImpl implements CloudProvisioner

`CloudProvisionerImpl` (`infra/cloud/manager.py`) SHALL satisfy the
`CloudProvisioner` Protocol (`allocate` async, `deallocate` async,
`select_provider` sync). It SHALL be a pure cloud-API adapter — it SHALL NOT
access the database, SHALL NOT hold a `NodeRepository`, and SHALL NOT open any
Unit of Work. Node persistence is owned by use cases.

`allocate(provider: str, node: Node) -> Node` receives the tmp-node `Node`
(post-persistence identity — the row already exists with the tmp `node_id`; the
caller enabled it via `NodeRepository.update`). This reuses the tmp-node row
inserted by `_select_and_insert_tmp` as the real node's identity: the cloud
setup SSH session registers under `node.node_id`, and the caller's persist step
is a single `update(node)` (flipping `enabled` to TRUE, setting `ip`/`ncpus`)
rather than `insert(NewNode) + remove(tmp_node_id)`.

After `adapter.create_node(...)` returns the VM `ip_addr`, `allocate` SHALL
derive the node identity exactly once via
`replace(node, ip=ip_addr, cloud=adapter.name, username=config.username)` and
thread that single `Node` object down into `_setup_vm(node, adapter, config)`.
`allocate` SHALL NOT construct a fresh `Node`, and the private helpers SHALL NOT
reconstruct one — the enabled node is derived from this object via
`dataclasses.replace`. `port` is carried through unchanged (the tmp node's
`port` default is preserved).

On VM creation/setup failure `allocate` SHALL raise `CloudAllocateError` or
`CloudSetupError` (domain exceptions). `deallocate(node: Node)` deletes the VM
via the provider named by `node.cloud`, using `node.ip` as the cloud SDK host
identifier (unchanged VM-lookup mechanism). When `node.cloud` is `None`,
`deallocate` SHALL log a warning and return without deleting. When the named
provider has no registered adapter or config, `deallocate` SHALL log a warning
and return. `select_provider(platforms, current_counts) -> str | None`
delegates to the pure `select_provider_pure(adapters, configs, platforms,
current_counts, log)` and returns the selected adapter's name (or `None` on no
capacity OR when the selected provider's op semaphore is locked — throttle).

`_setup_vm(node: Node, adapter, config)` SHALL call
`_connect_to_vm(node, adapter, config)`, which calls
`machine_repository.connect(node=node, client_keys=..., ...)` (passing the
single `Node` straight through — NO ersatz `Node` is constructed inside
`_connect_to_vm`, and NO `username`/`port` arguments are passed since `connect`
reads them from `node`), registering the session under `node.node_id`. After
cloud-init, engine setup, and CPU detection, `_setup_vm` SHALL return
`replace(node, enabled=True, ncpus=ncpus)` (a `Node` — the same identity with
`enabled` flipped and `ncpus` populated, NOT a freshly constructed `Node` and
NOT a `NewNode`).

The `configs: dict[str, ConfigCloud]` field SHALL be typed against the
`ConfigCloud` Union. `_connect_to_vm` SHALL access `config.jump_host` /
`config.jump_username` via direct attribute access.

#### Scenario: Allocate node on selected provider reuses the passed node identity

- **WHEN** `allocate("aws", node)` is called with a provider name that has a registered adapter and a tmp-node `Node` carrying `node_id == NodeId(7)`
- **THEN** a VM is created, set up via a session registered under `NodeId(7)`, and a `Node(node_id=NodeId(7), ip=<vm_ip>, enabled=True, …)` is returned (no DB write inside the adapter; the caller persists via `NodeRepository.update`)

#### Scenario: Allocate raises on VM creation failure

- **WHEN** `allocate(provider, node)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` is raised; the caller catches and cleans up the tmp-node by `remove(node.node_id)`

#### Scenario: Deallocate reads provider and host from the node

- **WHEN** `deallocate(node)` is called with `node.cloud="aws"` and `node.ip="10.0.0.1"`
- **THEN** the VM at `10.0.0.1` is deleted via the `aws` provider's SDK

#### Scenario: Deallocate no-ops on None cloud

- **WHEN** `deallocate(node)` is called with `node.cloud` of `None`
- **THEN** no provider SDK is invoked; the adapter logs a warning and returns

#### Scenario: No DB access from adapter

- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

#### Scenario: Provider op-limit returns None

- **WHEN** the highest-priority provider with capacity has its op semaphore locked
- **THEN** `select_provider` returns `None` (does not raise); the caller's `selection is None` branch handles cleanup

### Requirement: Cloud-init rendering and SSH key management

SSH key generation, loading, and name extraction SHALL live in
`infra/cloud/ssh_keys.py`. The cloud-init user-data renderer SHALL be a single
concrete frozen dataclass `CloudInitConfig` in `infra/cloud/cloud_init.py`. There
SHALL be no `PCloudConfig` Protocol in `infra/cloud/protocols.py`. Provider
`*_create_node` callables and `CreateNodeCallable.__call__` SHALL type their
`cloud_config` parameter as `CloudInitConfig | None` (the concrete class). The
`az_create_node` public entry point SHALL NOT carry a runtime `isinstance`
boundary guard narrowing `cloud_config`.

#### Scenario: SSH key generated for cloud provisioning
- **WHEN** a cloud provider needs an SSH key
- **THEN** the key is generated or loaded via `infra/cloud/ssh_keys.py`

#### Scenario: Provider create_node callables type cloud_config as CloudInitConfig
- **WHEN** each `*_create_node` is inspected for its `cloud_config` parameter annotation
- **THEN** the annotation is `CloudInitConfig | None`, imported from `yascheduler.infra.cloud` or `...cloud_init`

### Requirement: Cloud-init package_upgrade sourced from per-cloud config

The system SHALL build the `CloudInitConfig` passed to provider `create_node`
callables via `CloudProvisionerImpl._get_cloud_config_data(self, adapter,
config: ConfigCloud)` with `package_upgrade` sourced from
`config.package_upgrade` (default `True`), NOT from
`self.local_config.cloud_package_upgrade` (which no longer exists) and NOT
hardcoded. The `config` parameter SHALL be typed `ConfigCloud` (the infra Union),
NOT the domain `CloudConfig` Protocol — `package_upgrade` is on the concrete DTOs
only. The sole caller `allocate` SHALL pass the resolved `config =
self.configs.get(provider)`. The `packages` list continues to derive from
platform-matched engines' `platform_packages`.

#### Scenario: package_upgrade reflects config.package_upgrade
- **WHEN** `_get_cloud_config_data(adapter, config)` builds the `CloudInitConfig` and `config.package_upgrade is True` (resp. `False`)
- **THEN** the resulting `CloudInitConfig.package_upgrade is True` (resp. `False`)

#### Scenario: _get_cloud_config_data receives the resolved per-cloud config
- **WHEN** `CloudProvisionerImpl.allocate("hetzner")` is inspected
- **THEN** it resolves `config = self.configs.get("hetzner")` and passes that same `config` to `_get_cloud_config_data`

### Requirement: CloudProvisionerImpl.stop closes machine_repository connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_repository` by awaiting `machine_repository.disconnect_all()`.
`_setup_vm` opens connections via `machine_repository.connect(node)` during
cloud allocation, and `allocate` does not disconnect them on success. Without
`stop()` draining the repository, those connections leak. `disconnect_all` on
`SSHMachineRepository` is idempotent, so calling it from both `clouds.stop()`
and `Orchestrator.stop()` (shared instance per `dependency-injection`) is safe.

#### Scenario: stop drains all connections

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose `machine_repository` holds one or more connected sessions
- **THEN** `machine_repository.disconnect_all()` is awaited exactly once and every connection present at call time is closed

#### Scenario: stop with empty repository is a safe no-op

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose `machine_repository` holds zero sessions
- **THEN** `disconnect_all()` is still awaited (no effect) and `stop()` does not raise

#### Scenario: stop is idempotent under repeated calls

- **WHEN** `await clouds.stop()` is called twice in succession
- **THEN** both calls complete without raising; the second is a no-op (the repository's `_sessions` is already empty)
### Requirement: Setup-failure disconnects machine_repository session

`CloudProvisionerImpl.allocate` SHALL disconnect the `machine_repository`
session for the failed node identity before deleting the VM on the
setup-failure path. Both `except` blocks following `_setup_vm` (the
`CloudSetupError` handler and the generic `Exception` handler) SHALL
`await self.machine_repository.disconnect(node.node_id)` BEFORE
`await adapter.delete_node(...)`, where `node` is the single identity object
`allocate` constructed after `create_node` (`node.node_id == tmp_node_id`).
Without this, a failed allocation would
leak a stale `FREE` session in `_sessions[node.node_id]` pointing at a deleted
VM — the allocator would then pick that session, attempt operations on it, and
raise `asyncssh.misc.ChannelOpenError`, aborting the free-machine loop.

`SSHMachineRepository.disconnect` is a safe no-op when the `node_id` is absent
from `_sessions` (`self._sessions.pop(node_id, None)`), so calling
`disconnect(node.node_id)` when `_connect_to_vm` itself failed (no session
registered) is harmless. The success path is unchanged: on a successful
`_setup_vm`, the session stays registered under `node.node_id` for orchestrator
reuse after the DB row's `update(enabled=True)` flips it visible.

#### Scenario: CloudSetupError disconnects before deleting VM

- **WHEN** `_setup_vm` raises `CloudSetupError` after `_connect_to_vm` registered a session in `_sessions[node.node_id]`
- **THEN** the `CloudSetupError` `except` block awaits `machine_repository.disconnect(node.node_id)` BEFORE `await adapter.delete_node(...)`

#### Scenario: Generic exception disconnects before deleting VM

- **WHEN** `_setup_vm` raises a non-`CloudSetupError` `Exception` after `_connect_to_vm` registered a session
- **THEN** the generic `except Exception` block awaits `machine_repository.disconnect(tmp_node_id)` BEFORE `await adapter.delete_node(...)` and re-raising as `CloudSetupError`

#### Scenario: No stale session leaks after failed allocation

- **WHEN** two consecutive `allocate` calls both fail at `_setup_vm`
- **THEN** after each failure `disconnect(tmp_node_id)` is called, `_sessions` contains no stale `FREE` entries for those node_ids, and a subsequent `list_free()` returns an empty list

#### Scenario: Success path does not disconnect

- **WHEN** `_setup_vm` returns a `Node` successfully
- **THEN** `allocate` does NOT call `disconnect(tmp_node_id)`; the session remains registered under `tmp_node_id` for orchestrator reuse after the DB row flips to `enabled=TRUE` via `update`
### Requirement: Cloud-init error message includes stdout

The `CloudSetupError` raised by `_setup_vm` on a non-zero `cloud-init status --wait` exit code SHALL include both `stdout` and `stderr` in its message
(`cloud-init status --wait` writes its status line to stdout, so omitting it
yields no indication of why cloud-init failed). Format: `cloud-init failed on
{ip_addr}: exit={exit_code} stdout={stdout} stderr={stderr}`. The timeout branch
(`asyncio.TimeoutError`) message is unchanged: `cloud-init status --wait timed
out on {ip_addr} after {timeout}s`.

#### Scenario: Cloud-init failure message contains stdout
- **WHEN** `cloud-init status --wait` returns `exit_code=2` with `stdout="status: error\n"` and `stderr=""`
- **THEN** the exception message contains `stdout=status: error` and `stderr=`
