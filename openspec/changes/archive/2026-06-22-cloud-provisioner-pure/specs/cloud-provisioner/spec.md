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

#### Scenario: Allocate node on selected provider
- **WHEN** `allocate("aws")` is called with a provider name that has a registered adapter
- **THEN** a VM is created via the named provider's SDK, set up, and a Node is returned (no DB write occurs inside the adapter)

#### Scenario: Allocate returns Node
- **WHEN** a VM is successfully provisioned and set up
- **THEN** returns a Node domain object with ip, ncpus, cloud, enabled=True — the caller is responsible for persisting the Node

#### Scenario: Allocate raises on VM creation failure
- **WHEN** `allocate(provider)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` (from `domain.exceptions`) is raised; the caller catches and cleans up tmp-node

#### Scenario: Deallocate deletes VM only
- **WHEN** `deallocate(cloud="aws", ip="10.0.0.1")` is called for a cloud node
- **THEN** the VM is deleted via provider SDK; the caller is responsible for DB disable and remove

#### Scenario: No DB access from adapter
- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or `db.py` import is touched

### Requirement: Provider selection by priority and capacity

The system SHALL select the best available cloud provider based on
configurable priority and current capacity. Provider selection SHALL be
exposed via the sync port method `select_provider(platforms,
current_counts) -> ProviderSelection | None` on `CloudProvisioner`. The
implementation SHALL call the adapter-internal pure function
`select_provider_pure(adapters, configs, platforms, current_counts, log)`
and wrap the result into a `ProviderSelection(name, username)` domain
value object. The application layer SHALL NOT call `select_provider_pure`
directly or reference `CloudAdapter`/`ConfigCloud` types.

If the selected provider's op semaphore is locked (concurrent op limit
reached), the port method SHALL return `None` (not raise). This matches
current caller-visible semantics where `allocate_with_tracking` returned
`None` on throttle.

#### Scenario: Higher priority wins
- **WHEN** provider A has priority=100 and provider B has priority=50, both with capacity
- **THEN** `select_provider(platforms, counts)` returns a `ProviderSelection` with `name=provider_a.name`

#### Scenario: Full provider skipped
- **WHEN** a provider has reached max_nodes (current_counts[name] >= configs[name].max_nodes)
- **THEN** it is excluded from selection

#### Scenario: No platform support
- **WHEN** no provider supports any of the requested platforms
- **THEN** `select_provider` returns `None`

#### Scenario: Provider op-limit returns None
- **WHEN** the highest-priority provider with capacity has its op semaphore locked
- **THEN** `select_provider` returns `None` (does not raise); the caller's `selection is None` branch handles cleanup

#### Scenario: ProviderSelection is primitive-only
- **WHEN** `select_provider` returns a `ProviderSelection`
- **THEN** it has `name: str` and `username: str` only — no `CloudAdapter` or `ConfigCloud` reference

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

## REMOVED Requirements

### Requirement: Capacity reports available nodes

**Reason**: `capacity()` is removed from `CloudProvisionerImpl` and the
`CloudProvisioner` Protocol. Capacity counting (read + arithmetic) is now
owned by the orchestrator's `_clouds_get_capacity` inline UoW read.

**Migration**: Callers that previously called `clouds.capacity()` or
`clouds.get_capacity()` SHALL use the orchestrator's inline
`_clouds_get_capacity` method, which reads `uow.nodes.list_all()` and
computes `max(0, sum(max_nodes) - sum(current_counts))` over the
filtered `_active_clouds` list.
