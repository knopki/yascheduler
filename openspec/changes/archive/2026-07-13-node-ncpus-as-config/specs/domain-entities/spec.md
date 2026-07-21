## MODIFIED Requirements

### Requirement: Node persistent record

The system SHALL provide a `Node` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** node record
(one that has been assigned a database `node_id`). Fields: `node_id: NodeId`,
`hostname: str`, `ncpus: int | None`, `enabled: bool`, `cloud: str | None`,
`username: str`, `port: int`, `jump_host: str | None`, `jump_port: int`,
`jump_username: str`, `external_id: str | None`, `status: NodeStatus`,
`created_at: datetime`, `updated_at: datetime`.

A `Node` SHALL always carry a `node_id: NodeId` (never `None`); it is the only
node shape that flows out of a repository. Pre-persistence node records use
`NewNode` (see the "NewNode pre-persistence record" requirement). The conversion
from `NewNode` to `Node` happens in exactly one place:
`NodeRepository.insert`.

`node_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `node_id`, `hostname`, `ncpus` carry no defaults; the remaining
fields follow with their defaults. Construction at all in-repo call sites uses
keyword arguments, so the reorder is source-compatible.

`ncpus: int | None` SHALL be interpreted as **operator-set static config**, not a
discovery cache:

- `None` means "no operator limit — the orchestrator discovers the CPU count at
  spawn via `session.get_cpu_cores()` (memoized per session)".
- `N > 0` means "operator-set static value — used directly at spawn, no remote
  discovery".

The magic `0` sentinel is REMOVED. `0` is no longer a valid stored value — the
DB enforces `(ncpus IS NULL OR ncpus > 0)` and the persistence adapter
round-trips SQL `NULL` as Python `None` without coalescence. The cloud allocator
no longer writes a runtime-discovered `ncpus` into the `Node` (see the cloud
spec); both add paths (static via `yasetnode`, cloud via `allocate`) produce
`Node.ncpus is None` unless an operator sets a static value.

`hostname` is no longer `UNIQUE` on `yascheduler_nodes` (tmp/pending rows carry
`hostname=""` as a sentinel — multiple rows can share `""` after a node is
removed). `NodeRepository` mutators (`enable`/`disable`/`remove`/`update`) key on
`node_id`, not `hostname`. The hostname-keyed lookup methods (`get(ip: str)`,
`get_by_ips(ips: list[str])`) are REMOVED — all lookups are `node_id`-keyed
(`get_by_id`, `get_by_ids`). `node_id` is the primary identity; `hostname` is an
attribute (the transport address).

`created_at`/`updated_at` default to `datetime.now()` mirroring the DB schema
(`DEFAULT NOW()`). The DB always overrides them via RETURNING on insert and on
every read.

`external_id` is `None` for static nodes and set alongside `hostname` only at
cloud allocation time. Future intent: `external_id` becomes the cloud
provider's stable VM identifier, diverging from `hostname` — but that
divergence is out of scope for this change.

`status: NodeStatus` defaults to `NodeStatus.OTHER` (the sole value — a
placeholder for future node lifecycle states).

`jump_host` / `jump_port` / `jump_username` are authoritative SSH
connection-identity fields. They SHALL be populated exactly once at node
creation and SHALL NOT be re-resolved at connect time:

- Static nodes (`yasetnode` add-path): stamped from `config.remote.jump_host` / `config.remote.jump_username` at `NewNode` construction.
- Cloud nodes (cloud allocator): stamped from the matching `CloudConfig` (`prefix == node.cloud`) if it sets both `jump_host` and `jump_username`, otherwise from `config.remote.*` fallback, applied in the same `replace(node, enabled=True, ...)` call that flips `enabled`.

`jump_host = None` means "no tunnel" (direct connection). `MachineRepository.connect` SHALL read these fields directly and SHALL NOT accept `jump_host` / `jump_username` parameters.

#### Scenario: Node creation with defaults

- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `hostname="[IP]"`, `ncpus=4`, and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None, `jump_host` defaults to None, `jump_port` defaults to 22, `jump_username` defaults to "root", `external_id` defaults to None, `status` defaults to `NodeStatus.OTHER`, `created_at`/`updated_at` default to `datetime.now()`

#### Scenario: Static node stamps jump from remote defaults at creation

- **WHEN** `yasetnode` constructs a `NewNode` for a static node while `config.remote.jump_host="bastion.example.com"` and `config.remote.jump_username="jumper"`
- **THEN** the resulting `NewNode.jump_host == "bastion.example.com"` and `NewNode.jump_username == "jumper"` are persisted by `insert`, and the tmp row used for the connect-setup verification already carries them

#### Scenario: Cloud node stamps jump from matching CloudConfig at creation

- **WHEN** the cloud allocator runs `replace(node, enabled=True, ...)` for a node with `cloud="hetzner"`, and the `hetzner` `CloudConfig` has `jump_host="jump.example.com"` and `jump_username="jumper"`
- **THEN** the persisted `Node.jump_host == "jump.example.com"` and `Node.jump_username == "jumper"`

#### Scenario: Cloud node falls back to remote defaults when CloudConfig has no jump

- **WHEN** the cloud allocator runs `replace(node, enabled=True, ...)` for a node whose matching `CloudConfig` does NOT set both `jump_host` and `jump_username`, and `config.remote.jump_host` is set
- **THEN** the persisted `Node.jump_host` / `jump_username` come from `config.remote.*`

#### Scenario: Node ncpus None means discover at spawn

- **WHEN** a Node is instantiated with `ncpus=None`
- **THEN** the orchestrator resolves the CPU count at spawn via `session.get_cpu_cores()` (memoized per session) rather than using a stored value

#### Scenario: Node ncpus positive means operator-set static config

- **WHEN** a Node is instantiated with `ncpus=8`
- **THEN** the orchestrator uses `8` directly at spawn and does NOT call `session.get_cpu_cores()`

### Requirement: NewNode pre-persistence record

The system SHALL provide a `NewNode` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** node record
(one that has not yet been assigned a database `node_id`). Fields:
`hostname: str = ""`, `ncpus: int | None = None`, `enabled: bool = True`,
`cloud: str | None = None`, `username: str = "root"`, `port: int = 22`,
`jump_host: str | None = None`, `jump_port: int = 22`,
`jump_username: str = "root"`, `external_id: str | None = None`,
`status: NodeStatus = NodeStatus.OTHER`.

`NewNode` mirrors the non-`node_id` fields of `Node` with identical defaults,
**except** that `hostname` and `ncpus` carry defaults (`""` and `None`) so the
tmp-reservation call site can construct a tmp node without naming them:
`NewNode(cloud=selected_name, enabled=False)`. The default `hostname=""` is the
empty-string sentinel; the default `ncpus=None` reflects that a tmp node has no
operator-set CPU limit — the count is discovered at spawn via the session cache.

`NewNode` carries no identity attribute; it is converted to a `Node` only by
`NodeRepository.insert`. The tmp-node row is reused as the real node's
identity: `clouds.allocate(provider, tmp_node_id)` returns a `Node` carrying
`node_id == tmp_node_id` (the cloud adapter does NOT return a `NewNode`; the
row already exists). The caller then flips `enabled=TRUE` via
`uow.nodes.update(node)` — it no longer sets `ncpus` (the cloud allocator no
longer writes a discovered value into the `Node`).

#### Scenario: NewNode has no node_id attribute
- **WHEN** a NewNode is instantiated with `hostname="[IP]"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None, `jump_host` to None, `jump_port` to 22, `jump_username` to "root", `external_id` to None, `status` to `NodeStatus.OTHER`

#### Scenario: NewNode defaults ncpus to None
- **WHEN** a NewNode is instantiated with only `cloud="aws"` and `enabled=False`
- **THEN** `ncpus` defaults to `None` (no operator-set limit; discovered at spawn)
