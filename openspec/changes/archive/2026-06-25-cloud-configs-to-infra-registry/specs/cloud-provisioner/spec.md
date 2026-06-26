## MODIFIED Requirements

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