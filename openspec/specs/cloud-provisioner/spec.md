# Cloud Provisioner

## Purpose

CloudProvisionerImpl class that manages cloud provider selection, VM provisioning (allocate/deallocate/capacity), cloud-init rendering, SSH key management, node setup after provisioning, and concurrent allocation throttling.

## Requirements

### Requirement: CloudProvisionerImpl implements CloudProvisioner

The system SHALL provide a `CloudProvisionerImpl` class that satisfies the
`CloudProvisioner` Protocol with methods: `allocate` (async),
`deallocate` (async), `select_provider` (sync). The class SHALL be a pure
cloud-API adapter — it SHALL NOT access the database, SHALL NOT hold a
`NodeRepository`, and SHALL NOT open any Unit of Work. Node persistence
(add, add_tmp, disable, remove, list_all reads) is owned by use cases.

The class SHALL NOT expose `capacity()`, `allocate_with_tracking`,
`get_capacity`, `mark_task_done`, `on_tasks`, or `apis` — these are removed
(moved to use cases, `AllocationTracker`, or deleted as dead code).

The `configs: dict[str, ConfigCloud]` field SHALL be typed against the relocated
`ConfigCloud` Union (imported from `yascheduler.infra.cloud` or intra-package
`from .cloud_configs import ConfigCloud`), not from `yascheduler.config`. The
`_connect_to_vm` method SHALL access `config.jump_host` and
`config.jump_username` as direct attribute access (all four DTOs declare these
fields), replacing the prior `getattr(config, "jump_host", None) or None` defensive
fallbacks with `config.jump_host or None` / `config.jump_username or None`.

#### Scenario: Allocate node on best provider
- **WHEN** allocate(["linux"]) is called and two providers support Linux
- **THEN** a VM is created on the provider with highest priority and available capacity

#### Scenario: Allocate returns Node
- **WHEN** a VM is successfully provisioned and set up
- **THEN** returns a Node domain object with ip, ncpus, cloud, enabled=True — the caller is responsible for persisting the Node

#### Scenario: Deallocate removes VM and DB record
- **WHEN** deallocate("10.0.0.1") is called for a cloud node
- **THEN** the VM is deleted via provider SDK and the node is removed from DB

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
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or `db.py` import is touched

#### Scenario: configs dict typed against relocated ConfigCloud union
- **WHEN** `CloudProvisionerImpl.configs` is introspected for its type annotation
- **THEN** it is `dict[str, ConfigCloud]` where `ConfigCloud` is imported from
  `yascheduler.infra.cloud` (or intra-package `.cloud_configs`), not from
  `yascheduler.config`

#### Scenario: _connect_to_vm uses direct attribute access for jump fields
- **WHEN** `CloudProvisionerImpl._connect_to_vm` is inspected for how it reads
  `jump_host` / `jump_username` from the config DTO
- **THEN** it uses `config.jump_host or None` / `config.jump_username or None` (direct
  attribute access), not `getattr(config, "jump_host", None) or None` (the defensive
  fallback is removed because all four DTOs declare the fields)

### Requirement: Provider selection by priority and capacity

The system SHALL select the best available cloud provider based on
configurable priority and current capacity. Provider selection SHALL be
exposed via the sync port method `select_provider(platforms,
current_counts) -> str | None` on `CloudProvisioner`. The implementation
SHALL call the adapter-internal pure function `select_provider_pure(adapters,
configs, platforms, current_counts, log)` and return the selected
adapter's `name` as a bare `str` (or `None`). The application layer SHALL
NOT call `select_provider_pure` directly or reference
`CloudAdapter`/`ConfigCloud` types.

If the selected provider's op semaphore is locked (concurrent op limit
reached), the port method SHALL return `None` (not raise). This matches
current caller-visible semantics where `allocate_with_tracking` returned
`None` on throttle.

The returned `str` is the selected provider's identity, passed back
unchanged by the caller to `allocate(provider)` and `deallocate(cloud, ip)`.
No `ProviderSelection` value object is constructed or returned.

#### Scenario: Higher priority wins
- **WHEN** provider A has priority=100 and provider B has priority=50, both with capacity
- **THEN** `select_provider(platforms, counts)` returns the string `provider_a.name`

#### Scenario: Full provider skipped
- **WHEN** a provider has reached max_nodes (current_counts[name] >= configs[name].max_nodes)
- **THEN** it is excluded from selection

#### Scenario: No platform support
- **WHEN** no provider supports any of the requested platforms
- **THEN** `select_provider` returns `None`

