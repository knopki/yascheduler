## MODIFIED Requirements

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
