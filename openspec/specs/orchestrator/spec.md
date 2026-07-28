# Orchestrator

## Purpose

Run four concurrent loops that connect machines, allocate tasks, consume
results, and deallocate idle cloud nodes. Each loop polls the database on a
tick, dispatches work within a configured concurrency limit, and survives
transient errors. The daemon starts all loops together and shuts them down
together.

## Requirements

### Requirement: Four concurrent loops

The system SHALL run four loops concurrently: connect, allocate, consume, and
deallocate. Each loop SHALL poll the database on a tick and SHALL dispatch at
most its configured number of items at the same time.

#### Scenario: the daemon lifecycle runs and tears down all loops

- **WHEN** the daemon starts and later stops
- **THEN** all four loops run together while the daemon is up, and on stop the in-flight items drain and all SSH connections close

### Requirement: Task CPU count resolution

The orchestrator SHALL use the stored CPU count of the allocated node when that
count is set, and SHALL discover the count from the remote machine at deploy
time when it is not set.

#### Scenario: stored CPU count is used

- **WHEN** the allocated node carries a stored CPU count
- **THEN** that count is used for the task deploy

#### Scenario: CPU count is discovered when unset

- **WHEN** the allocated node has no stored CPU count
- **THEN** the count is read from the remote machine and used for the deploy

### Requirement: Cloud capacity limits provisioning

The orchestrator SHALL compute available cloud capacity as the difference
between the maximum node count and the current node count across active clouds.
The allocator SHALL provision cloud nodes only up to the available capacity.

#### Scenario: capacity caps provisioning

- **WHEN** the current node count across active clouds equals the maximum node count
- **THEN** the allocator requests no new cloud node

### Requirement: Per-node occupancy and in-flight tracking

The orchestrator SHALL track per-node occupancy state across consume ticks and
SHALL start each allocated node's occupancy check exactly once. A task already
being consumed SHALL be skipped on later ticks until its consume attempt
completes.

#### Scenario: an in-flight task is skipped, then released

- **WHEN** a task is selected for consume while a consume for the same task is already in flight
- **THEN** the task is skipped, and when the in-flight consume completes the task becomes selectable again

### Requirement: Deallocate teardown without a database lookup

The deallocate loop SHALL tear down a disabled node from the data carried in the
queue, with no database round-trip lookup. A teardown failure SHALL be logged
and SHALL NOT stop the loop.

#### Scenario: a teardown failure is logged and the loop continues

- **WHEN** the teardown of a queued node raises an error
- **THEN** the error and the node identity are logged and the loop moves to the next queued node

### Requirement: Connect retry and grace window

A static node SHALL retry connection on every tick without limit. A cloud node
SHALL retry within its configured connect-grace window and SHALL be abandoned
past it. A successful connect SHALL clear the recorded failure age for the node.

#### Scenario: within-policy retry and success clears failure age

- **GIVEN** a node has recorded a connection failure
- **WHEN** the node connects on a later tick
- **THEN** the recorded failure age for that node is cleared

#### Scenario: a cloud node past grace is abandoned

- **GIVEN** a cloud node has failed connection for longer than its connect-grace window
- **WHEN** the connect loop evaluates the node
- **THEN** the node is abandoned

### Requirement: Loop error resilience

The orchestrator SHALL catch a transient error from any loop producer or
consumer, log it, and continue on the next tick. A cancellation SHALL propagate
to graceful shutdown.

#### Scenario: a transient error is logged and the loop continues

- **WHEN** a producer or consumer raises a transient error
- **THEN** the error is logged and the loop continues on the next tick

#### Scenario: cancellation triggers graceful shutdown

- **WHEN** a loop receives a cancellation during shutdown
- **THEN** the cancellation propagates to the shutdown drain path

### Requirement: Periodic stats logging

The orchestrator SHALL log queue sizes, node counts, and task counts at a
configurable interval. Missing or partial count data SHALL be tolerated, and a
stats error SHALL be logged without stopping the stats job.

#### Scenario: partial count data is tolerated

- **WHEN** a count source returns no data for a key
- **THEN** a zero is used and no error is raised

### Requirement: Graceful shutdown is idempotent and exception-safe

A stop request SHALL run the cleanup steps exactly once. A failure in one
cleanup step SHALL be logged and SHALL NOT skip the remaining steps.

#### Scenario: stop runs once and runs every step

- **WHEN** stop is called twice and a cleanup step raises an error
- **THEN** the cleanup runs exactly once, the second call does nothing, and the error is logged while the remaining steps still run

### Requirement: Free-machine selection

Free-machine selection SHALL consider only machines whose node is enabled in the
database and not busy with a running task. A single session failure SHALL be
isolated: the failed session SHALL be logged and the selection SHALL continue
with the remaining sessions. When no free session succeeds, the selection SHALL
report no match so the caller requests a cloud node.

#### Scenario: only an enabled, non-busy node is selectable

- **WHEN** the allocator selects a free machine
- **THEN** only machines whose node is enabled in the database and not busy with a running task are candidates

#### Scenario: one session fails and the cloud branch is reached

- **WHEN** one free session raises an error during selection and no other session succeeds
- **THEN** the error is logged and the selection reports no match
