## ADDED Requirements

### Requirement: MachineRepository and MachineOperations ports replace MachineGateway

The system SHALL define two `@runtime_checkable` Protocols in
`yascheduler/domain/ports.py` replacing the removed `MachineGateway`:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_machine_state`/`contains`),
  state transitions (`update_machine`/`occupy`/`release`), accessor
  getters (`get_adapter`/`get_platforms`/`get_path`/`get_quote`/
  `get_data_dir`/`get_engines_dir`/`get_tasks_dir`/`get_hostname`),
  connection lifecycle (`get_conn`), and the generic monitor mechanism
  (`install_monitor`/`cancel_monitor`).
- `MachineOperations` — operations on a single machine:
  `run`/`run_full`/`run_bg`, `upload`/`download`/`get_sftp`,
  `pgrep`/`list_processes`, `get_cpu_cores`/`setup_node`,
  `start_task_on_machine`, `download_outputs`, `occupancy_check`,
  `start_occupancy_check`.

The full method-signature specification of these two Protocols lives
in the `ssh-machine-repository` capability spec (Requirement:
MachineRepository port, Requirement: MachineOperations port, Requirement:
SSHMachineOperations composition). The `domain-ports` capability
asserts only that both Protocols are defined here, are
`@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades.

Application-layer consumers (`allocate_task.py`, `consume_task.py`,
`deallocate_nodes.py`, `abandon_node.py`, `orchestrator.py`) SHALL type
their SSH-side parameters against `MachineRepository` and
`MachineOperations` (one or both, depending on which methods they call)
— never against `MachineGateway` (removed).

#### Scenario: Import MachineRepository from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineRepository`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: Import MachineOperations from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineOperations`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: Both Protocols are runtime_checkable

- **WHEN** `isinstance(repository_obj, MachineRepository)` and
  `isinstance(operations_obj, MachineOperations)` are evaluated
- **THEN** both Protocols are `@runtime_checkable` and structural-subtype
  their implementations

#### Scenario: Application consumers type against the two new Protocols

- **WHEN** `application/orchestrator.py`, `application/allocate_task.py`,
  `application/consume_task.py`, `application/deallocate_nodes.py`, and
  `application/abandon_node.py` are inspected for SSH-side parameter
  annotations
- **THEN** the annotations are `MachineRepository` and/or
  `MachineOperations` (per the methods each consumer calls); the
  annotation `MachineGateway` does not appear in any of these files

## MODIFIED Requirements

### Requirement: Ports are importable from domain

The system SHALL expose all port Protocols from `yascheduler.domain.ports`,
including `CloudConfig`, `MachineRepository`, and `MachineOperations`.

The module SHALL NOT export `MachineGateway` — the Protocol is removed
and replaced by `MachineRepository` + `MachineOperations`.

#### Scenario: Import ports for adapter implementation

- **WHEN** an adapter module imports `from yascheduler.domain.ports import TaskRepository`
- **THEN** the Protocol class is available for structural subtyping

#### Scenario: Import MachineRepository and MachineOperations from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import MachineRepository, MachineOperations`
- **THEN** the Protocol classes resolve without ImportError

#### Scenario: Import CloudConfig from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: MachineGateway not exported

- **WHEN** `yascheduler.domain.ports` is inspected for `MachineGateway`
- **THEN** the name is absent; the Protocol has been removed and replaced by `MachineRepository` + `MachineOperations`

## REMOVED Requirements

### Requirement: MachineGateway port

**Reason:** The single `MachineGateway` Protocol conflated two
architectural responsibilities (machine collection lifecycle + operations
on a single machine). It is split into `MachineRepository` and
`MachineOperations` Protocols (see ADDED Requirements). All consumers
take one or both of the new Protocols instead of one `MachineGateway`.

**Migration:**
- Consumers needing collection operations (`connect`, `disconnect`,
  `list_free`, `list_connected`, `contains`, `get_machine_state`,
  `update_machine`) SHALL depend on `MachineRepository`.
- Consumers needing per-machine operations (`run`, `run_bg`, `upload`,
  `download`, `download_outputs`, `start_task_on_machine`,
  `start_occupancy_check`, `get_cpu_cores`, `setup_node`,
  `occupancy_check`) SHALL depend on `MachineOperations`.
- Consumers needing both (e.g., `orchestrator.py`) SHALL take two
  parameters (`repository: MachineRepository`, `operations:
  MachineOperations`) instead of one `gateway`.
- The CloudConfig sub-prose previously attached to this requirement has
  already been moved to its own `CloudConfig structural Protocol`
  requirement (per the prior change `resolve-type-bridge-debt`); the
  `MachineGateway port` removal does not affect `CloudConfig`.
- All `### Scenario: No stale "without inheritance" prose under
  MachineGateway port` references SHALL be reinterpreted against the
  removed requirement — the prose no longer exists to carry the stale
  text.