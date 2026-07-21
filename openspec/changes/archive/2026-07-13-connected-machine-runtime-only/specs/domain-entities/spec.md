## MODIFIED Requirements

### Requirement: ConnectedMachine runtime entity

The system SHALL provide a `ConnectedMachine` domain entity as an immutable
`@dataclass(frozen=True)` object with fields (identity first):
`node_id: NodeId`, `platform: str`, `state: MachineState = MachineState.FREE`,
`free_since: float | None = None`.

`node_id` is the first field (identity first). It identifies which `Node`
this connected machine represents. `occupy()`/`release()`/`replace()` SHALL
carry `node_id` through automatically (frozen dataclass — `replace(self,
state=…)` preserves all non-overridden fields, including `node_id`). The
construction site is the machine-repository connect path, which passes
`node_id=node.node_id` from the `Node` parameter of `connect`.

`platform` is runtime-discovered at connect time (via the platform-package
`_detect_platform(...)` call). It is the sole `ConnectedMachine` field that
is not an identity back-reference and not runtime state — it is the
runtime-discovered platform identifier that the `is_compatible(engine.platforms)`
check reads. It does not live on `Node`.

`state` and `free_since` are the runtime-only state of the connected machine.
They SHALL NOT be persisted and SHALL NOT propagate to `Node`. The session
mutates them via `occupy()`/`release()`/`update(machine)`.

`MachineBusyError(self.node_id)` is raised by `occupy()` when the machine is
already BUSY — the error carries the `node_id` (identity). `ConnectedMachine`
SHALL NOT carry `hostname` or `ncpus`; these are not runtime state and not
identity — `hostname` lives on `Node.hostname` (read by the transport layer
at connect) and `SSHMachineSession._hostname` (the session's transport echo
for operator-facing logs); `ncpus` lives on `Node.ncpus` after cloud setup
and is read at deploy time.

#### Scenario: Machine is compatible with platform list
- **WHEN** `machine.is_compatible(("linux", "debian-12"))` is called on a FREE machine with `platform="debian-12"`
- **THEN** returns True

#### Scenario: Occupy free machine
- **WHEN** `machine.occupy()` is called on a FREE machine
- **THEN** a new ConnectedMachine is returned with `state=BUSY` and the same `node_id`, `platform`

#### Scenario: Occupy busy machine raises MachineBusyError carrying node_id only
- **WHEN** `machine.occupy()` is called on a BUSY machine
- **THEN** `MachineBusyError(self.node_id)` is raised; the exception carries `node_id` (identity) and does NOT carry a `hostname` attribute

#### Scenario: Release machine
- **WHEN** `machine.release()` is called
- **THEN** a new ConnectedMachine is returned with `state=FREE`, `free_since` set to current timestamp, and the same `node_id`, `platform`
