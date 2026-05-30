# Client Refactor

## Purpose

Refactor the Yascheduler client to delegate to application-layer use cases
via dependency injection, removing the direct Scheduler import.

## Requirements

### Requirement: Yascheduler delegates to use cases via DI

The system SHALL refactor `Yascheduler` to use use cases obtained from
`make_cli_deps()` instead of importing `Scheduler`.

#### Scenario: queue_submit_task_async uses SubmitTask use case
- **WHEN** `yascheduler.queue_submit_task_async(label, metadata, engine_name)` is called
- **THEN** the `submit_task` use case is called via DI, NOT via `Scheduler.create()`

#### Scenario: queue_submit_task still returns task_id
- **WHEN** `yascheduler.queue_submit_task(label, metadata, engine_name)` is called synchronously
- **THEN** returns the task_id (same public API as before)

### Requirement: No import of scheduler.py from client.py

The system SHALL remove the import `from .scheduler import Scheduler` from
`client.py`.

#### Scenario: client.py has no scheduler import
- **WHEN** `import yascheduler.client` is executed
- **THEN** `yascheduler.scheduler` is NOT imported as a side effect

### Requirement: Yascheduler public API preserved

The system SHALL preserve all public methods and attributes of `Yascheduler`:
`queue_submit_task`, `queue_submit_task_async`, `queue_get_tasks`,
`queue_get_tasks_async`, `queue_get_task`, `queue_get_task_async`,
`STATUS_TO_DO`, `STATUS_RUNNING`, `STATUS_DONE`.

#### Scenario: Existing AiiDA plugin still works
- **WHEN** AiiDA plugin calls `Yascheduler(config_path).queue_submit_task(...)`
- **THEN** the call succeeds with identical behavior
