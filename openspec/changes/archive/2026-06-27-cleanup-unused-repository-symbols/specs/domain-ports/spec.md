## MODIFIED Requirements

### Requirement: MachineRepository and MachineOperations ports replace MachineGateway

The system SHALL define two `@runtime_checkable` Protocols in
`yascheduler/domain/ports.py` replacing the removed `MachineGateway`:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_machine_state`/`contains`),
  state transitions (`update_machine`/`occupy`/`release`), accessor
  getters (`get_path`/`get_quote`/`get_hostname`), and the generic
  monitor mechanism (`install_monitor`/`cancel_monitor`).
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
