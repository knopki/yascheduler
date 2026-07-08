## MODIFIED Requirements

### Requirement: MachineRepository, MachineSession, and MachineOperations ports

The system SHALL define `@runtime_checkable` Protocols in
`yascheduler/domain/ports.py` for the SSH-side ports:

- `MachineRepository` — connected-machine collection lifecycle
  (`connect`/`disconnect`/`disconnect_all`), queries
  (`list_free`/`list_connected`/`get_session`/`__contains__`/`__len__`).
  Returns `MachineSession` from `connect`/`list_free`/`list_connected`/
  `get_session`.
- `MachineSession` — the connected-machine entity handle: identity
  (`ip`, `machine`), state transitions (`occupy`/`release`/`update`),
  connect-time config, adapter-derived accessors, base primitives
  (`run`/`run_full`/`run_bg`/`upload`/`open_sftp`/`get_cpu_cores`/
  `setup_node`/`pgrep`/`list_processes`), monitor mechanism, and lifecycle.

Full method-signature specification lives in the `ssh-infrastructure` spec.
`domain-ports` asserts only that these Protocols are defined here, are
`@runtime_checkable`, and are exposed via `yascheduler.domain.ports` and
`yascheduler.domain` facades. Application-layer consumers SHALL type
their SSH-side collection parameter against `MachineRepository`.

The former `MachineOperations` Protocol is REMOVED. SSH-side operations
that previously hung off the facade (`start_task_on_machine`,
`download_outputs`, `occupancy_check`, `start_occupancy_check`) are now
invoked directly on the concrete collaborator classes (`TaskDeployer`,
`OutputDownloader`, `OccupancyChecker` from
`yascheduler.infra.ssh.operations`). The facade pass-throughs
(`run`/`run_full`/`run_bg`/`get_cpu_cores`/`setup_node`) are now invoked
directly on the `MachineSession` instance every caller already holds.

#### Scenario: Two Protocols defined in domain/ports.py

- **WHEN** `yascheduler.domain.ports` is inspected
- **THEN** `MachineRepository` and `MachineSession` are defined as `@runtime_checkable` Protocols; no `MachineOperations` Protocol is present
