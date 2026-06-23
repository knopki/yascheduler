# uow-not-initialized-error

## Purpose

Exception class for accessing `PostgresUnitOfWork` API without entering the `async with` context. Inherits from `RuntimeError` for backward compatibility.

## Requirements

### Requirement: UnitOfWorkNotInitializedError exception class

The system SHALL provide a `UnitOfWorkNotInitializedError` exception class in
`yascheduler.infra.persistence.exceptions` that inherits from `RuntimeError`.
It SHALL be raised when `PostgresUnitOfWork` API methods are called without
entering the `async with` context.

#### Scenario: Accessing tasks property without entering context
- **WHEN** `uow.tasks` is accessed on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Accessing nodes property without entering context
- **WHEN** `uow.nodes` is accessed on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Calling commit without entering context
- **WHEN** `uow.commit()` is called on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Calling rollback without entering context
- **WHEN** `uow.rollback()` is called on a `PostgresUnitOfWork` that was not entered via `async with`
- **THEN** `UnitOfWorkNotInitializedError` is raised

#### Scenario: Backward compatibility with RuntimeError catch
- **WHEN** `UnitOfWorkNotInitializedError` is raised
- **THEN** `isinstance(exc, RuntimeError)` returns `True`