#### Scenario: Provider op-limit returns None
- **WHEN** the highest-priority provider with capacity has its op semaphore locked
- **THEN** `select_provider` returns `None` (does not raise); the caller's `selection is None` branch handles cleanup

### Requirement: Node setup after provisioning

The system SHALL run cloud-init status check and engine setup after a VM is
created, before returning the Node. All setup logic SHALL be contained within
`infra/cloud/` — no imports from `clouds/` or `remote_machine/`.

#### Scenario: Cloud-init must complete
- **WHEN** a VM is created
- **THEN** cloud-init status --wait is executed before setup

#### Scenario: Engine packages installed
- **WHEN** node setup runs on a fresh VM
- **THEN** required packages for configured engines are installed

#### Scenario: No CloudAPI dependency
- **WHEN** CloudProvisionerImpl creates a node
- **THEN** no code from `clouds/cloud_api.py` is invoked

### Requirement: Concurrent allocation throttling

The system SHALL prevent duplicate allocation requests for the same task
while a provisioning operation is in-flight. Throttling SHALL be owned by
the application layer: `AllocationTracker` deduplicates by task_id, and
the `CloudProvisioner.select_provider` port method returns `None` when
the selected provider's op semaphore is locked (concurrent op limit
reached).

#### Scenario: Duplicate request ignored
- **WHEN** `allocate_task` is called for task_id=42 while task 42 is already tracked by `AllocationTracker`
- **THEN** the second call returns immediately without creating a second VM

#### Scenario: Provider op-limit returns None
- **WHEN** the selected provider's op semaphore is locked (concurrent op limit reached)
- **THEN** `select_provider` returns `None` and the use case's `selection is None` branch calls `tracker.discard(task_id)` and returns False

### Requirement: CloudProvisionerImpl owns cloud-init rendering and SSH key management

The system SHALL provide cloud-init configuration rendering and SSH key
management within `infra/cloud/`, without depending on `clouds/cloud_api.py`.
SSH key generation, loading, and name extraction SHALL live in
`infra/cloud/ssh_keys.py`.

The cloud-init user-data renderer SHALL be a single concrete frozen dataclass
`CloudInitConfig` in `infra/cloud/cloud_init.py` (renamed from
`infra/cloud/cloud_config.py` `class CloudConfig` in the
`cloud-init-rename-and-prune` change). There SHALL be no `PCloudConfig`
Protocol in `infra/cloud/protocols.py`: the single-implementer Protocol was
collapsed into its sole concrete class because it had zero runtime dispatch
(`@runtime_checkable` was never applied; zero `isinstance` calls) and a
self-referential seam (`CreateNodeCallable.__call__` referenced it; providers
referenced it because `CreateNodeCallable` did). Provider `*_create_node`
callables and `CreateNodeCallable.__call__` SHALL type their `cloud_config`
parameter as `Optional[CloudInitConfig]` (the concrete class), not
`Optional[PCloudConfig]` (the deleted Protocol).

The `az_create_node` public entry point SHALL NOT carry a runtime `isinstance`
boundary guard narrowing `cloud_config` to the concrete class. The guard
introduced by `resolve-type-bridge-debt` D3a (bridging a public
`PCloudConfig | None` param to an internal `CloudConfig | None` param) is
removed in the `cloud-init-rename-and-prune` change: with both sides retyped
to the same concrete class, the guard's premise (a foreign `PCloudConfig`
impl reaching `az_create_node`) is structurally impossible, and the guard
would be dead code asserting a property the type system already guarantees.

