## ADDED Requirements

### Requirement: Message bus dispatches events to handlers

The system SHALL provide a `handle(event: Event)` async function that
dispatches an event to all registered handlers for its type.

#### Scenario: Single event dispatched to matching handler
- **WHEN** `handle(TaskCreated(...))` is called and a handler is registered for `TaskCreated`
- **THEN** the handler is called with the event

#### Scenario: Event with no handlers is silently ignored
- **WHEN** `handle(TaskCreated(...))` is called and no handler is registered for `TaskCreated`
- **THEN** no error is raised

### Requirement: Handler registration

The system SHALL support registering handlers for event types via a
`HANDLERS: dict[type, list[Callable]]` mapping.

#### Scenario: Multiple handlers for one event
- **WHEN** two handlers are registered for `TaskCompleted`
- **THEN** both are called when a `TaskCompleted` event is dispatched

#### Scenario: Handler registration at startup
- **WHEN** DI factory wires the message bus
- **THEN** `HANDLERS[TaskCreated].append(webhook_handler)` registers the handler

### Requirement: Dispatch after commit

The system SHALL dispatch events in `PostgresUnitOfWork.commit()` after the
database transaction is committed.

#### Scenario: Events dispatched after commit
- **WHEN** `uow.commit()` is called and events were collected
- **THEN** the database commit completes first, then events are dispatched

#### Scenario: Rollback discards events
- **WHEN** an exception triggers `uow.rollback()`
- **THEN** collected events are discarded without dispatch

### Requirement: UoW collects events

The system SHALL extend `AbstractUnitOfWork` with an `events: list[Event]`
attribute where use cases append events during a transaction.

#### Scenario: Use case records event
- **WHEN** a use case does `uow.events.append(TaskAllocated(...))`
- **THEN** the event is collected and dispatched on commit

### Requirement: Message bus importable from application

The system SHALL expose the message bus from `yascheduler.application.message_bus`.

#### Scenario: Import message bus
- **WHEN** `from yascheduler.application.message_bus import handle, HANDLERS` is executed
- **THEN** both are available
