# Orchestrator

## Purpose

Orchestrator class that manages concurrent producer-consumer loops for
connecting machines, allocating tasks, consuming results, and deallocating
idle cloud nodes.

## Requirements

### Requirement: Orchestrator manages producer-consumer loops

The system SHALL provide an `Orchestrator` class that runs 4 producer-consumer
loops. The `Orchestrator` SHALL accept `uow_factory: Callable[[], AbstractUnitOfWork]`
instead of `DB`. All producer queries SHALL use UoW. The `Orchestrator` SHALL
NOT depend on `M-DB`.

#### Scenario: Orchestrator starts all loops
- **WHEN** `await orchestrator.start()` is called
- **THEN** all 4 loops begin executing concurrently, using `uow_factory` for all persistence queries

#### Scenario: Graceful shutdown
- **WHEN** `await orchestrator.stop()` is called
- **THEN** all loops receive cancellation, pending queue items are drained, and connections are closed

### Requirement: Allocate loop

The system SHALL poll TO_DO tasks via UoW and dispatch to the `allocate_task`
use case with configured concurrency limits. The producer SHALL load domain
`Task` objects from `TaskRepository.list_by_status`.

#### Scenario: Task allocated in order
- **WHEN** multiple TO_DO tasks exist
- **THEN** tasks are allocated up to the configured `allocate_limit` concurrently

### Requirement: Consume loop

The system SHALL poll RUNNING tasks via UoW and dispatch to the `consume_task`
use case when the remote machine reports completion. Queue messages SHALL
carry domain `Task` objects.

#### Scenario: Completed task consumed
- **WHEN** a RUNNING task's machine reports `state=FREE`
- **THEN** `consume_task` is called with `task_id` to download outputs

### Requirement: Deallocate loop

The system SHALL identify idle cloud nodes via UoW, call `deallocate_nodes`
to disable them, then handle SSH disconnect and cloud deallocation for
returned IPs.

#### Scenario: Cloud node idle too long
- **WHEN** a cloud node has been free longer than `idle_tolerance` seconds
- **THEN** `deallocate_nodes` disables the node in DB and returns its IP for SSH cleanup and cloud deletion

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections.

#### Scenario: New node connected
- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established and the machine is registered

### Requirement: Stats logging

The system SHALL periodically log queue sizes, node counts, and task counts
at a configurable interval.

#### Scenario: Stats printed every N seconds
- **WHEN** the orchestrator is running
- **THEN** usage statistics are logged at the configured interval

### Requirement: Orchestrator concurrency limits

The system SHALL enforce configurable concurrency limits for each loop:
`conn_machine_limit`, `allocate_limit`, `consume_limit`, `deallocate_limit`.

#### Scenario: Allocation concurrency respected
- **WHEN** `allocate_limit=3` and 10 TO_DO tasks exist
- **THEN** at most 3 allocations proceed concurrently
