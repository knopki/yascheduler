# Cloud Provisioner

## Purpose

CloudProvisionerImpl class that manages cloud provider selection, VM provisioning (allocate/deallocate/capacity), cloud-init rendering, SSH key management, node setup after provisioning, and concurrent allocation throttling.

## Requirements

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
`infra/cloud/`.

#### Scenario: Cloud-init must complete
- **WHEN** a VM is created
- **THEN** cloud-init status --wait is executed before setup

#### Scenario: Engine packages installed
- **WHEN** node setup runs on a fresh VM
- **THEN** required packages for configured engines are installed

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

### Requirement: Setup-failure disconnects machine_repository session

`CloudProvisionerImpl.allocate` SHALL disconnect the `machine_repository`
session for the failed IP before deleting the VM on the setup-failure
path. Both `except` blocks that follow the `_setup_vm` call (the
`CloudSetupError` handler and the generic `Exception` handler) SHALL
`await self.machine_repository.disconnect(ip_addr)` before
`await adapter.delete_node(...)`.

This complements the existing `CloudProvisionerImpl.stop closes
machine_repository connections` requirement: `stop()` remains the
shutdown drain, but a failed allocation mid-run would otherwise leak a
stale `FREE` session in `_sessions[ip]` pointing at a deleted VM's IP. The
allocator would then pick that session via `list_free()`, attempt
`get_cpu_cores` or `start_task_on_machine` on it, and raise
`asyncssh.misc.ChannelOpenError` — aborting the free-machine loop and
preventing any new node from being provisioned.

`SSHMachineRepository.disconnect` is a safe no-op when the IP is absent
from `_sessions` (it does `self._sessions.pop(ip, None)` and returns if
`None`), so calling `disconnect(ip_addr)` when `_connect_to_vm` itself
failed (and never registered a session) is harmless.

The success path is unchanged: on a successful `_setup_vm`, the session
stays registered so the orchestrator can reuse the connection on the next
tick (after `_persist_node_with_cleanup` flips the DB row to
`enabled=TRUE`). This is the designed behavior — only the failure path
gains a disconnect.

#### Scenario: CloudSetupError disconnects before deleting VM

- **WHEN** `_setup_vm` raises `CloudSetupError` (e.g. cloud-init failed, setup_node failed, or get_cpu_cores failed) after `_connect_to_vm` registered a session in `_sessions[ip]`
- **THEN** the `CloudSetupError` `except` block in `allocate` awaits `machine_repository.disconnect(ip_addr)` (removing the session from `_sessions` and closing the SSH connection) BEFORE awaiting `adapter.delete_node(...)` to delete the cloud VM

#### Scenario: Generic exception disconnects before deleting VM

- **WHEN** `_setup_vm` raises a non-`CloudSetupError` `Exception` after `_connect_to_vm` registered a session in `_sessions[ip]`
- **THEN** the generic `except Exception` block in `allocate` awaits `machine_repository.disconnect(ip_addr)` BEFORE awaiting `adapter.delete_node(...)` and re-raising as `CloudSetupError`

#### Scenario: No stale session leaks after failed allocation

- **WHEN** two consecutive `allocate` calls both fail at the `_setup_vm` stage
- **THEN** after each failure `machine_repository.disconnect(ip)` is called for the failed IP, `MachineRepository._sessions` contains no stale `FREE` entries for those IPs, and a subsequent `list_free()` call returns an empty list (assuming no other connected nodes)

#### Scenario: Disconnect on never-connected IP is a safe no-op

- **WHEN** `_connect_to_vm` itself fails (SSH connect error before `machine_repository.connect` registered a session) and `allocate`'s `except` block calls `machine_repository.disconnect(ip_addr)` for an IP not in `_sessions`
- **THEN** `SSHMachineRepository.disconnect` does `self._sessions.pop(ip, None)`, gets `None`, and returns without raising; `adapter.delete_node` still runs and the cloud VM is deleted

#### Scenario: Success path does not disconnect

- **WHEN** `_setup_vm` returns a `Node` successfully
- **THEN** `allocate` does NOT call `machine_repository.disconnect(ip_addr)`; the session remains registered in `_sessions` for the orchestrator to reuse on the next tick after the DB row is flipped to `enabled=TRUE`

