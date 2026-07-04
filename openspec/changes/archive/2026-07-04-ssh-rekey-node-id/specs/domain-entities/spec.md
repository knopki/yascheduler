## MODIFIED Requirements

### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as an immutable
`@dataclass(frozen=True)` object with fields (identity first):
`node_id: NodeId`, `ip: str`, `platform: str`, `ncpus: int`,
`state: MachineState = MachineState.FREE`, `free_since: float | None = None`.

`node_id` is the first field (identity first). It identifies which `Node`
this connected machine represents. `occupy()`/`release()`/`replace()` SHALL
carry `node_id` through automatically (frozen dataclass — `replace(self,
state=…)` preserves all non-overridden fields, including `node_id`). The
construction site is `SSHMachineRepository._connect_impl`, which passes
`node_id=node.node_id` from the `Node` parameter of `connect`.

`ip` is the transport address (the asyncssh host). It is read at connect
time and exposed via `MachineSession.ip` for transport-level concerns
(`MachineConnectionError`, CLI display, logging). It is NOT the identity —
two `ConnectedMachine` instances with the same `ip` but different `node_id`
are distinct (the dup-IP configuration behind different jump hosts).

`MachineBusyError(self.ip)` is raised by `occupy()` when the machine is
already BUSY — the error keeps `ip` for operator-facing messages (the
address is what the operator recognizes).

#### Scenario: Machine is compatible with platform list

- **WHEN** `machine.is_compatible(("linux", "debian-12"))` is called on a FREE machine with `platform="debian-12"`
- **THEN** returns True

#### Scenario: Busy machine is not compatible

- **WHEN** `machine.is_compatible(("linux",))` is called on a BUSY machine
- **THEN** returns False

#### Scenario: Occupy free machine

- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY` and the same `node_id`, `ip`, `platform`, `ncpus` (only `state` is overridden; `replace()` carries the rest)

#### Scenario: Occupy busy machine raises error

- **WHEN** `machine.occupy()` is called on a BUSY machine
- **THEN** `MachineBusyError` is raised (carrying `self.ip`)

#### Scenario: Release machine

- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE`, `free_since` set to current timestamp, and the same `node_id`, `ip`, `platform`, `ncpus`

#### Scenario: ConnectedMachine carries node_id

- **WHEN** a `ConnectedMachine` is constructed at `SSHMachineRepository._connect_impl` from `Node(node_id=NodeId(7), ip="10.0.0.1", …)`
- **THEN** the resulting `ConnectedMachine` has `node_id == NodeId(7)` and `ip == "10.0.0.1"`

#### Scenario: Two machines sharing an ip are distinct

- **WHEN** two `ConnectedMachine` instances are constructed with `ip="10.0.0.1"` but different `node_id` (`NodeId(1)` and `NodeId(2)`)
- **THEN** they are distinct entities (different `node_id`); both can be registered in `_sessions` under their respective `NodeId` keys without collision

### Requirement: Node persistent record

The system SHALL provide a `Node` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **post-persistence** node record
(one that has been assigned a database `node_id`). Fields: `node_id: NodeId`,
`ip: str`, `ncpus: int`, `enabled: bool`, `cloud: str | None`, `username: str`,
`port: int`.

A `Node` SHALL always carry a `node_id: NodeId` (never `None`); it is the only
node shape that flows out of a repository. Pre-persistence node records use
`NewNode` (see the "NewNode pre-persistence record" requirement). The conversion
from `NewNode` to `Node` happens in exactly one place:
`NodeRepository.insert` (see the `domain-ports` capability).

`node_id` SHALL be the first field (identity first). Field order is valid for a
frozen dataclass: `node_id`, `ip`, `ncpus` carry no defaults; the remaining
fields follow with their defaults. Construction at all in-repo call sites uses
keyword arguments, so the reorder is source-compatible.

After migration 003, `ip` is no longer `UNIQUE` on `yascheduler_nodes`
(migration 003 dropped the `UNIQUE` constraint; tmp/pending rows now carry
`ip=""` as a sentinel — multiple rows can share `""` after a node is removed).
`NodeRepository` mutators (`enable`/`disable`/`remove`/`update`) key on
`node_id`, not `ip`. The ip-keyed lookup methods (`get(ip: str)`,
`get_by_ips(ips: list[str])`) are REMOVED — all lookups are `node_id`-keyed
(`get_by_id`, `get_by_ids`) after the `ssh-rekey-node-id` change. `node_id` is
the primary identity; `ip` is an attribute (the transport address).

#### Scenario: Node creation with defaults

- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `ip="10.0.0.1"`, `ncpus=4`, and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None

#### Scenario: Node always carries node_id

- **WHEN** a Node is obtained from any `NodeRepository` read or insert (`get_by_id`, `get_by_ids`, `list_enabled`, `list_disabled`, `list_all`, `insert`)
- **THEN** `node.node_id` is a `NodeId` instance (never `None`)

#### Scenario: NewNode is the pre-persistence input shape

- **WHEN** a caller prepares a node record for insertion
- **THEN** it constructs a `NewNode` (no `node_id`), passes it to `NodeRepository.insert`, and receives a `Node` carrying the generated `NodeId`

### Requirement: NewNode pre-persistence record

The system SHALL provide a `NewNode` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** node record
(one that has not yet been assigned a database `node_id`). Fields:
`ip: str = ""`, `ncpus: int = 0`, `enabled: bool = True`,
`cloud: str | None = None`, `username: str = "root"`, `port: int = 22`.

`NewNode` mirrors the non-`node_id` fields of `Node` with identical defaults,
**except** that `ip` and `ncpus` carry defaults (`""` and `0`) so the
tmp-reservation call site can construct a tmp node without naming them:
`NewNode(cloud=selected_name, enabled=False)`. Field types are unchanged
(`ip: str`, `ncpus: int`) — no `Optional` is introduced. The default `ip=""`
is the empty-string sentinel; the default `ncpus=0` reflects that a tmp node
has no CPU information until a real VM is provisioned.

`NewNode` carries no identity attribute; it is converted to a `Node` only by
`NodeRepository.insert`. The tmp-node row inserted by `_select_and_insert_tmp`
is reused as the real node's identity: `clouds.allocate(provider, tmp_node_id)`
returns a `Node` carrying `node_id == tmp_node_id` (the cloud adapter does NOT
return a `NewNode`; the row already exists). The caller then flips
`enabled=TRUE` and sets `ip`/`ncpus` via `uow.nodes.update(node)`.

#### Scenario: NewNode has no node_id attribute

- **WHEN** a NewNode is instantiated with `ip="10.0.0.1"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None

#### Scenario: NewNode tmp-reservation defaults

- **WHEN** `NewNode(cloud="aws", enabled=False)` is instantiated
- **THEN** `ip` defaults to `""` (empty-string sentinel), `ncpus` defaults to `0`, `username` defaults to `"root"`, `port` defaults to `22`

#### Scenario: CloudProvisioner.allocate returns Node reusing tmp_node_id

- **WHEN** `CloudProvisioner.allocate("aws", tmp_node_id=NodeId(7))` is called
- **THEN** it returns a `Node` with `node_id == NodeId(7)` (the tmp_node_id), a real `ip` (the provisioned VM's address), and `ncpus` populated from the VM; the caller passes it to `NodeRepository.update` to flip `enabled=TRUE` and persist `ip`/`ncpus`