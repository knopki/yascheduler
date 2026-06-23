## MODIFIED Requirements

### Requirement: PostgresUnitOfWork provides transactional boundaries

The system SHALL provide a `PostgresUnitOfWork` class that manages a shared
pg8000 Connection across `PostgresTaskRepository` and `PostgresNodeRepository`
with commit/rollback semantics, satisfying the `AbstractUnitOfWork` Protocol.

Accessing `tasks` or `nodes` properties, or calling `commit()`/`rollback()`
without entering the `async with` context SHALL raise
`UnitOfWorkNotInitializedError` from `yascheduler.infra.persistence.exceptions`.

#### Scenario: Enter context creates connection and repositories
- **WHEN** `async with PostgresUnitOfWork(config) as uow`
- **THEN** `uow.tasks` is a `PostgresTaskRepository` and `uow.nodes` is a `PostgresNodeRepository`, both sharing the same connection
