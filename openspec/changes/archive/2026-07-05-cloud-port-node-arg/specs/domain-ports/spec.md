## MODIFIED Requirements

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str, node: Node) -> Node` (async),
`deallocate(node: Node) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> str | None` (sync).

`allocate` takes the tmp-node `Node` (post-insert identity — the row already
exists with the tmp `node_id`) and returns a `Node` reusing that same
`node_id`. The caller (`allocate_task`) inserted the tmp-node row via
`uow.nodes.insert(NewNode(cloud=..., enabled=False)) -> Node` and passes that
`Node` to `allocate`. The cloud adapter reuses the passed node's `node_id` as
the real node's identity: the setup SSH session registers under it, and the
returned `Node` carries the same `node_id`. The caller then flips the row to
`enabled=TRUE` and sets `ip`/`ncpus` via a single `uow.nodes.update(node)`.
This is one row per cloud allocation lifecycle, not two.

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `str | None` (the selected provider name or
`None`), then calls `allocate(selection, node)`.

`deallocate` takes the `Node` and reads `node.cloud` (the provider name) and
`node.ip` (the cloud SDK host identifier) internally — the caller no longer
unpacks them. When `node.cloud` is `None` the adapter SHALL log and return
without deleting a VM. `deallocate` stays ip-keyed for the actual VM lookup —
`ip` is the cloud SDK host identifier (migrating VM identification to a
`node_id`-derived tag is a future cloud-adapter change).

`select_provider` is sync — it does no I/O. It returns `None` when no
provider has capacity OR when the selected provider's op semaphore is
locked (throttle). The caller's `selection is None` branch handles
cleanup.

`capacity()` is not part of the port — capacity counting is a use case /
orchestrator responsibility, not a cloud adapter concern.

`select_provider` returns the selected provider's name as a bare `str`,
matching the identity-string convention used across `NodeRepository`
(`get_by_id(node_id)`, `remove(node_id)`, `enable(node_id)`,
`disable(node_id)`). No `ProviderSelection` value object is defined; the
application layer treats the returned string as an opaque provider identity
and passes it back to `allocate`/`deallocate` unchanged.

#### Scenario: Allocate cloud node returns Node reusing the passed node's identity

- **WHEN** `allocate("aws", node)` is called with a valid provider name and a tmp-node `Node` carrying `node_id == NodeId(7)`
- **THEN** returns a `Node` with `node_id == NodeId(7)`, a real `ip` (the provisioned VM's address), `enabled=True`, and `ncpus` populated from the VM; no DB write inside the adapter; the caller persists via `NodeRepository.update(node)`

#### Scenario: Deallocate cloud node reads provider and host from the node

- **WHEN** `deallocate(node)` is called with a `Node` carrying `cloud="aws"` and `ip="10.0.0.1"`
- **THEN** the VM at `10.0.0.1` is deleted via the `aws` provider's SDK

#### Scenario: Deallocate no-ops when node has no cloud

- **WHEN** `deallocate(node)` is called with a `Node` whose `cloud` is `None`
- **THEN** no provider SDK is invoked; the adapter logs and returns

#### Scenario: Select provider returns provider name string

- **WHEN** `select_provider(["linux"], {"aws": 0})` is called and aws has capacity and supports linux
- **THEN** returns the string `"aws"` (the selected provider's name)

#### Scenario: Select provider returns None on no capacity

- **WHEN** `select_provider(["linux"], {"aws": 10})` is called and aws max_nodes is 10
- **THEN** returns `None`

#### Scenario: Select provider returns None on throttle

- **WHEN** the selected provider's op semaphore is locked
- **THEN** `select_provider` returns `None` (does not raise)
