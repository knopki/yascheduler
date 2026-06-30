## MODIFIED Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log:
Logger | None = None, *, clouds: CloudProvisionerImpl | None = None) ->
Orchestrator` factory function, exposed at `yascheduler.entrypoints.di`.
The `Config` aggregate SHALL be imported from `yascheduler.entrypoints.config`.
The function SHALL create a `PostgresUnitOfWork` factory and pass it to the
`Orchestrator`. It SHALL construct the SSH infrastructure directly as TWO ports
— a `MachineRepository` (instantiated as `SSHMachineRepository`) and a
`MachineOperations` (instantiated as `SSHMachineOperations`) — and pass both to
the `Orchestrator` and to `CloudProvisionerImpl`.

The composition root SHALL NOT introduce a DB-facade class. Persistence is
accessed only via `PostgresUnitOfWork` and the repository ports
(`TaskRepository`, `NodeRepository`).

The composition root SHALL NOT use `typing.cast` to bridge between the
domain `CloudConfig` Protocol and the infra `ConfigCloud` Union. The
`typing.cast` symbol SHALL NOT be imported by `yascheduler.entrypoints.di`.

#### Scenario: Config imported from entrypoints

- **WHEN** `yascheduler.entrypoints.di` is inspected for its `Config` import
- **THEN** it imports `Config` from `yascheduler.entrypoints.config` (or `yascheduler.entrypoints`)

#### Scenario: No DB-facade import in the composition root

- **WHEN** `yascheduler.entrypoints.di` is imported
- **THEN** it does NOT import a `DB` facade, and no `DB`-like facade class is introduced; persistence is wired only via `PostgresUnitOfWork`
