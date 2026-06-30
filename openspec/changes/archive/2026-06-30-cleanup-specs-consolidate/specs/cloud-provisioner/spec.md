## REMOVED Requirements

### Requirement: CloudProvisionerImpl.stop closes machine_gateway connections

## MODIFIED Requirements

### Requirement: CloudProvisionerImpl implements CloudProvisioner

The system SHALL provide a `CloudProvisionerImpl` class that satisfies the
`CloudProvisioner` Protocol with methods: `allocate` (async), `deallocate`
(async), `select_provider` (sync). The class SHALL be a pure cloud-API adapter —
it SHALL NOT access the database, SHALL NOT hold a `NodeRepository`, and SHALL NOT
open any Unit of Work. Node persistence (add, add_tmp, disable, remove, list_all
reads) is owned by use cases.

The `configs: dict[str, ConfigCloud]` field SHALL be typed against the
`ConfigCloud` Union (imported from `yascheduler.infra.cloud` or intra-package
`from .cloud_configs import ConfigCloud`). The `_connect_to_vm` method SHALL
access `config.jump_host` and `config.jump_username` via direct attribute access
(`config.jump_host or None` / `config.jump_username or None`); all four DTOs
declare these fields.

#### Scenario: Allocate node on best provider
- **WHEN** allocate(["linux"]) is called and two providers support Linux
- **THEN** a VM is created on the provider with highest priority and available capacity

#### Scenario: Allocate returns Node
- **WHEN** a VM is successfully provisioned and set up
- **THEN** returns a Node domain object with ip, ncpus, cloud, enabled=True — the caller is responsible for persisting the Node

#### Scenario: Allocate node on selected provider
- **WHEN** `allocate("aws")` is called with a provider name that has a registered adapter
- **THEN** a VM is created via the named provider's SDK, set up, and a Node is returned (no DB write occurs inside the adapter)

#### Scenario: Allocate raises on VM creation failure
- **WHEN** `allocate(provider)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` (from `domain.exceptions`) is raised; the caller catches and cleans up tmp-node

#### Scenario: Deallocate deletes VM only
- **WHEN** `deallocate(cloud="aws", ip="10.0.0.1")` is called for a cloud node
- **THEN** the VM is deleted via provider SDK; the caller is responsible for DB disable and remove

#### Scenario: No DB access from adapter
- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

#### Scenario: configs dict typed against the ConfigCloud union
- **WHEN** `CloudProvisionerImpl.configs` is introspected for its type annotation
- **THEN** it is `dict[str, ConfigCloud]` where `ConfigCloud` is imported from `yascheduler.infra.cloud` (or intra-package `.cloud_configs`)

#### Scenario: _connect_to_vm uses direct attribute access for jump fields
- **WHEN** `CloudProvisionerImpl._connect_to_vm` is inspected for how it reads `jump_host` / `jump_username` from the config DTO
- **THEN** it uses `config.jump_host or None` / `config.jump_username or None` (direct attribute access)

### Requirement: Node setup after provisioning

The system SHALL run cloud-init status check and engine setup after a VM is
created, before returning the Node. All setup logic SHALL be contained within
`infra/cloud/`.

#### Scenario: Cloud-init must complete
- **WHEN** a VM is created
- **THEN** cloud-init status --wait is executed before setup

#### Scenario: Engine packages installed
- **WHEN** node setup runs on a fresh VM
- **THEN** required packages for configured engines are installed

### Requirement: CloudProvisionerImpl owns cloud-init rendering and SSH key management

The system SHALL provide cloud-init configuration rendering and SSH key
management within `infra/cloud/`. SSH key generation, loading, and name extraction
SHALL live in `infra/cloud/ssh_keys.py`.

The cloud-init user-data renderer SHALL be a single concrete frozen dataclass
`CloudInitConfig` in `infra/cloud/cloud_init.py`. There SHALL be no `PCloudConfig`
Protocol in `infra/cloud/protocols.py`. Provider `*_create_node` callables and
`CreateNodeCallable.__call__` SHALL type their `cloud_config` parameter as
`CloudInitConfig | None` (the concrete class).

