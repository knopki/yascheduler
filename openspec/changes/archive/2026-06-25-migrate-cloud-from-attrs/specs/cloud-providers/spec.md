## MODIFIED Requirements

### Requirement: Support modules relocated

The system SHALL move cloud support modules (adapters, protocols, utils)
to infra/cloud/ preserving their functionality.

#### Scenario: Cloud adapter registry accessible
- **WHEN** CloudAdapter is imported from yascheduler.infra.cloud.adapters
- **THEN** the class is available with the same API, backed by stdlib dataclasses

#### Scenario: CloudConfig render output stable across migration
- **WHEN** `CloudConfig.render()` is called on a frozen dataclass instance
- **THEN** the output is a `"#cloud-config\n"`-prefixed JSON serialization of all fields
- **AND** the output is byte-identical to the prior attrs-backed implementation