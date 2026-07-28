## Purpose

The domain entity model for yascheduler. It defines the persistent
records for tasks and nodes, the runtime state of a connected machine,
the engine specification, and the identity value objects. Each entity
owns its lifecycle rules. A task record emits the events defined in the
`domain-events-and-dispatch` spec.

## Requirements

### Requirement: Identity value objects

The system SHALL provide identity value objects for tasks and for nodes.
Each identity wraps a positive integer. The system SHALL reject zero and
negative values. The wrapped value SHALL be exposed as a bare integer at
every external boundary (SQL, JSON, CLI).

#### Scenario: identity rejects non-positive values

- **WHEN** an identity is constructed with zero or a negative value
- **THEN** construction fails with a value error

### Requirement: Pre-persistence task and node records

The system SHALL provide pre-persistence record shapes for tasks and for
nodes. These shapes carry no identity and no lifecycle. The repository
attaches the generated identity and the initial state on insert. The
insert contract lives in the `domain-ports` spec.

#### Scenario: pre-persistence record carries no identity or state

- **WHEN** a pre-persistence record is constructed
- **THEN** it has no identity, no status, and no allocated-node binding

### Requirement: Task record and lifecycle

The system SHALL provide a task record as the post-persistence shape
returned by the task repository. The record owns its lifecycle. A
transition validates the source state, applies the field changes, records
the matching event, and returns a new task record. The event types live
in the `domain-events-and-dispatch` spec.

The valid transitions are:

| Source state | Trigger | Result state | Recorded event |
|---|---|---|---|
| TO_DO | start on a node | RUNNING | TaskAllocated |
| TO_DO | reject as unsupported | DONE | TaskFailed |
| RUNNING | complete successfully | DONE | TaskCompleted |
| RUNNING | fail with partial output | DONE | TaskFailed |
| RUNNING | abandon a lost node | DONE | TaskAbandoned |

A task starts unallocated. It binds to a node only when it starts. If its
node is deleted later, the task becomes unallocated again.

#### Scenario: valid transition applies and records the event

- **WHEN** a transition listed in the table is applied to a task in the matching source state
- **THEN** the returned task has the result state, the trigger's field changes, and one recorded event of the listed type

#### Scenario: invalid source state raises

- **WHEN** a transition is applied to a task whose state is not the source state in the table
- **THEN** the call raises and no event is recorded

#### Scenario: abandon with no node records no event

- **WHEN** abandon is applied to a RUNNING task whose node was deleted, leaving the task unallocated
- **THEN** the task moves to DONE with the abandon error, and no TaskAbandoned event is recorded

### Requirement: TaskCreated is emitted on first persistence

A task SHALL be recorded with one `TaskCreated` event when it is first
inserted by the task repository. The repository is the sole emission
site.

#### Scenario: insert attaches TaskCreated

- **WHEN** a pre-persistence task record is inserted
- **THEN** the returned task carries one TaskCreated event

### Requirement: Node record

The system SHALL provide a node record as the post-persistence shape
returned by the node repository. It carries an identity, a hostname, and
an enabled flag.

The CPU count field has two interpretations:

| Value | Behavior at spawn |
|---|---|
| Empty (no operator value) | The orchestrator discovers the CPU count on the remote node. |
| Positive integer (operator value) | The orchestrator uses the value directly. |

The three SSH jump fields are authoritative connection identity. They
are stamped once at node creation from one source. They SHALL NOT be
re-resolved at connect time. An empty jump host means a direct
connection with no tunnel. The source is selected by this table:

| Node origin | Cloud jump configuration | Source of all three jump fields |
|---|---|---|
| Static add | not applicable | remote default configuration |
| Cloud | sets host AND username | cloud configuration |
| Cloud | missing host OR username | remote default configuration |

The three jump fields SHALL all come from one source. A node SHALL NOT
mix a cloud jump host with a remote jump port.

#### Scenario: jump fields come from a single source

- **WHEN** a cloud node is created and its cloud configuration sets the host but not the username
- **THEN** all three jump fields come from the remote default configuration, so the cloud leg is not half-authoritative

### Requirement: ConnectedMachine runtime state

The system SHALL provide a connected-machine record as a runtime view of
a connected node. It carries the node identity, the discovered platform,
and a runtime state. The runtime state and the idle timestamp SHALL NOT
persist and SHALL NOT propagate to the node record.

The machine SHALL be compatible with a list of accepted platforms when
its discovered platform is in the list. Occupying a free machine moves
it to busy. Occupying a busy machine raises an error that carries the
node identity. Releasing a busy machine moves it to free and records the
current time as the idle timestamp.

#### Scenario: occupy and release toggle the state

- **WHEN** a free machine is occupied and then released
- **THEN** the occupied machine is busy with the same node identity and platform; the released machine is free with the idle timestamp set to the current time

#### Scenario: occupy on a busy machine raises

- **WHEN** a busy machine is occupied
- **THEN** the call raises an error that carries the node identity

### Requirement: Supporting types

The system SHALL provide these supporting types:

- An engine specification record. The record SHALL fail construction when a required input is missing.
- A process result record for a completed remote command.
- A machine state with the FREE and BUSY values.
- A node status with an OTHER placeholder value for future node lifecycle states.

The engine collection SHALL support lookup by name, membership test, and
platform-based filtering that returns a new collection.

#### Scenario: engine construction fails on missing required input

- **WHEN** an engine is constructed without a required input
- **THEN** construction fails
