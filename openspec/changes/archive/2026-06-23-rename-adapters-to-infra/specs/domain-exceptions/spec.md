## MODIFIED Requirements

### Requirement: CloudError is not re-exported from yascheduler.infra.cloud

The system SHALL NOT export `CloudError` from `yascheduler.infra.cloud`;
the new root remains accessible only via `yascheduler.domain`. The adapter
module's existing re-exports (`CloudAllocateError`, `CloudSetupError`) are
unchanged.

#### Scenario: infra.cloud does not re-export CloudError

- **WHEN** a module attempts `from yascheduler.infra.cloud import CloudError`
- **THEN** the import raises `ImportError`

#### Scenario: infra.cloud still re-exports the leaf cloud exceptions

- **WHEN** a module imports `from yascheduler.infra.cloud import CloudAllocateError, CloudSetupError`
- **THEN** both classes are available
