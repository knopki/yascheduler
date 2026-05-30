# postgres-uow

## Purpose

Unit of Work implementation for PostgreSQL using pg8000 — manages transaction boundaries and connection lifecycle.

## Requirements

### Requirement: PostgresUnitOfWork provides transactional boundaries

The system SHALL provide a `PostgresUnitOfWork` class that manages a shared
pg8000 Connection across `PostgresTaskRepository` and `PostgresNodeRepository`
with commit/rollback semantics.

> Note: An `AbstractUnitOfWork` Protocol is planned for the application-layer
> change. Until then, `PostgresUnitOfWork` operates as a standalone class.

#### Scenario: Enter context creates connection and repositories
- **WHEN** `async with PostgresUnitOfWork(config) as uow`
- **THEN** `uow.tasks` is a `PostgresTaskRepository` and `uow.nodes` is a `PostgresNodeRepository`, both sharing the same connection

#### Scenario: Commit persists changes
- **WHEN** a task is saved via `uow.tasks.save(task)` then `uow.commit()` is called
- **THEN** the task is committed and visible to other connections

#### Scenario: Exception triggers rollback
- **WHEN** an exception occurs inside the `async with` block
- **THEN** the transaction is rolled back before the connection is closed

#### Scenario: Normal exit commits
- **WHEN** the `async with` block completes without exception
- **THEN** the transaction is committed (or left to commit explicitly)

### Requirement: UoW accepts existing DB config

The system SHALL construct a `PostgresUnitOfWork` from a `ConfigDb` config
object, creating a fresh pg8000 connection on each context entry.

#### Scenario: UoW factory
- **WHEN** a factory `lambda: PostgresUnitOfWork(config)` is called
- **THEN** a new UoW is returned, ready to enter the context

### Requirement: Connection is closed after context exit

The system SHALL close the pg8000 connection when the UoW context exits,
regardless of success or failure.

#### Scenario: Connection closed after use
- **WHEN** `async with uow: ...` completes
- **THEN** the underlying pg8000 connection is closed
