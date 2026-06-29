## MODIFIED Requirements

### Requirement: MachineRepository, MachineSession, and MachineOperations ports replace MachineGateway

The system SHALL define three `@runtime_checkable` Protocols in
`yascheduler/domain/ports.py`:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_session`/`__contains__`/`__len__`).
  Returns `MachineSession` from `connect`/`list_free`/`list_connected`/
  `get_session`. SHALL NOT declare state transitions, accessor
  getters, or the monitor mechanism — those are on `MachineSession`.
- `MachineSession` — the connected-machine entity handle: identity
  (`ip`, `machine`), state transitions (`occupy`/`release`/`update`),
  connect-time config (`adapter`, `platforms`, `data_dir`,
  `engines_dir`, `tasks_dir`), adapter-derived accessors (`path`,
  `quote`, `hostname`), base primitives (`run`/`run_full`/`run_bg`/
  `upload`/`open_sftp`/`get_cpu_cores`/`setup_node`/`pgrep`/
  `list_processes`), monitor mechanism (`install_monitor`/
  `cancel_monitor`), and lifecycle (`is_closed`).
- `MachineOperations` — operations on a single machine, with method
  signatures taking `session: MachineSession`. Methods: `run`,
  `run_full`, `run_bg`, `get_cpu_cores`, `setup_node`,
  `start_task_on_machine`, `download_outputs`, `occupancy_check`,
  `start_occupancy_check`.

The full method-signature specification of these three Protocols lives
in the `ssh-infrastructure` capability spec (Requirement: MachineRepository
port, Requirement: MachineSession port, Requirement: SSHMachineSession
implements MachineSession, Requirement: MachineOperations port,
Requirement: SSHMachineOperations composition). The `domain-ports`
capability asserts only that all three Protocols are defined here, are
`@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades.

Application-layer consumers (`allocate_task.py`, `consume_task.py`,
`deallocate_nodes.py`, `abandon_node.py`, `orchestrator.py`) SHALL type
their SSH-side parameters against `MachineRepository`,
`MachineSession`, and/or `MachineOperations` (one or more, depending on
which methods they call) — never against `MachineGateway` (removed by
`decompose-ssh-gateway`).

#### Scenario: All three Protocols are runtime_checkable

- **WHEN** `isinstance(repo_obj, MachineRepository)`,
  `isinstance(session_obj, MachineSession)`, and
  `isinstance(ops_obj, MachineOperations)` are evaluated
- **THEN** all three Protocols are `@runtime_checkable` and
  structural-subtype their implementations