The `az_create_node` public entry point SHALL NOT carry a runtime `isinstance`
boundary guard narrowing `cloud_config` to the concrete class.

#### Scenario: Cloud-init rendered
- **WHEN** `CloudInitConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the cloud-config YAML is produced from `infra/cloud/cloud_init.py`

#### Scenario: SSH key generated for cloud provisioning
- **WHEN** a cloud provider needs an SSH key
- **THEN** the key is generated or loaded via `infra/cloud/ssh_keys.py`

#### Scenario: Cloud-init renderer is a single concrete class
- **WHEN** the `yascheduler/infra/cloud/` directory is inspected for `cloud_init.py` and `cloud_config.py`
- **THEN** `cloud_init.py` exists and contains `class CloudInitConfig` (a `@dataclass(frozen=True)` with no Protocol base class); `cloud_config.py` does NOT exist; `protocols.py` does NOT define `PCloudConfig`

#### Scenario: Provider create_node callables type cloud_config as CloudInitConfig
- **WHEN** each of `az_create_node`, `hetzner_create_node`, `upcloud_create_node`, `vastai_create_node` is inspected for its `cloud_config` parameter type annotation
- **THEN** the annotation is `CloudInitConfig | None` (or `Optional[CloudInitConfig]`), imported from `yascheduler.infra.cloud` or `yascheduler.infra.cloud.cloud_init`

#### Scenario: CreateNodeCallable types cloud_config as CloudInitConfig
- **WHEN** `CreateNodeCallable.__call__` in `infra/cloud/protocols.py` is inspected for its `cloud_config` parameter type annotation
- **THEN** the annotation is `Optional[CloudInitConfig]` (or `CloudInitConfig | None`)

## ADDED Requirements

### Requirement: CloudProvisionerImpl.stop closes machine_repository connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_repository` by awaiting `machine_repository.disconnect_all()`.

`_setup_vm` opens SSH connections via `machine_repository.connect(ip)` during
cloud allocation, and `CloudProvisionerImpl.allocate` does not disconnect them on
success. Without `stop()` draining the repository, those connections leak for the
process lifetime. When `make_daemon` shares a single repository between
`CloudProvisionerImpl` and `Orchestrator` (per the `dependency-injection`
capability), `clouds.stop()` becomes the primary shutdown drain; the
orchestrator's subsequent `repository.disconnect_all()` call is an idempotent
no-op on the same instance.

`disconnect_all` on `SSHMachineRepository` is idempotent (it iterates a snapshot
of `_sessions` and pops each entry), so calling it from both `clouds.stop()` and
`Orchestrator.stop()` is safe regardless of whether the repository is shared.

#### Scenario: stop drains all connections

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose `machine_repository` holds one or more connected sessions
- **THEN** `machine_repository.disconnect_all()` SHALL be awaited exactly once, and every connection that was present at call time SHALL be closed

#### Scenario: stop with empty repository is a safe no-op

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose `machine_repository` holds zero connected sessions
- **THEN** `machine_repository.disconnect_all()` SHALL still be awaited (it returns without effect), and `stop()` SHALL NOT raise

#### Scenario: stop is idempotent under repeated calls

- **WHEN** `await clouds.stop()` is called twice in succession on the same `CloudProvisionerImpl`
- **THEN** both calls SHALL complete without raising, and the second call SHALL be a no-op (the repository's `_sessions` dict is already empty)

#### Scenario: stop with shared repository does not interfere with orchestrator shutdown

- **WHEN** `clouds` and `Orchestrator` share the same `SSHMachineRepository` instance (per the `dependency-injection` capability), and `Orchestrator.stop()` awaits `clouds.stop()` followed by `repository.disconnect_all()`
- **THEN** both calls SHALL complete without raising; the second `disconnect_all()` SHALL be an idempotent no-op on the now-empty `_sessions` dict
