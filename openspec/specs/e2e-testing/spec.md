## Purpose

Define the end-to-end test tier: its boundary and its coverage
contract. End-to-end tests verify the full task lifecycle against real
PostgreSQL and a real SSH target.

## Requirements

### Requirement: End-to-end tier exercises the full lifecycle

The end-to-end test tier SHALL drive the complete scheduler lifecycle
through the real application entrypoints. The tier SHALL NOT bypass the
orchestrator, the persistence layer, the SSH layer, or the cloud
provisioner. Each test SHALL start on an empty database; the test suite
SHALL own per-test isolation.

#### Scenario: a submitted task completes the full lifecycle

- **WHEN** tasks are submitted and the daemon runs against a real PostgreSQL instance and a real SSH target
- **THEN** each task transitions to done, its output file is downloaded, and its error is empty
- **AND** the completed tasks spread across the available SSH nodes

### Requirement: End-to-end tier uses short-lived containers

The end-to-end test tier SHALL spin up its own short-lived PostgreSQL
container and SSH target container. The tier SHALL be independent of the
development sandbox and SHALL NOT touch production databases, production
SSH servers, or live cloud accounts.

#### Scenario: each test owns its containers

- **WHEN** an end-to-end test runs
- **THEN** it starts its own PostgreSQL and SSH containers and tears them down when the test ends

### Requirement: Optional live-cloud end-to-end test

The system SHALL support an optional end-to-end test that runs the full
lifecycle, including cloud provisioning and idle deallocation, against a
live cloud provider. The test SHALL stay off by default and SHALL run
only when cloud credentials are configured. When the credentials are
absent, the test SHALL be skipped and no cloud API call SHALL be made.

#### Scenario: live cloud provisioning and deallocation when configured

- **WHEN** cloud credentials are configured and tasks are submitted
- **THEN** a cloud node is provisioned, the tasks complete, the outputs are downloaded, and the idle node is deallocated
