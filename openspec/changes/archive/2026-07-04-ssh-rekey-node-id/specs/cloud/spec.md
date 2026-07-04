## MODIFIED Requirements

### Requirement: CloudProvisionerImpl implements CloudProvisioner

`CloudProvisionerImpl` (`infra/cloud/manager.py`) SHALL satisfy the
`CloudProvisioner` Protocol (`allocate` async, `deallocate` async,
`select_provider` sync). It SHALL be a pure cloud-API adapter — it SHALL NOT
access the database, SHALL NOT hold a `NodeRepository`, and SHALL NOT open any
Unit of Work. Node persistence is owned by use cases.

`allocate(provider: str, tmp_node_id: NodeId) -> Node` returns a `Node`
(post-persistence identity — the row already exists with `node_id ==
tmp_node_id`; the caller enabled it via `NodeRepository.update`). This reuses
the tmp-node row inserted by `_select_and_insert_tmp` as the real node's
identity: the cloud setup SSH session registers under `tmp_node_id`, and the
caller's persist step is a single `update(node)` (flipping `enabled` to TRUE,
setting `ip`/`ncpus`) rather than `insert(NewNode) + remove(tmp_node_id)`.

On VM creation/setup failure `allocate` SHALL raise `CloudAllocateError` or
`CloudSetupError` (domain exceptions). `deallocate(cloud: str, ip: str)`
deletes the VM via the named provider's SDK (unchanged — `ip` is the cloud SDK
host identifier). `select_provider(platforms, current_counts) -> str | None`
delegates to the pure `select_provider_pure(adapters, configs, platforms,
current_counts, log)` and returns the selected adapter's name (or `None` on no
capacity OR when the selected provider's op semaphore is locked — throttle).

`_setup_vm(ip_addr, tmp_node_id, adapter, config)` SHALL call
`_connect_to_vm(ip_addr, tmp_node_id, adapter, config)` which calls
`machine_repository.connect(node=Node(node_id=tmp_node_id, ip=ip_addr, …),
…)`, registering the session under `tmp_node_id`. After cloud-init, engine
setup, and CPU detection, `_setup_vm` SHALL return
`Node(node_id=tmp_node_id, ip=ip_addr, enabled=True, ncpus, cloud=adapter.name,
username=config.username, port=22)` (a `Node`, not a `NewNode`).

The `configs: dict[str, ConfigCloud]` field SHALL be typed against the
`ConfigCloud` Union. `_connect_to_vm` SHALL access `config.jump_host` /
`config.jump_username` via direct attribute access.

#### Scenario: Allocate node on selected provider reuses tmp_node_id

- **WHEN** `allocate("aws", tmp_node_id=NodeId(7))` is called with a provider name that has a registered adapter
- **THEN** a VM is created, set up via a session registered under `NodeId(7)`, and a `Node(node_id=NodeId(7), ip=<vm_ip>, enabled=True, …)` is returned (no DB write inside the adapter; the caller persists via `NodeRepository.update`)

#### Scenario: Allocate raises on VM creation failure

- **WHEN** `allocate(provider, tmp_node_id)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` is raised; the caller catches and cleans up the tmp-node by `remove(tmp_node_id)`

#### Scenario: No DB access from adapter

- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

#### Scenario: Provider op-limit returns None

- **WHEN** the highest-priority provider with capacity has its op semaphore locked
- **THEN** `select_provider` returns `None` (does not raise); the caller's `selection is None` branch handles cleanup

### Requirement: Setup-failure disconnects machine_repository session

`CloudProvisionerImpl.allocate` SHALL disconnect the `machine_repository`
session for the failed `tmp_node_id` before deleting the VM on the
setup-failure path. Both `except` blocks following `_setup_vm` (the
`CloudSetupError` handler and the generic `Exception` handler) SHALL
`await self.machine_repository.disconnect(tmp_node_id)` BEFORE
`await adapter.delete_node(...)`. Without this, a failed allocation would
leak a stale `FREE` session in `_sessions[tmp_node_id]` pointing at a deleted
VM — the allocator would then pick that session, attempt operations on it, and
raise `asyncssh.misc.ChannelOpenError`, aborting the free-machine loop.

`SSHMachineRepository.disconnect` is a safe no-op when the `node_id` is absent
from `_sessions` (`self._sessions.pop(node_id, None)`), so calling
`disconnect(tmp_node_id)` when `_connect_to_vm` itself failed (no session
registered) is harmless. The success path is unchanged: on a successful
`_setup_vm`, the session stays registered under `tmp_node_id` for orchestrator
reuse after the DB row's `update(enabled=True)` flips it visible.

#### Scenario: CloudSetupError disconnects before deleting VM

- **WHEN** `_setup_vm` raises `CloudSetupError` after `_connect_to_vm` registered a session in `_sessions[tmp_node_id]`
- **THEN** the `CloudSetupError` `except` block awaits `machine_repository.disconnect(tmp_node_id)` BEFORE `await adapter.delete_node(...)`

#### Scenario: Generic exception disconnects before deleting VM

- **WHEN** `_setup_vm` raises a non-`CloudSetupError` `Exception` after `_connect_to_vm` registered a session
- **THEN** the generic `except Exception` block awaits `machine_repository.disconnect(tmp_node_id)` BEFORE `await adapter.delete_node(...)` and re-raising as `CloudSetupError`

#### Scenario: No stale session leaks after failed allocation

- **WHEN** two consecutive `allocate` calls both fail at `_setup_vm`
- **THEN** after each failure `disconnect(tmp_node_id)` is called, `_sessions` contains no stale `FREE` entries for those node_ids, and a subsequent `list_free()` returns an empty list

#### Scenario: Success path does not disconnect

- **WHEN** `_setup_vm` returns a `Node` successfully
- **THEN** `allocate` does NOT call `disconnect(tmp_node_id)`; the session remains registered under `tmp_node_id` for orchestrator reuse after the DB row flips to `enabled=TRUE` via `update`

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