## MODIFIED Requirements

### Requirement: UoW accepts existing DB config

The system SHALL construct a `PostgresUnitOfWork` from a `PostgresDbConfig`
config object, creating a fresh pg8000 connection on each context entry.

#### Scenario: UoW factory
- **WHEN** a factory `lambda: PostgresUnitOfWork(config)` is called
- **THEN** a new UoW is returned, ready to enter the context
