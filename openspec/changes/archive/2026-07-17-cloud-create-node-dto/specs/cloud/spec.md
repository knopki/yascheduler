# Cloud

## ADDED Requirements

### Requirement: CloudCreateNodeDTO as create_node result

The system SHALL define `CloudCreateNodeDTO` as a `@dataclass(frozen=True)` in `yascheduler.infra.cloud.dto`:

- `external_id: str` — the cloud provider's native resource identifier
- `hostname: str` — the SSH-accessible address of the created VM
- `username: str = "root"` — the SSH login user
- `port: int = 22` — the SSH port
- `jump_host: str | None = None` — optional jump / bastion host
- `jump_port: int = 22` — jump host SSH port
- `jump_username: str = "root"` — jump host SSH login user

`CreateNodeCallable` SHALL return `CloudCreateNodeDTO` instead of bare `str`.
`DeleteNodeCallable` SHALL accept `external_id: str` as the resource identifier parameter instead of `host: str`.

Each provider `*_create_node` function SHALL return a `CloudCreateNodeDTO` with:
- `external_id` and `hostname` set to the VM's IP address
- `username` sourced from the provider's config DTO (`cfg.username`)
- `port`, `jump_host`, `jump_port`, `jump_username` sourced from the provider's config DTO (with their respective defaults)

Each provider `*_delete_node` function SHALL accept the `external_id` parameter and use it to locate the resource. Provider-internal logic may still match by IP; the contract is that `external_id` is the authoritative provider identifier.

`CloudCreateNodeDTO` SHALL be importable via the `yascheduler.infra.cloud` subpackage facade.

#### Scenario: create_node returns DTO with IP-based identity

- **WHEN** `az_create_node`, `hetzner_create_node`, `upcloud_create_node`, or `vastai_create_node` succeeds
- **THEN** the return value is a `CloudCreateNodeDTO` whose `external_id` and `hostname` equal the VM's IP address

#### Scenario: create_node DTO carries config-derived connection parameters

- **WHEN** the DTO is constructed by a provider create function
- **THEN** `username` equals `cfg.username`, and the remaining connection fields (`port`, `jump_*`) carry the values from the provider's config DTO or their dataclass defaults

#### Scenario: delete_node identifies resource by external_id

- **WHEN** `adapter.delete_node(cfg=config, external_id=node.external_id)` is called
- **THEN** the provider locates the cloud resource by `external_id` (internal matching may use IP for providers lacking native external IDs)

## MODIFIED Requirements

### Requirement: CloudProvisionerImpl implements CloudProvisioner

`CloudProvisionerImpl` SHALL satisfy the `CloudProvisioner` Protocol (`allocate` async, `deallocate` async, `select_provider` sync). It SHALL NOT access the database, hold a `NodeRepository`, or open a Unit of Work.

`allocate(provider: str, node: Node) -> Node` SHALL receive a tmp-node `Node` (the row already exists) and mutate it — SHALL NOT construct a fresh `Node`.

After VM creation, `allocate` SHALL map the `CloudCreateNodeDTO` fields from `adapter.create_node` onto the Node:
- `hostname` from `dto.hostname`
- `external_id` from `dto.external_id`
- `username` from `dto.username`
- `port` from `dto.port`
- `jump_host`, `jump_port`, `jump_username` from `dto.jump_host`, `dto.jump_port`, `dto.jump_username`

`allocate` SHALL then call `_setup_vm` which performs the SSH connection, cloud-init wait, and engine installation. `_setup_vm` SHALL NOT modify `jump_host`, `jump_port`, or `jump_username` on the Node — the DTO mapping in `allocate` is the sole source for these fields. Each adapter is responsible for sourcing jump fields from its own config DTO and returning them in the `CloudCreateNodeDTO`.

`allocate` SHALL connect the node via `machine_repository.connect(...)` with no `jump_host` / `jump_username` arguments. After cloud-init, engine setup, and CPU detection, the returned `Node` carries `enabled=True`, `ncpus`, and the stamp fields. On VM creation or setup failure, `allocate` SHALL raise `CloudAllocateError` or `CloudSetupError`.

`deallocate(node: Node)` SHALL delete the VM via the provider named by `node.cloud`, using `node.external_id` as the cloud SDK host identifier. When `node.cloud` is `None`, or when the named provider has no registered adapter or config, `deallocate` SHALL log a warning and return without deleting.

`select_provider(platforms, current_counts) -> str | None` delegates to a pure selection function and returns the selected adapter's name (or `None` on no capacity or when the selected provider's op semaphore is locked).

#### Scenario: Allocate raises on VM creation failure

- **WHEN** `allocate(provider, node)` is called and VM creation or setup fails
- **THEN** `CloudAllocateError` or `CloudSetupError` is raised; the caller catches and cleans up the tmp-node by `remove(node.node_id)`

#### Scenario: No DB access from adapter

- **WHEN** any method on `CloudProvisionerImpl` is invoked
- **THEN** no `NodeRepository`, `PostgresUnitOfWork`, or persistence import is touched

#### Scenario: allocate maps DTO fields onto Node

- **WHEN** `allocate` runs and `adapter.create_node` returns a `CloudCreateNodeDTO(external_id="1.2.3.4", hostname="1.2.3.4", username="yascheduler", port=2222)`
- **THEN** the `replace(node, ...)` call produces a `Node` with `hostname="1.2.3.4"`, `external_id="1.2.3.4"`, `username="yascheduler"`, `port=2222`

#### Scenario: _setup_vm preserves DTO-sourced jump values

- **WHEN** the Node after DTO mapping already has `jump_host="dto-jump.example.com"` (not `None`)
- **THEN** `_setup_vm` does NOT overwrite `jump_host`, `jump_port`, or `jump_username` — the DTO-sourced values are preserved

#### Scenario: allocate connects without jump kwargs

- **WHEN** `allocate` opens the setup SSH session via `machine_repository.connect`
- **THEN** the call is `connect(node=node, client_keys=keys, connect_timeout=adapter.create_node_conn_timeout, data_dir=..., engines_dir=..., tasks_dir=...)` — no `jump_host` / `jump_username` keyword arguments

#### Scenario: allocate setup does not write ncpus onto the Node

- **WHEN** `allocate` reaches the final `replace(node, enabled=True, ...)` after setup
- **THEN** the resulting `Node.ncpus is None` (no `ncpus=` kwarg is passed); the standalone `get_cpu_cores()` call is NOT made inside the setup path

#### Scenario: deallocate uses external_id to identify VM

- **WHEN** `deallocate(node)` is called and `node.cloud` is a known provider with a registered adapter and config
- **THEN** `adapter.delete_node(cfg=config, external_id=node.external_id)` is called (NOT `host=node.hostname`)

#### Scenario: setup failure deletes VM by external_id

- **WHEN** setup raises `CloudSetupError` or a generic `Exception`
- **THEN** `machine_repository.disconnect(node.node_id)` is awaited BEFORE `adapter.delete_node(cfg=config, external_id=node.external_id)`

#### Scenario: deallocate warns on missing or unknown cloud

- **WHEN** `deallocate(node)` is called and `node.cloud` is `None`, or the named provider has no adapter or config
- **THEN** a warning is logged and the method returns without calling `delete_node`
