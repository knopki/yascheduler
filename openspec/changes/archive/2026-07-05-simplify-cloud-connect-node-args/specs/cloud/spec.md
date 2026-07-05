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

After `adapter.create_node(...)` returns the VM `ip_addr`, `allocate` SHALL
construct the node identity exactly once as
`Node(node_id=tmp_node_id, ip=ip_addr, ncpus=0, enabled=False,
cloud=adapter.name, username=config.username, port=22)` and thread that single
`Node` object down into `_setup_vm(node, adapter, config)`. `allocate` SHALL
NOT build a second `Node`, and the private helpers SHALL NOT reconstruct one —
the enabled node is derived from this object via `dataclasses.replace`.

On VM creation/setup failure `allocate` SHALL raise `CloudAllocateError` or
`CloudSetupError` (domain exceptions). `deallocate(cloud: str, ip: str)`
deletes the VM via the named provider's SDK (unchanged — `ip` is the cloud SDK
host identifier). `select_provider(platforms, current_counts) -> str | None`
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

#### Scenario: Allocate node on selected provider reuses tmp_node_id

- **WHEN** `allocate("aws", tmp_node_id=NodeId(7))` is called with a provider name that has a registered adapter
- **THEN** a VM is created, set up via a session registered under `NodeId(7)`, and a `Node(node_id=NodeId(7), ip=<vm_ip>, enabled=True, …)` is returned (no DB write inside the adapter; the caller persists via `NodeRepository.update`)

#### Scenario: allocate constructs the node identity once

- **WHEN** `allocate` succeeds
- **THEN** exactly one `Node(...)` is constructed (in `allocate`, right after `create_node`); `_connect_to_vm` passes that object to `machine_repository.connect` without building an ersatz `Node`, and `_setup_vm` returns `dataclasses.replace(node, enabled=True, ncpus=ncpus)` rather than constructing a new `Node`

#### Scenario: connect is called with the node and no username/port args

- **WHEN** `_connect_to_vm(node, adapter, config)` reaches the connect step
- **THEN** it calls `machine_repository.connect(node=node, client_keys=..., connect_timeout=..., data_dir=..., engines_dir=..., tasks_dir=..., jump_host=..., jump_username=...)` with no `username` and no `port` argument (both come from `node.username` / `node.port`)

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
- **THEN** the generic `except Exception` block awaits `machine_repository.disconnect(node.node_id)` BEFORE `await adapter.delete_node(...)` and re-raising as `CloudSetupError`

#### Scenario: No stale session leaks after failed allocation

- **WHEN** two consecutive `allocate` calls both fail at `_setup_vm`
- **THEN** after each failure `disconnect(node.node_id)` is called, `_sessions` contains no stale `FREE` entries for those node_ids, and a subsequent `list_free()` returns an empty list

#### Scenario: Success path does not disconnect

- **WHEN** `_setup_vm` returns a `Node` successfully
- **THEN** `allocate` does NOT call `disconnect(node.node_id)`; the session remains registered under `node.node_id` for orchestrator reuse after the DB row flips to `enabled=TRUE` via `update`
