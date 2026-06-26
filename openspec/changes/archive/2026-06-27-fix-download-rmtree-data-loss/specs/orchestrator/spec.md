## MODIFIED Requirements

### Requirement: Consume loop

The system SHALL poll RUNNING tasks via UoW and dispatch to the `consume_task`
use case when the remote machine reports completion. Queue messages SHALL
carry domain `Task` objects. SSH operations SHALL use `MachineGateway`.

The orchestrator SHALL maintain an in-process `set[int]` of in-flight consume
task ids (`self._consuming`). The consume producer SHALL skip yielding a task
whose id is in `self._consuming`. The consume consumer SHALL add the task id to
`self._consuming` before awaiting `consume_task` and remove it in a `finally`
block. Because both producer and consumer run in the same event loop, the
check/add/remove are atomic (no `await` between check and add).

The orchestrator SHALL treat the `consume_task` return value as a
finalisation signal: when `consume_task` returns `True` (finalised — task is
DONE, remote directory cleaned), the orchestrator SHALL discard the ip from
`self._occupancy_started`; when `consume_task` returns `False` (deferred —
task stays RUNNING for retry, remote directory preserved), the orchestrator
SHALL NOT discard the ip from `self._occupancy_started` so the next producer
cycle re-enters the consume block for the same task.

#### Scenario: Completed task consumed and finalised
- **WHEN** a RUNNING task's machine reports `state=FREE` and `consume_task` returns `True`
- **THEN** `consume_task` is called with `task_id` to download outputs, the task is finalised (DONE), and the orchestrator discards the ip from `_occupancy_started`

#### Scenario: Transient download failure defers and retries
- **WHEN** a RUNNING task's machine reports `state=FREE` and `consume_task` returns `False` (transient-only download errors)
- **THEN** the orchestrator does NOT discard the ip from `_occupancy_started`, the task stays RUNNING, and the next consume producer cycle re-yields the task for retry

#### Scenario: In-flight consume guard prevents concurrent consume
- **WHEN** a task is in-flight in `consume_task` (its id is in `self._consuming`) and the next producer cycle reads RUNNING tasks
- **THEN** the producer skips yielding the in-flight task id, preventing two workers from concurrently consuming the same task

#### Scenario: In-flight guard released after consume completes
- **WHEN** `consume_task` returns (either `True` or `False`)
- **THEN** the consumer's `finally` block removes the task id from `self._consuming`, allowing a future producer cycle to yield the task again if it is still RUNNING