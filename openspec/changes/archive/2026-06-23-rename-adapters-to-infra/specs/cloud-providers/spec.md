## MODIFIED Requirements

### Requirement: Provider code relocated

The system SHALL move provider-specific VM lifecycle code from clouds/ to
infra/cloud/providers/ preserving functionality.

#### Scenario: Azure provider accessible
- **WHEN** az_create_node is imported from infra.cloud.providers.az
- **THEN** the function is available and creates Azure VMs

#### Scenario: Hetzner provider accessible
- **WHEN** hetzner_create_node is imported from infra.cloud.providers.hetzner
- **THEN** the function is available and creates Hetzner servers

#### Scenario: UpCloud provider accessible
- **WHEN** upcloud_create_node_sync is imported from infra.cloud.providers.upcloud
- **THEN** the function is available and creates UpCloud servers

### Requirement: Support modules relocated

The system SHALL move cloud support modules (adapters, protocols, utils)
to infra/cloud/ preserving their functionality.

#### Scenario: Cloud adapter registry accessible
- **WHEN** CloudAdapter is imported from infra.cloud.adapters
- **THEN** the class is available with the same API
