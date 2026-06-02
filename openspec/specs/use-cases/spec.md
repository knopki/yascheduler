# Use Cases

## Purpose

Application-layer use cases that orchestrate domain operations for task
submission, allocation, consumption, and node deallocation.

## Requirements

### Requirement: SubmitTask use case

The system SHALL provide a `submit_task` async function that creates a new
task in the database after validating the engine and inputs.

#### Scenario: Successful task submission
- **WHEN** `submit_task("my-job", ctx, "fleur", engines, uow_factory)` is called with valid inputs
- **THEN** a new Task is saved with status TO_DO and the task_id is returned

#### Scenario: Unsupported engine
- **WHEN** `submit_task(...)` is called with an engine_name not in the EngineRepository
- **THEN** `UnsupportedEngineError` is raised

#### Scenario: Missing input file
- **WHEN** `submit_task(...)` is called with context missing a required input file
- **THEN** `MissingInputFileError` is raised

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function
SHALL accept `task_id: int` and `uow_factory: Callable[[], AbstractUnitOfWork]`
instead of `TaskModel` and `DB`. It SHALL load the domain `Task` via UoW,
validate the engine against `EngineRepository`, and save state transitions
through domain lifecycle methods (`allocate_to`, `mark_running`).

#### Scenario: Allocate to free machine
- **WHEN** `allocate_task(task_id, engines, uow_factory, machine_gateway, cloud, webhook)` is called and a free compatible machine exists
- **THEN** the task is loaded via UoW, allocated via `task.allocate_to(ip)`, transitioned to RUNNING via `task.mark_running()`, saved via `uow.tasks.save()`, and committed

#### Scenario: No free machine — request cloud
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** `cloud.allocate(engine.platforms)` is called and the function returns False without modifying the task

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.fail("unsupported engine")`, saved, committed, and webhook is called

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and marks the task DONE. The function SHALL
accept `task_id: int` and `uow_factory: Callable[[], AbstractUnitOfWork]`
instead of `TaskModel` and `DB`. It SHALL load the domain `Task` via UoW,
download outputs, and mark done/error through `task.complete()` / `task.fail()`.

#### Scenario: Successful consumption
- **WHEN** `consume_task(task_id, machine, engines, uow_factory, local_tasks_dir, cloud, webhook)` is called on a completed task
- **THEN** the task is loaded via UoW, output files are downloaded, the task is transitioned via `task.complete()`, saved via `uow.tasks.save()`, committed, and remote directory is cleaned

#### Scenario: Download failure
- **WHEN** output file download fails
- **THEN** the task is transitioned via `task.fail(error_details)`, saved, committed, and webhook is called

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept
`uow_factory: Callable[[], AbstractUnitOfWork]` instead of `DB`. It SHALL
query nodes via `NodeRepository` and disable them through UoW.

#### Scenario: Idle cloud node disabled
- **WHEN** `deallocate_nodes(uow_factory, cloud, config_clouds, idle_machines)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(ip)` and committed; the IP is returned for orchestrator-level SSH cleanup

#### Scenario: Non-cloud node skipped
- **WHEN** a non-cloud node is idle
- **THEN** it is not disabled and not included in returned IPs

#### Scenario: Returns disabled node IPs
- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a list of disabled node IPs is returned for the orchestrator to handle SSH disconnect and cloud deallocation

### Requirement: Use cases importable from application

The system SHALL expose all use cases from `yascheduler.application`.

#### Scenario: Import use case
- **WHEN** `from yascheduler.application.submit_task import submit_task` is executed
- **THEN** the function is available