### Requirement: Cloud-init error message includes stdout

The `CloudSetupError` raised by `_setup_vm` on a non-zero `cloud-init status --wait` exit code SHALL include both `stdout` and `stderr` in its message.

`cloud-init status --wait` writes its status line to stdout,
so omitting `stdout` (the previous behavior) yields `stderr=` (typically
empty) with no indication of why cloud-init failed.

The error message format SHALL be:
`cloud-init failed on {ip_addr}: exit={exit_code} stdout={stdout}
stderr={stderr}`.

#### Scenario: Cloud-init failure message contains stdout

- **WHEN** `cloud-init status --wait` returns `exit_code=2` with `stdout="status: error\n"` and `stderr=""` and `_setup_vm` raises `CloudSetupError`
- **THEN** the exception message contains `stdout=status: error` and `stderr=` so the operator can read the cloud-init status line from the daemon log

#### Scenario: Cloud-init timeout message is unchanged

- **WHEN** `cloud-init status --wait` times out (`asyncio.TimeoutError`)
- **THEN** the raised `CloudSetupError` message is `cloud-init status --wait timed out on {ip_addr} after {timeout}s` (the timeout branch does not read `result.stdout`/`result.stderr` and is unchanged)

### Requirement: Cloud-init package_upgrade sourced from per-cloud config

`CloudProvisionerImpl._get_cloud_config_data` SHALL build the `CloudInitConfig`
passed to provider `create_node` callables with its `package_upgrade` flag
sourced from the per-cloud config DTO's `package_upgrade` field
(`config.package_upgrade`, default `True`), NOT from
`self.local_config.cloud_package_upgrade` (which no longer exists) and NOT
hardcoded to `True`.

The method signature SHALL be
`_get_cloud_config_data(self, adapter: CloudAdapter, config: ConfigCloud)`,
where `config` is the per-cloud DTO resolved by the caller. The `config`
parameter SHALL be typed `ConfigCloud` (the infra Union of the four
`ConfigCloud*` DTOs), NOT the domain `CloudConfig` Protocol — because
`package_upgrade` is declared on the concrete DTOs only (not on the Protocol),
typing against the Protocol would not resolve `config.package_upgrade`
statically.

The sole caller, `CloudProvisionerImpl.allocate`, SHALL pass the per-cloud
config it already resolves (`config = self.configs.get(provider)`) as the
`config` argument.

This lets operators (and tests) skip the slow cloud-init `apt-get upgrade` on
freshly-provisioned VMs on a per-provider basis. The `packages` list SHALL
continue to be derived from the platform-matched engines' `platform_packages`
(unchanged). Only the `package_upgrade` flag's sourcing changes.

#### Scenario: package_upgrade reflects config.package_upgrade
- **WHEN** `CloudProvisionerImpl._get_cloud_config_data(adapter, config)` builds the `CloudInitConfig` and `config.package_upgrade is True`
- **THEN** the resulting `CloudInitConfig.package_upgrade is True`
- **WHEN** the same is called with a `config` whose `package_upgrade is False`
- **THEN** the resulting `CloudInitConfig.package_upgrade is False`

#### Scenario: _get_cloud_config_data receives the resolved per-cloud config
- **WHEN** `CloudProvisionerImpl.allocate("hetzner")` is inspected for how it builds the cloud config passed to `adapter.create_node`
- **THEN** it resolves `config = self.configs.get("hetzner")` and passes that same `config` as the `config` argument to `_get_cloud_config_data(adapter, config)`

#### Scenario: config parameter typed as the infra ConfigCloud union
- **WHEN** `_get_cloud_config_data` is introspected for its `config` parameter type annotation
- **THEN** the annotation is `ConfigCloud` (imported from `yascheduler.infra.cloud` or intra-package `.cloud_configs`), NOT the domain `CloudConfig` Protocol

#### Scenario: Default behavior is unchanged
- **WHEN** a daemon is constructed from a `Config` whose active `ConfigCloud*` DTOs were parsed from a `[clouds]` section that does not set any `{prefix}_package_upgrade` key
- **THEN** each such DTO has `package_upgrade is True` (the field default), preserving the pre-change cloud-init behavior
