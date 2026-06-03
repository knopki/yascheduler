## ADDED Requirements

### Requirement: CloudAPIManager becomes compatibility wrapper

The system SHALL refactor CloudAPIManager as a thin wrapper that delegates
to CloudProvisionerImpl.

#### Scenario: Old allocate call still works
- **WHEN** existing code calls cloud_manager.allocate(task_id, want_platforms=["linux"])
- **THEN** the call delegates to CloudProvisionerImpl.allocate()

#### Scenario: Old deallocate call still works
- **WHEN** existing code calls cloud_manager.deallocate("10.0.0.1")
- **THEN** the call delegates to CloudProvisionerImpl.deallocate()

### Requirement: CloudAPI becomes compatibility wrapper

The system SHALL refactor CloudAPI as a thin wrapper that delegates to
CloudProvisionerImpl for VM lifecycle operations.

#### Scenario: Old create_node call still works
- **WHEN** existing code calls cloud_api.create_node()
- **THEN** the call delegates to CloudProvisionerImpl

### Requirement: Old imports preserved

The system SHALL ensure imports from yascheduler.clouds still resolve during
the transition period.

#### Scenario: Import CloudAPIManager from old location
- **WHEN** from yascheduler.clouds import CloudAPIManager is executed
- **THEN** the import succeeds, returning the wrapper class
