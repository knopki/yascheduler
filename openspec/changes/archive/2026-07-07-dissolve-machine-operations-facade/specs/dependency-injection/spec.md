## MODIFIED Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log:
Logger | None = None, *, clouds: CloudProvisionerImpl | None = None) ->
Orchestrator` factory function, exposed at `yascheduler.entrypoints.di`.
The `Config` aggregate SHALL be imported from `yascheduler.entrypoints.config`.
The function SHALL create a `PostgresUnitOfWork` factory and pass it to the
`Orchestrator`. It SHALL construct the SSH infrastructure directly as a
`MachineRepository` (instantiated as `SSHMachineRepository`) plus three
stateless collaborator instances (`TaskDeployer`, `OutputDownloader`,
`OccupancyChecker` from `yascheduler.infra`, each constructed with `log`)
and pass the repository and the three collaborators to the `Orchestrator`.

`CloudProvisionerImpl` is constructed with `machine_repository` only — it
no longer takes any operations-side parameter; its `_setup_vm` calls
session pass-through methods (`session.run`/`session.setup_node`/
`session.get_cpu_cores`) directly on the session returned by
`machine_repository.connect`.

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

#### Scenario: Three collaborators constructed and passed to Orchestrator

- **WHEN** `make_daemon(config)` is called
- **THEN** exactly one instance each of `TaskDeployer(log=log)`, `OutputDownloader(log=log)`, `OccupancyChecker(log=log)` is constructed; all three are passed to `Orchestrator(...)` as `task_deployer=`, `output_downloader=`, `occupancy_checker=` keyword arguments

### Requirement: make_daemon shares one SSHMachineRepository on the production path

On the `clouds is None` branch, `make_daemon` SHALL construct exactly one
`SSHMachineRepository` instance and inject the SAME instance into both
`CloudProvisionerImpl.machine_repository` and `Orchestrator.repository`.
This ensures a single `_sessions` registry spans cloud setup (via
`_setup_vm`) and orchestrator runtime, so that connections opened during
cloud allocation are visible to the orchestrator and are reaped by
`Orchestrator.stop()` via `repository.disconnect_all()`.

`CloudProvisionerImpl` SHALL be constructed WITHOUT any operations-side
parameter — it has no `machine_operations` field. The three stateless
collaborators (`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`)
are taken by the orchestrator only; `CloudProvisionerImpl._setup_vm`
calls `session.run`/`session.setup_node`/`session.get_cpu_cores` directly.

The pre-built-clouds (`clouds is not None`) branch SHALL continue to
construct a fresh `SSHMachineRepository` for the orchestrator while the
caller-supplied `clouds` retain whatever repository it was built with.
This branch is exercised only by unit tests and performs no real
allocations.

This requirement exists to prevent two correctness defects that arise
from split registries: (1) every allocated cloud node leaks one SSH
connection for the process lifetime because the cloud repository is
never drained, and (2) the orchestrator opens a second connection to
each cloud VM because its `contains(ip)` filter inspects only its own
registry.

#### Scenario: clouds is None shares one repository instance

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** the `SSHMachineRepository` instance passed as `CloudProvisionerImpl.machine_repository` SHALL be the same object (`is`) as the instance passed as `Orchestrator.repository`

#### Scenario: clouds is None constructs exactly one SSHMachineRepository

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `SSHMachineRepository(...)` SHALL be invoked exactly once across the construction of `CloudProvisionerImpl` and `Orchestrator`

#### Scenario: CloudProvisionerImpl constructed without operations port

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `CloudProvisionerImpl(...)` SHALL be invoked with `machine_repository=` but WITHOUT any `machine_operations=` (or equivalent operations-side) keyword argument

#### Scenario: clouds is None constructs three collaborator instances

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `TaskDeployer(...)`, `OutputDownloader(...)`, and `OccupancyChecker(...)` SHALL each be invoked exactly once; all three instances are passed to `Orchestrator(...)`

#### Scenario: pre-built clouds path keeps its own repository

- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the orchestrator SHALL be constructed with a `repository` that is a freshly-constructed `SSHMachineRepository`, NOT taken from `my_clouds`; the caller-supplied `clouds` instance SHALL be wired to the orchestrator unchanged

#### Scenario: cloud-allocation connections are visible to orchestrator

- **WHEN** a cloud node is allocated via `clouds.allocate(provider)` and `_setup_vm` connects it via `machine_repository.connect(node=...)`
- **THEN** a subsequent `_connect_machine_producer` cycle in the orchestrator SHALL observe `repository.contains(node.node_id) == True` for that node and SHALL NOT call `repository.connect(...)` again for it

#### Scenario: cloud-allocation connections are reaped at shutdown

- **WHEN** `Orchestrator.stop()` runs after one or more cloud nodes have been allocated on the `clouds is None` path
- **THEN** `repository.disconnect_all()` SHALL close every connection opened by `_setup_vm`, leaving no cloud-setup SSH connection open at process exit
