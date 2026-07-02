## MODIFIED Requirements

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

The `ip`-based identity legacy is deliberately **not** removed in this change:
`ip` remains `UNIQUE` and remains the key for `Task.allocated_ip`,
`ConnectedMachine.ip`, `MachineSession.ip`, and the ip-keyed `NodeRepository`
mutators (`get`/`enable`/`disable`/`remove`/`update`/`get_by_ips`). `node_id`
is carried alongside `ip`, not swapped for it.

#### Scenario: Node creation with defaults
- **WHEN** a Node is instantiated with `node_id=NodeId(1)`, `ip="10.0.0.1"`, `ncpus=4`, and `enabled=True`
- **THEN** `username` defaults to "root", `port` defaults to 22, `cloud` defaults to None

#### Scenario: Node always carries node_id
- **WHEN** a Node is obtained from any `NodeRepository` read or insert (`get`, `get_by_id`, `list_enabled`, `list_disabled`, `list_all`, `get_by_ips`, `insert`)
- **THEN** `node.node_id` is a `NodeId` instance (never `None`)

#### Scenario: NewNode is the pre-persistence input shape
- **WHEN** a caller prepares a node record for insertion
- **THEN** it constructs a `NewNode` (no `node_id`), passes it to `NodeRepository.insert`, and receives a `Node` carrying the generated `NodeId`

### Requirement: Domain entities are importable from yascheduler.domain.model

The system SHALL expose all domain entities from `yascheduler.domain.model`.

#### Scenario: Import entities
- **WHEN** `from yascheduler.domain.model import Task, Node, NewNode, NodeId, ConnectedMachine, TaskContext, Engine, TaskStatus, MachineState, ProcessResult`
- **THEN** all symbols are available (including the new `NewNode` and `NodeId`)

## ADDED Requirements

### Requirement: NodeId value object

The system SHALL provide a `NodeId` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/model.py` wrapping a single
field `value: int`. `NodeId` SHALL:

- validate in `__post_init__` that `value > 0`, raising `ValueError` otherwise
  (`yascheduler_nodes.node_id SERIAL PRIMARY KEY` starts at 1, so a non-positive
  value indicates a bug);
- define `__str__` returning `str(self.value)` so CLI rendering and logging
  produce the bare integer string (not the dataclass `repr`
  `NodeId(value=5)`);
- be hashable (frozen dataclass) and usable as a dict key;
- NOT be equal to a bare `int` — `NodeId(5) == 5` is `False`. This is the
  type-safety point of a dedicated value object: callers cannot accidentally
  mix a `NodeId` with an unrelated `int`.

At external boundaries the wrapped `.value` SHALL be unwrapped explicitly:
pg8000 SQL parameters pass `node_id.value` (pg8000 cannot adapt a dataclass);
JSON serialization emits `node_id.value`; argparse wraps `NodeId(int(s))` after
a `str.isdigit()` discriminator check; DB-read mapping wraps
`NodeId(int(row["node_id"]))`.

`NodeId` SHALL NOT be `typing.NewType('NodeId', int)` (erased to `int` at
runtime, no validation, no methods) and SHALL NOT subclass `int` (defeats
value-object ergonomics and the explicit "frozen dataclass with value: int"
design).

#### Scenario: NodeId validates positive
- **WHEN** `NodeId(0)` or `NodeId(-3)` is constructed
- **THEN** `ValueError` is raised

#### Scenario: NodeId str renders the bare integer
- **WHEN** `str(NodeId(5))` or `f"{NodeId(5)}"` is evaluated
- **THEN** the result is `"5"` (NOT `"NodeId(value=5)"`)

#### Scenario: NodeId is not equal to int
- **WHEN** `NodeId(5) == 5` is evaluated
- **THEN** the result is `False`

#### Scenario: NodeId is hashable
- **WHEN** `hash(NodeId(5))` is evaluated or `NodeId(5)` is used as a dict key
- **THEN** it succeeds (frozen dataclass is hashable)

#### Scenario: NodeId wraps DB-generated serial on read
- **WHEN** a row with `node_id = 7` is read from `yascheduler_nodes`
- **THEN** `_row_to_node` constructs `NodeId(int(row["node_id"]))` → `NodeId(7)`

### Requirement: NewNode pre-persistence record

The system SHALL provide a `NewNode` domain entity as an immutable
`@dataclass(frozen=True)` object representing a **pre-persistence** node record
(one that has not yet been assigned a database `node_id`). Fields: `ip: str`,
`ncpus: int`, `enabled: bool = True`, `cloud: str | None = None`,
`username: str = "root"`, `port: int = 22`.

`NewNode` mirrors the non-`node_id` fields of `Node` with identical defaults.
It carries no identity attribute; it is converted to a `Node` only by
`NodeRepository.insert`. `CloudProvisioner.allocate` returns a `NewNode` (a
freshly-built VM that has not been persisted); the caller persists it via
`insert` and receives the `Node`.

#### Scenario: NewNode has no node_id attribute
- **WHEN** a NewNode is instantiated with `ip="10.0.0.1"` and `ncpus=4`
- **THEN** it has no `node_id` field; `enabled` defaults to True, `username` to "root", `port` to 22, `cloud` to None

#### Scenario: CloudProvisioner.allocate returns NewNode
- **WHEN** `CloudProvisioner.allocate("aws")` is called
- **THEN** it returns a `NewNode` (pre-persistence); the caller passes it to `NodeRepository.insert` to obtain a persisted `Node`
