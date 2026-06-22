# Allocation Tracker

## Purpose

Tracks in-flight cloud allocations to prevent duplicate provisioning requests for the same task.

## Requirements

### Requirement: AllocationTracker tracks in-flight cloud allocations

The system SHALL provide an `AllocationTracker` class in
`yascheduler.application.allocation_tracker` that maintains an in-memory
`set[int]` of task_ids with in-flight cloud allocations. The class SHALL
expose `add(task_id: int) -> bool` (returns True if newly added, False if
already tracked), `discard(task_id: int) -> None`, and `__contains__(task_id:
int) -> bool`.

The tracker SHALL be constructed once by the orchestrator and injected into
the `allocate_task` and `consume_task` use cases. It replaces the
`on_tasks` set and `mark_task_done` method previously on
`CloudProvisionerImpl`.

#### Scenario: Add new task to tracker
- **WHEN** `tracker.add(42)` is called for an untracked task_id
- **THEN** returns True and 42 is in `tracker`

#### Scenario: Add duplicate task to tracker
- **WHEN** `tracker.add(42)` is called while 42 is already tracked
- **THEN** returns False and the set is unchanged

#### Scenario: Discard tracked task
- **WHEN** `tracker.discard(42)` is called after a successful allocation or completion
- **THEN** 42 is no longer in `tracker`

#### Scenario: Discard untracked task is a no-op
- **WHEN** `tracker.discard(99)` is called for a task not in the tracker
- **THEN** no error is raised and the set is unchanged

#### Scenario: Containment check
- **WHEN** `42 in tracker` is evaluated
- **THEN** returns True if 42 is tracked, False otherwise
