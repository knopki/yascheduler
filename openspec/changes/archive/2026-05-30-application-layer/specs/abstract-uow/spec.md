## ADDED Requirements

### Requirement: AbstractUnitOfWork Protocol

The system SHALL define an `AbstractUnitOfWork` Protocol in
`yascheduler.application.uow` with `tasks: TaskRepository`,
`nodes: NodeRepository`, `commit()`, `rollback()`, and async context manager
support.

#### Scenario: UoW provides repositories
- **WHEN** a use case enters `async with uow_factory() as uow`
- **THEN** `uow.tasks` is a `TaskRepository` and `uow.nodes` is a `NodeRepository`

#### Scenario: Commit persists changes
- **WHEN** `await uow.commit()` is called
- **THEN** all changes made through `uow.tasks` and `uow.nodes` are persisted

#### Scenario: Rollback on exception
- **WHEN** an exception occurs inside the `async with uow:` block
- **THEN** `rollback()` is called automatically

### Requirement: UoW is factory-injected

The system SHALL inject a UoW factory (`Callable[[], AbstractUnitOfWork]`)
into use cases rather than a pre-created UoW instance.

#### Scenario: Each use case gets a fresh UoW
- **WHEN** `allocate_task` is called twice with the same factory
- **THEN** each call creates a new UoW with a fresh connection and transaction
