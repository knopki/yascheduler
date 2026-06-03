## MODIFIED Requirements

### Requirement: PostgresUnitOfWork provides transactional boundaries

The system SHALL provide a `PostgresUnitOfWork` class that manages a shared
pg8000 Connection across `PostgresTaskRepository` and `PostgresNodeRepository`
with commit/rollback semantics, satisfying the `AbstractUnitOfWork` Protocol.

Accessing `tasks` or `nodes` properties, or calling `commit()`/`rollback()`
without entering the `async with` context SHALL raise
`UnitOfWorkNotInitializedError` from `yascheduler.adapters.persistence.exceptions`.

#### Scenario: Enter context creates connection and repositories
- **WHEN** `async with PostgresUnitOfWork(config) as uow`
- **THEN** `uow.tasks` is a `PostgresTaskRepository` and `uow.nodes` is a `PostgresNodeRepository`, both sharing the same connection

#### Scenario: Commit persists changes
- **WHEN** a task is saved via `uow.tasks.save(task)` then `await uow.commit()` is called
- **THEN** the task is committed and visible to other connections

#### Scenario: Exception triggers rollback
- **WHEN** an exception occurs inside the `async with` block
- **THEN** the transaction is rolled back before the connection is closed

#### Scenario: Normal exit without explicit commit
- **WHEN** the `async with` block completes without exception and without calling `commit()`
- **THEN** the transaction is not committed; changes are lost

#### Scenario: Accessing repositories outside context raises UnitOfWorkNotInitializedError
- **WHEN** `uow.tasks` or `uow.nodes` is accessed without entering the context
- **THEN** `UnitOfWorkNotInitializedError` is raised (not `RuntimeError`)

#### Scenario: Commit after context exit raises UnitOfWorkNotInitializedError
- **WHEN** `uow.commit()` is called after the `async with` block has exited
- **THEN** `UnitOfWorkNotInitializedError` is raised (not `RuntimeError`)
