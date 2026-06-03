## MODIFIED Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log: Logger | None = None, *, db: DB | None = None, clouds: CloudProvisionerImpl | None = None) -> Orchestrator`
factory function. The function SHALL create a `PostgresUnitOfWork` factory and
pass it to the `Orchestrator` instead of the `DB` instance. The `DB` instance
SHALL be retained for schema migration only.

#### Scenario: make_daemon returns orchestrator with UoW factory
- **WHEN** `make_daemon(config)` is called with a valid Config
- **THEN** returns an Orchestrator wired with `uow_factory`, machine gateway, and cloud provisioner — without storing `DB` in the orchestrator

#### Scenario: make_daemon accepts pre-built dependencies
- **WHEN** `make_daemon(config, db=my_db, clouds=my_clouds)` is called
- **THEN** the provided `db` is used for schema migration and the provided `clouds` are wired to the orchestrator
