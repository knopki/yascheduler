## MODIFIED Requirements

### Requirement: CloudProvisionerImpl implements CloudProvisioner

`CloudProvisionerImpl` SHALL satisfy the `CloudProvisioner` Protocol (`allocate`
async, `deallocate` async, `select_provider` sync). It SHALL be a pure cloud-API
adapter — it SHALL NOT access the database, SHALL NOT hold a `NodeRepository`,
and SHALL NOT open any Unit of Work. Node persistence is owned by use cases.

`allocate(provider: str, node: Node) -> Node` receives the tmp-node `Node`
(post-persistence identity — the row already exists with the tmp `node_id`).
This reuses the tmp-node row as the real node's identity: the cloud setup SSH
session registers under `node.node_id`, and the caller's persist step is a
single `update(node)` rather than `insert(NewNode) + remove(tmp_node_id)`.

After the VM is created, `allocate` SHALL derive the node identity exactly once
(flipping `hostname`, `cloud`, `username` on the passed Node) and thread that
single `Node` object down. `allocate` SHALL NOT construct a fresh `Node`, and
the private helpers SHALL NOT reconstruct one. `port` is carried through
unchanged (the tmp node's `port` default is preserved).

`allocate` SHALL stamp the jump-leg identity on the node exactly once, in the
same `replace(node, enabled=True, ncpus=..., ...)` call that flips `enabled`
and writes `ncpus`. The jump values SHALL be resolved from the matching
`CloudConfig` (`prefix == node.cloud`) if it sets BOTH `jump_host` and
`jump_username`; otherwise from `config.remote.jump_host` /
`config.remote.jump_username` (fallback). `jump_port` SHALL be `22` (the
schema default — `CloudConfig` does not carry a `jump_port` field in this
change). This stamping SHALL happen BEFORE the node is persisted as enabled,
so the orchestrator's connect-machine loop (which only yields `enabled=True`
nodes) always sees a fully-stamped row.

`_setup_vm` SHALL call `machine_repository.connect(node=node,
client_keys=keys, connect_timeout=..., data_dir=..., engines_dir=...,
tasks_dir=...)` with NO `jump_host` / `jump_username` arguments — the
repository reads them from the node (whose jump fields were stamped at
creation, BEFORE the connect-setup SSH session is opened).

On VM creation/setup failure `allocate` SHALL raise `CloudAllocateError` or
`CloudSetupError` (domain exceptions). `deallocate(node: Node)` deletes the VM
via the provider named by `node.cloud`, using `node.hostname` as the cloud SDK
host identifier. When `node.cloud` is `None`, `deallocate` SHALL log a warning
and return without deleting. When the named provider has no registered adapter
or config, `deallocate` SHALL log a warning and return.
`select_provider(platforms, current_counts) -> str | None` delegates to a pure
selection function and returns the selected adapter's name (or `None` on no
capacity OR when the selected provider's op semaphore is locked — throttle).

`allocate` connects the node via the machine repository and registers the
session under `node.node_id`. After cloud-init, engine setup, and CPU detection,
the node identity is returned with `enabled` flipped, `ncpus` populated, and
`jump_host` / `jump_username` stamped (the same identity, NOT a freshly
constructed `Node` and NOT a `NewNode`).

#### Scenario: Allocate raises on VM creation failure

- **WHEN** `allocate(provider, node)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` is raised; the caller catches and cleans up the tmp-node by `remove(node.node_id)`

#### Scenario: No DB access from adapter

- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

#### Scenario: setup_vm stamps jump on Node before persisting enabled=True

- **WHEN** `allocate` runs `_setup_vm` for a node with `cloud="hetzner"` and the `hetzner` `CloudConfig` has `jump_host="jump.example.com"` and `jump_username="jumper"`
- **THEN** the `replace(node, enabled=True, ...)` call produces a `Node` with `jump_host="jump.example.com"` and `jump_username="jumper"`, and the subsequent `repository.connect(node=node, ...)` call passes no `jump_host` / `jump_username` arguments

#### Scenario: setup_vm falls back to remote defaults when CloudConfig lacks jump

- **WHEN** `allocate` runs `_setup_vm` for a node whose matching `CloudConfig` does NOT set both `jump_host` and `jump_username`, and `config.remote.jump_host` is set
- **THEN** the `replace(node, enabled=True, ...)` call produces a `Node` whose `jump_host` / `jump_username` come from `config.remote.*`

#### Scenario: setup_vm connect call has no jump kwargs

- **WHEN** `_setup_vm` opens the setup SSH session via `machine_repository.connect`
- **THEN** the call is `connect(node=node, client_keys=keys, connect_timeout=adapter.create_node_conn_timeout, data_dir=..., engines_dir=..., tasks_dir=...)` — no `jump_host` / `jump_username` keyword arguments
