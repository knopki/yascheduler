## ADDED Requirements

### Requirement: CloudProvisionerImpl implements CloudProvisioner

The system SHALL provide a CloudProvisionerImpl class that satisfies the
CloudProvisioner Protocol with async methods: allocate, deallocate, capacity.

#### Scenario: Allocate node on best provider
- **WHEN** allocate(["linux"]) is called and two providers support Linux
- **THEN** a VM is created on the provider with highest priority and available capacity

#### Scenario: Allocate returns Node
- **WHEN** a VM is successfully provisioned and set up
- **THEN** returns a Node domain object with ip, ncpus, cloud, enabled=True

#### Scenario: Deallocate removes VM and DB record
- **WHEN** deallocate("10.0.0.1") is called for a cloud node
- **THEN** the VM is deleted via provider SDK and the node is removed from DB

#### Scenario: Capacity reports available nodes
- **WHEN** capacity() is called with 2 providers at 50% utilization
- **THEN** returns a dict mapping provider names to available node counts

### Requirement: Provider selection by priority and capacity

The system SHALL select the best available cloud provider based on
configurable priority and current capacity.

#### Scenario: Higher priority wins
- **WHEN** provider A has priority=100 and provider B has priority=50
- **THEN** provider A is selected if it has capacity

#### Scenario: Full provider skipped
- **WHEN** a provider has reached max_nodes
- **THEN** it is excluded from selection

### Requirement: Node setup after provisioning

The system SHALL run cloud-init status check and engine setup after a VM is
created, before returning the Node.

#### Scenario: Cloud-init must complete
- **WHEN** a VM is created
- **THEN** cloud-init status --wait is executed before setup

#### Scenario: Engine packages installed
- **WHEN** node setup runs on a fresh VM
- **THEN** required packages for configured engines are installed

### Requirement: Concurrent allocation throttling

The system SHALL prevent duplicate allocation requests for the same task
while a provisioning operation is in-flight.

#### Scenario: Duplicate request ignored
- **WHEN** allocate() is called for task_id=42 while task 42 is already provisioning
- **THEN** the second call returns immediately without creating a second VM
