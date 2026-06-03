## ADDED Requirements

### Requirement: TaskStatus enum values
Tests SHALL verify that `TaskStatus.TO_DO == 0`, `TaskStatus.RUNNING == 1`, `TaskStatus.DONE == 2`, and that values are `int` subclasses.

#### Scenario: Enum values match expected integers
- **WHEN** `TaskStatus.TO_DO`, `TaskStatus.RUNNING`, `TaskStatus.DONE` are compared to 0, 1, 2
- **THEN** each equality check succeeds and `isinstance(TaskStatus.TO_DO, int)` is True

### Requirement: TaskModel construction and immutability
Tests SHALL verify that `TaskModel` accepts all fields, converts `status` via `TaskStatus` converter, is frozen (raises on attribute assignment), and produces deterministic hashes.

#### Scenario: TaskModel with all fields
- **WHEN** `TaskModel(task_id=1, label="test", ip="10.0.0.1", status=0, metadata={"k": "v"}, cloud="az")`
- **THEN** `task.status == TaskStatus.TO_DO` and all other fields match constructor args

#### Scenario: TaskModel is frozen
- **WHEN** attempting `task.label = "new"` on an existing TaskModel
- **THEN** `attrs.exceptions.FrozenInstanceError` is raised

#### Scenario: TaskModel hash is deterministic
- **WHEN** two TaskModels are constructed with identical fields
- **THEN** their hashes are equal

### Requirement: NodeModel construction and defaults
Tests SHALL verify that `NodeModel` provides defaults for `enabled`, `cloud`, `username`, `port`, and is frozen.

#### Scenario: NodeModel with minimal args
- **WHEN** `NodeModel(ip="10.0.0.1", ncpus=4)`
- **THEN** `enabled=True`, `cloud=None`, `username="root"`, `port=22`

#### Scenario: NodeModel with all args
- **WHEN** `NodeModel(ip="10.0.0.1", ncpus=4, enabled=False, cloud="hetzner", username="admin", port=2222)`
- **THEN** all fields match constructor args
