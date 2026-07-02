## MODIFIED Requirements

### Requirement: NodeRepository port

The system SHALL define a `NodeRepository` Protocol with async methods:
`get(ip: str) -> Node | None`, `get_by_id(node_id: NodeId) -> Node | None`,
`list_enabled() -> list[Node]`, `list_disabled() -> list[Node]`,
`list_all() -> list[Node]`, `insert(new_node: NewNode) -> Node`,
`add_tmp(cloud: str) -> str`, `update(node: Node) -> None`,
`enable(ip: str) -> None`, `disable(ip: str) -> None`, `remove(ip: str) -> None`,
`get_by_ips(ips: list[str]) -> dict[str, Node]`, `count_by_status() -> Mapping[bool, int]`.

`insert(new_node: NewNode) -> Node` is the create method (renamed from `add`).
It takes a pre-persistence `NewNode` and returns the persisted `Node` carrying
the database-generated `node_id`. This mirrors `TaskRepository.insert(task) ->
Task`, which returns the enriched object. The implementation runs
`node/insert.sql ... RETURNING node_id`.

`get_by_id(node_id: NodeId) -> Node | None` is an additive lookup by primary
key. There is no batch `get_by_ids` (no consumer identified). A batch variant
mirroring `get_by_ips` is explicitly out of scope.

`add_tmp` takes only `cloud: str` — the `username` column on
`yascheduler_nodes` retains its `DEFAULT 'root'` and the tmp-row falls back to
that default. The tmp-row is a short-lived placeholder (`enabled=FALSE`)
removed before any reader touches it; no caller needs to supply a username.
`add_tmp`'s signature and return type (`-> str`, the generated placeholder ip)
are **unchanged** by this change; reworking it is a deferred follow-up.

All ip-keyed mutators (`get`, `enable`, `disable`, `remove`, `update`,
`get_by_ips`) keep their ip keying. `update(node)` keeps `WHERE ip = :ip`
internally (`ip UNIQUE` protects the write); switching these to
`WHERE node_id =` is an explicit non-goal, deferred until `ip UNIQUE` is
relaxed in a future change. This change **carries** `node_id`; it does not
**replace** ip-based identification.

#### Scenario: Full node lifecycle through port
- **WHEN** a consumer calls `insert`, `get`, `get_by_id`, `update`, `enable`, `disable`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `remove` through the port
- **THEN** the Protocol defines all these operations with async signatures

#### Scenario: Insert takes NewNode returns Node
- **WHEN** `insert(NewNode(ip="10.0.0.1", ncpus=4))` is called
- **THEN** a `Node` is returned whose `node_id` is the database-generated `NodeId` and whose other fields match the `NewNode`

#### Scenario: Get node by id
- **WHEN** `get_by_id(NodeId(5))` is called and a row with node_id=5 exists
- **THEN** a `Node` is returned with `node_id == NodeId(5)`; if no such row exists, `None` is returned

#### Scenario: Add temporary node takes only cloud
- **WHEN** `add_tmp("aws")` is called
- **THEN** a tmp-node row is inserted with `enabled=FALSE`, the given cloud, and `username` left to the DB default (`'root'`); the generated placeholder ip is returned (unchanged behavior)

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str) -> NewNode` (async),
`deallocate(cloud: str, ip: str) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync).

`allocate` returns a `NewNode` (pre-persistence) — a freshly-built VM that has
NOT been written to `yascheduler_nodes`. The caller (`allocate_task`) persists
it via `NodeRepository.insert(new_node) -> Node`. Returning `NewNode` (rather
than `Node`) is honest about persistence state: a `Node` always carries a
`node_id`, which does not exist until `insert` runs.

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `str | None` (the selected provider name or
`None`), then calls `allocate(selection)`.

`deallocate` takes `cloud` explicitly because the adapter no longer reads
the database to resolve the provider from `ip`. The caller (use case) has
the `Node` and passes `node.cloud`.

`select_provider` is sync — it does no I/O. It returns `None` when no
provider has capacity OR when the selected provider's op semaphore is
locked (throttle). The caller's `selection is None` branch handles
cleanup.

`capacity()` is not part of the port — capacity counting is a use case /
orchestrator responsibility, not a cloud adapter concern.

`select_provider` returns the selected provider's name as a bare `str`,
matching the identity-string convention used across `NodeRepository`
(`get(ip: str)`, `remove(ip: str)`, `enable(ip: str)`, `disable(ip: str)`).
No `ProviderSelection` value object is defined; the application layer
treats the returned string as an opaque provider identity and passes it
back to `allocate`/`deallocate` unchanged.

#### Scenario: Allocate cloud node returns NewNode
- **WHEN** `allocate("aws")` is called with a valid provider name
- **THEN** returns a `NewNode` with the provisioned IP (no DB write inside the adapter; the caller persists via `NodeRepository.insert`)

#### Scenario: Deallocate cloud node with explicit cloud
- **WHEN** `deallocate(cloud="aws", ip="10.0.0.1")` is called
- **THEN** the VM at the given IP is deleted via the named provider's SDK

#### Scenario: Select provider returns provider name string
- **WHEN** `select_provider(["linux"], {"aws": 0})` is called and aws has capacity and supports linux
- **THEN** returns the string `"aws"` (the selected provider's name)

#### Scenario: Select provider returns None on no capacity
- **WHEN** `select_provider(["linux"], {"aws": 10})` is called and aws max_nodes is 10
- **THEN** returns `None`

#### Scenario: Select provider returns None on throttle
- **WHEN** the selected provider's op semaphore is locked
- **THEN** `select_provider` returns `None` (does not raise)
