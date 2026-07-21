## MODIFIED Requirements

### Requirement: Node persistent record

The system SHALL provide a `Node` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** node record
(one that has been assigned a database `node_id`). Fields: `node_id: NodeId`,
`hostname: str`, `ncpus: int`, `enabled: bool`, `cloud: str | None`,
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

`jump_host`/`jump_port`/`jump_username` are placeholder fields not consumed by
code yet; they mirror the cloud-config jump-host parameters for future SSH
connection routing.

#### Scenario: Node creation with defaults
- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `hostname="[IP]"`, `ncpus=4`, and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None, `jump_host` defaults to None, `jump_port` defaults to 22, `jump_username` defaults to "root", `external_id` defaults to None, `status` defaults to `NodeStatus.OTHER`, `created_at`/`updated_at` default to `datetime.now()`

### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as an immutable
`@dataclass(frozen=True)` object with fields (identity first):
`node_id: NodeId`, `hostname: str`, `platform: str`, `ncpus: int`,
`state: MachineState = MachineState.FREE`, `free_since: float | None = None`.

`node_id` is the first field (identity first). It identifies which `Node`
this connected machine represents. `occupy()`/`release()`/`replace()` SHALL
carry `node_id` through automatically (frozen dataclass — `replace(self,
state=…)` preserves all non-overridden fields, including `node_id`). The
construction site is the machine-repository connect path, which passes
`node_id=node.node_id` from the `Node` parameter of `connect`.

`hostname` is the transport address (the asyncssh host). It is read at connect
time and exposed via `MachineSession.hostname` for transport-level concerns
(`MachineConnectionError`, CLI display, logging). It is NOT the identity —
two `ConnectedMachine` instances with the same `hostname` but different
`node_id` are distinct (the dup-hostname configuration behind different jump
hosts).

`MachineBusyError(self.node_id, self.hostname)` is raised by `occupy()` when
the machine is already BUSY — the error carries both `node_id` (identity) and
`hostname` (the address the operator recognizes).

#### Scenario: Machine is compatible with platform list
- **WHEN** `machine.is_compatible(("linux", "debian-12"))` is called on a FREE machine with `platform="debian-12"`
- **THEN** returns True

#### Scenario: Occupy free machine
- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY` and the same `node_id`, `hostname`, `platform`, `ncpus`

#### Scenario: Release machine
- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE`, `free_since` set to current timestamp, and the same `node_id`, `hostname`, `platform`, `ncpus`

### Requirement: NewNode pre-persistence record

The system SHALL provide a `NewNode` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** node record
(one that has not yet been assigned a database `node_id`). Fields:
`hostname: str = ""`, `ncpus: int = 0`, `enabled: bool = True`,
`cloud: str | None = None`, `username: str = "root"`, `port: int = 22`,
`jump_host: str | None = None`, `jump_port: int = 22`,
`jump_username: str = "root"`, `external_id: str | None = None`,
`status: NodeStatus = NodeStatus.OTHER`.

`NewNode` mirrors the non-`node_id` fields of `Node` with identical defaults,
**except** that `hostname` and `ncpus` carry defaults (`""` and `0`) so the
tmp-reservation call site can construct a tmp node without naming them:
`NewNode(cloud=selected_name, enabled=False)`. Field types are unchanged
(`hostname: str`, `ncpus: int`) — no `Optional` is introduced. The default
`hostname=""` is the empty-string sentinel; the default `ncpus=0` reflects
that a tmp node has no CPU information until a real VM is provisioned.

`NewNode` carries no identity attribute; it is converted to a `Node` only by
`NodeRepository.insert`. The tmp-node row is reused as the real node's
identity: `clouds.allocate(provider, tmp_node_id)` returns a `Node` carrying
`node_id == tmp_node_id` (the cloud adapter does NOT return a `NewNode`; the
row already exists). The caller then flips `enabled=TRUE` and sets
`hostname`/`ncpus` via `uow.nodes.update(node)`.

#### Scenario: NewNode has no node_id attribute
- **WHEN** a NewNode is instantiated with `hostname="[IP]"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None, `jump_host` to None, `jump_port` to 22, `jump_username` to "root", `external_id` to None, `status` to `NodeStatus.OTHER`

## ADDED Requirements

### Requirement: NodeStatus enum

The system SHALL provide a `NodeStatus` enum as a `StrEnum` with a single value
`OTHER = "OTHER"`. `NodeStatus` SHALL be sourced via `yascheduler.shared.compat`
(version-branch: `enum.StrEnum` on Python 3.11+, `typing_extensions.StrEnum`
below 3.11).

`OTHER` is a placeholder for future node lifecycle states. The enum value
`"OTHER"` matches the `TASK_STATUS` convention (enum label == name, DB lookup
via `NodeStatus[row["status"]]`).

The `NODE_STATUS` PostgreSQL enum type SHALL mirror the Python enum.

#### Scenario: NodeStatus has OTHER value
- **WHEN** `NodeStatus` is inspected
- **THEN** `NodeStatus.OTHER` is defined with value `"OTHER"`

#### Scenario: NodeStatus is a StrEnum
- **WHEN** `isinstance(NodeStatus.OTHER, str)` is checked
- **THEN** it returns `True` (StrEnum members are str instances)

#### Scenario: NodeStatus DB lookup by name
- **WHEN** `NodeStatus["OTHER"]` is called
- **THEN** it returns `NodeStatus.OTHER` (name-based lookup, matching the `TASK_STATUS` pattern)