#### Scenario: Cloud-init rendered without CloudAPI
- **WHEN** `CloudInitConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the cloud-config YAML is produced from `infra/cloud/cloud_init.py`
  (the renderer file was renamed from `infra/cloud/cloud_config.py` in the
  `cloud-init-rename-and-prune` change to disambiguate from the
  `ConfigCloud*` provider-config DTOs in `infra/cloud/cloud_configs.py`)

#### Scenario: SSH key generated for cloud provisioning
- **WHEN** a cloud provider needs an SSH key
- **THEN** the key is generated or loaded via `infra/cloud/ssh_keys.py`

#### Scenario: Cloud-init renderer is a single concrete class
- **WHEN** the `yascheduler/infra/cloud/` directory is inspected for
  `cloud_init.py` and `cloud_config.py`
- **THEN** `cloud_init.py` exists and contains `class CloudInitConfig` (a
  `@dataclass(frozen=True)` with no Protocol base class); `cloud_config.py`
  does NOT exist; `protocols.py` does NOT define `PCloudConfig`

#### Scenario: Provider create_node callables type cloud_config as CloudInitConfig
- **WHEN** each of `az_create_node`, `hetzner_create_node`,
  `upcloud_create_node`, `vastai_create_node` is inspected for its
  `cloud_config` parameter type annotation
- **THEN** the annotation is `CloudInitConfig | None` (or
  `Optional[CloudInitConfig]`), imported from `yascheduler.infra.cloud` or
  `yascheduler.infra.cloud.cloud_init`; no reference to `PCloudConfig` appears
  in any provider file

#### Scenario: CreateNodeCallable types cloud_config as CloudInitConfig
- **WHEN** `CreateNodeCallable.__call__` in `infra/cloud/protocols.py` is
  inspected for its `cloud_config` parameter type annotation
- **THEN** the annotation is `Optional[CloudInitConfig]` (or
  `CloudInitConfig | None`); the `PCloudConfig` Protocol class is absent from
  `protocols.py`

#### Scenario: az_create_node has no isinstance boundary guard
- **WHEN** `yascheduler/infra/cloud/providers/az.py` is inspected for
  `isinstance(cloud_config, CloudInitConfig)` or
  `isinstance(cloud_config, CloudConfig)`
- **THEN** zero matches are found in the `az_create_node` function body (the
  D3a boundary guard is removed; both sides of the call chain are the same
  concrete class, making the guard structurally unreachable)

#### Scenario: No PCloudConfig references remain in source
- **WHEN** the `yascheduler/` source tree is searched for `PCloudConfig\b`
- **THEN** zero matches are found (the Protocol is deleted; all references
  retyped to `CloudInitConfig`)

#### Scenario: CloudCapacity dataclass removed
- **WHEN** the `yascheduler/` source tree is searched for `class CloudCapacity`
  and `CloudCapacity(` (construction sites)
- **THEN** zero matches are found in source (the `CloudCapacity` dataclass in
  `infra/cloud/protocols.py` is deleted; its last consumer was removed in
  the archived `cloud-provisioner-pure` change which rewrote
  `_clouds_get_capacity` to return `int`; the unrelated
  `CloudCapacityExhaustedError` domain exception in `domain/exceptions.py` is
  NOT a `CloudCapacity` consumer and is unaffected)

### Requirement: CloudProvisionerImpl.stop closes machine_gateway connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_gateway` by awaiting `machine_gateway.disconnect_all()`. This
replaces the prior no-op "compatibility hook" semantics.

Rationale: `_setup_vm` opens SSH connections via `machine_gateway.connect(ip)`
during cloud allocation, and `CloudProvisionerImpl.allocate` does not
disconnect them on success. Without `stop()` draining the gateway, those
connections leak for the process lifetime. When `make_daemon` shares a single
gateway between `CloudProvisionerImpl` and `Orchestrator` (per the
`dependency-injection` capability), `clouds.stop()` becomes the primary
shutdown drain; the orchestrator's subsequent `gateway.disconnect_all()` call
is an idempotent no-op on the same instance.

`disconnect_all` on `SSHMachineGateway` is idempotent (it iterates a snapshot
of `_machines` and pops each entry), so calling it from both `clouds.stop()`
and `Orchestrator.stop()` is safe regardless of whether the gateway is shared.

#### Scenario: stop drains all connections

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose
  `machine_gateway` holds one or more connected machines
- **THEN** `machine_gateway.disconnect_all()` SHALL be awaited exactly once,
  and every connection that was present at call time SHALL be closed

#### Scenario: stop with empty gateway is a safe no-op

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose
  `machine_gateway` holds zero connected machines
- **THEN** `machine_gateway.disconnect_all()` SHALL still be awaited (it
  returns without effect), and `stop()` SHALL NOT raise

#### Scenario: stop is idempotent under repeated calls

- **WHEN** `await clouds.stop()` is called twice in succession on the same
  `CloudProvisionerImpl`
- **THEN** both calls SHALL complete without raising, and the second call
  SHALL be a no-op (the gateway's `_machines` registry is already empty)

#### Scenario: stop with shared gateway does not interfere with orchestrator shutdown

- **WHEN** `clouds` and `Orchestrator` share the same `SSHMachineGateway`
  instance (per the `dependency-injection` capability), and
  `Orchestrator.stop()` awaits `clouds.stop()` followed by
  `gateway.disconnect_all()`
- **THEN** both calls SHALL complete without raising; the second
  `disconnect_all()` SHALL be an idempotent no-op on the now-empty registry
