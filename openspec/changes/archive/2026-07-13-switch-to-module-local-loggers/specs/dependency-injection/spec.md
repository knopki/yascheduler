## MODIFIED Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, *, clouds:
CloudProvisionerImpl | None = None) -> Orchestrator` factory function, exposed
at `yascheduler.entrypoints.di`. The `Config` aggregate SHALL be imported from
`yascheduler.entrypoints.config`. The function SHALL create a
`PostgresUnitOfWork` factory and pass it to the `Orchestrator`. It SHALL
construct the SSH infrastructure directly as a `MachineRepository` (instantiated
as `SSHMachineRepository`) plus three stateless collaborator instances
(`TaskDeployer`, `OutputDownloader`, `OccupancyChecker` from
`yascheduler.infra`) and pass the repository and the three collaborators to the
`Orchestrator`. The three collaborators SHALL be constructed without a `log`
argument — each binds its own module-local `YaLogger` via `get_logger("M-...")`
at module top.

`CloudProvisionerImpl` is constructed with `machine_repository` only — it no
longer takes any operations-side parameter or a `log` parameter.

The composition root SHALL NOT introduce a DB-facade class. Persistence is
accessed only via `PostgresUnitOfWork` and the repository ports
(`TaskRepository`, `NodeRepository`).

The composition root SHALL NOT use `typing.cast` to bridge between the domain
`CloudConfig` Protocol and the infra `ConfigCloud` Union.

The `make_daemon` function SHALL NOT accept a `log` parameter. The composition
root SHALL NOT create or thread a logger into collaborators; each collaborator
module binds its own logger via `get_logger("M-...")` at module top.

#### Scenario: Config imported from entrypoints

- **WHEN** `yascheduler.entrypoints.di` is inspected for its `Config` import
- **THEN** it imports `Config` from `yascheduler.entrypoints.config` (or `yascheduler.entrypoints`)

#### Scenario: No DB-facade import in the composition root

- **WHEN** `yascheduler.entrypoints.di` is imported
- **THEN** it does NOT import a `DB` facade, and no `DB`-like facade class is introduced; persistence is wired only via `PostgresUnitOfWork`

#### Scenario: Three collaborators constructed without log argument

- **WHEN** `make_daemon(config)` is called
- **THEN** exactly one instance each of `TaskDeployer()`, `OutputDownloader()`, `OccupancyChecker()` is constructed with no arguments; all three are passed to `Orchestrator(...)` as `task_deployer=`, `output_downloader=`, `occupancy_checker=` keyword arguments

#### Scenario: make_daemon does not accept a log parameter

- **WHEN** `make_daemon` is inspected for its signature
- **THEN** it is declared `async def make_daemon(config, *, clouds=None) -> Orchestrator` with no `log` parameter

### Requirement: make_daemon shares one SSHMachineRepository on the production path

On the `clouds is None` branch, `make_daemon` SHALL construct exactly one
`SSHMachineRepository` instance (constructed without a `log` argument) and
inject the SAME instance into both `CloudProvisionerImpl.machine_repository`
and `Orchestrator.repository`. This ensures a single connection registry spans
cloud setup and orchestrator runtime, so that connections opened during cloud
allocation are visible to the orchestrator and are reaped by
`Orchestrator.stop()` via `repository.disconnect_all()`.

`CloudProvisionerImpl` SHALL be constructed WITHOUT any operations-side
parameter AND WITHOUT a `log` parameter.

The pre-built-clouds (`clouds is not None`) branch SHALL continue to
construct a fresh `SSHMachineRepository` for the orchestrator while the
caller-supplied `clouds` retain whatever repository it was built with.

#### Scenario: clouds is None shares one repository instance

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** the `SSHMachineRepository` instance passed as `CloudProvisionerImpl.machine_repository` SHALL be the same object (`is`) as the instance passed as `Orchestrator.repository`

#### Scenario: CloudProvisionerImpl constructed without operations port or log

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `CloudProvisionerImpl(...)` SHALL be invoked with `machine_repository=` but WITHOUT any `machine_operations=` (or equivalent operations-side) keyword argument AND WITHOUT any `log=` keyword argument

#### Scenario: clouds is None constructs three collaborator instances

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `TaskDeployer()`, `OutputDownloader()`, and `OccupancyChecker()` SHALL each be invoked exactly once with no arguments; all three instances are passed to `Orchestrator(...)`

#### Scenario: pre-built clouds path keeps its own repository

- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the orchestrator SHALL be constructed with a `repository` that is a freshly-constructed `SSHMachineRepository` (without `log=`), NOT taken from `my_clouds`; the caller-supplied `clouds` instance SHALL be wired to the orchestrator unchanged

#### Scenario: cloud-allocation connections are visible to orchestrator

- **WHEN** a cloud node is allocated and connected via the shared repository
- **THEN** a subsequent orchestrator cycle SHALL observe `repository.contains(node.node_id) == True` for that node and SHALL NOT open a second connection

#### Scenario: cloud-allocation connections are reaped at shutdown

- **WHEN** `Orchestrator.stop()` runs after one or more cloud nodes have been allocated on the `clouds is None` path
- **THEN** `repository.disconnect_all()` SHALL close every connection opened during cloud allocation, leaving no cloud-setup SSH connection open at process exit
