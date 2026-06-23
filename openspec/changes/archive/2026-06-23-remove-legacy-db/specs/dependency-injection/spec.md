## MODIFIED Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log:
Logger | None = None, *, clouds: CloudProvisionerImpl | None = None) ->
Orchestrator` factory function. The function SHALL create a
`PostgresUnitOfWork` factory and pass it to the `Orchestrator` instead of
a `DB` instance. It SHALL wire `SSHMachineGateway` directly — no
`RemoteMachineRepository`. It SHALL NOT import from `remote_machine/` or
`clouds/`.

The function SHALL NOT create a `DB` instance, SHALL NOT run schema
migration, and SHALL NOT accept a `db` parameter. Schema migration is the
operator's responsibility (run `yainit` before starting the daemon).

The function SHALL construct `CloudProvisionerImpl` without a `node_repo`
parameter — the adapter is a pure cloud-API client. The function SHALL
construct an `AllocationTracker`, an `asyncio.Lock` for allocation
serialization, and a filtered `active_clouds` list (clouds with
`max_nodes > 0` AND a successfully resolved adapter), passing all three
to the `Orchestrator` alongside the `clouds` instance.

The function SHALL NOT pass `adapters` or `configs` dicts to the
`Orchestrator` — provider selection is delegated to the
`clouds.select_provider` port method, and `adapters`/`configs` stay on
`CloudProvisionerImpl`.

The composition root SHALL NOT introduce a DB-facade class. Persistence is
accessed only via `PostgresUnitOfWork` and the repository ports
(`TaskRepository`, `NodeRepository`). No module in `yascheduler.di` SHALL
import from `yascheduler.db` (the module is removed).

#### Scenario: make_daemon returns orchestrator with UoW factory
- **WHEN** `make_daemon(config)` is called with a valid Config
- **THEN** returns an Orchestrator wired with `uow_factory`, `SSHMachineGateway`, `CloudProvisionerImpl`, `AllocationTracker`, `allocation_lock`, and `active_clouds` — without creating `DB`, without running schema migration, and without creating `RemoteMachineRepository`

#### Scenario: make_daemon accepts pre-built clouds
- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the provided `clouds` are wired to the orchestrator; no `DB` is created and no schema migration runs

#### Scenario: No DB-facade import in the composition root
- **WHEN** `di.py` is imported
- **THEN** it does NOT import `DB` from `yascheduler.db`, and no `DB`-like facade class is introduced; persistence is wired only via `PostgresUnitOfWork`