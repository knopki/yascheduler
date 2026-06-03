## ADDED Requirements

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
TO_DO task to a free machine or requests cloud provisioning.

#### Scenario: Allocate to free machine
- **WHEN** `allocate_task(task_id, uow_factory, machine_gateway, engine, cloud)` is called and a free compatible machine exists
- **THEN** the task is saved with status RUNNING and `allocated_ip` set to the machine's IP

#### Scenario: No free machine — request cloud
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** `cloud.allocate(engine.platforms)` is called and `NoCompatibleNodeError` is NOT raised

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and marks the task DONE.

#### Scenario: Successful consumption
- **WHEN** `consume_task(task, machine_gateway, uow_factory)` is called on a completed task
- **THEN** output files are downloaded, the task status becomes DONE, and
  remote directory is cleaned

#### Scenario: Download failure
- **WHEN** output file download fails
- **THEN** the task is marked DONE with error in `TaskContext.error`

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes and triggers VM deletion.

#### Scenario: Idle cloud node deallocated
- **WHEN** `deallocate_nodes(uow_factory, cloud, config)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled in DB and cloud VM is deleted

#### Scenario: Non-cloud node skipped
- **WHEN** a non-cloud node is idle
- **THEN** it is not passed to the cloud provisioner for deletion

### Requirement: Use cases importable from application

The system SHALL expose all use cases from `yascheduler.application`.

#### Scenario: Import use case
- **WHEN** `from yascheduler.application.submit_task import submit_task` is executed
- **THEN** the function is available
