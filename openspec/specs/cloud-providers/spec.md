## ADDED Requirements

### Requirement: Provider code relocated

The system SHALL move provider-specific VM lifecycle code from clouds/ to
adapters/cloud/providers/ preserving functionality.

#### Scenario: Azure provider accessible
- **WHEN** az_create_node is imported from adapters.cloud.providers.az
- **THEN** the function is available and creates Azure VMs

#### Scenario: Hetzner provider accessible
- **WHEN** hetzner_create_node is imported from adapters.cloud.providers.hetzner
- **THEN** the function is available and creates Hetzner servers

#### Scenario: UpCloud provider accessible
- **WHEN** upcloud_create_node_sync is imported from adapters.cloud.providers.upcloud
- **THEN** the function is available and creates UpCloud servers

### Requirement: Support modules relocated

The system SHALL move cloud support modules (adapters, protocols, utils)
to adapters/cloud/ preserving their functionality.

#### Scenario: Cloud adapter registry accessible
- **WHEN** CloudAdapter is imported from adapters.cloud.adapters
- **THEN** the class is available with the same API

### Requirement: Optional provider SDKs handled gracefully

The system SHALL skip providers whose SDK is not installed, logging a warning
instead of raising an ImportError.

#### Scenario: Azure SDK not installed
- **WHEN** the Azure provider is configured but azure-identity is not installed
- **THEN** a warning is logged and the provider is excluded from capacity
