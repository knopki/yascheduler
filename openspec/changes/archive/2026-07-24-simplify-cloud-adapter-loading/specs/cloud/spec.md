## MODIFIED Requirements

### Requirement: Provider VM lifecycle modules

The system SHALL provide provider-specific VM lifecycle modules. Provider modules
SHALL import their config DTOs (`ConfigCloudAzure`, etc., `AzureImageReference`)
from `yascheduler.infra.cloud` (the subpackage facade), NOT via deep paths.

Optional provider SDKs SHALL be handled gracefully: the system SHALL skip
providers whose SDK is not installed, logging a warning instead of raising
`ImportError`.

`CloudInitConfig.render()` SHALL output a `"#cloud-config\n"`-prefixed JSON
serialization of all fields.

**Change notes**: The graceful-skip mechanism is now centralized in the adapter
resolution layer. Provider modules no longer carry `_*_AVAILABLE` flags or inline
`ImportError` guards. The import-path constraint (config DTOs from the subpackage
facade) is pre-existing and carried forward unchanged. Behavior is unchanged.

#### Scenario: CloudInitConfig render output

- **WHEN** `CloudInitConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the output is `"#cloud-config\n"`-prefixed JSON serialization of all fields

#### Scenario: Missing SDK skips provider gracefully

- **WHEN** a provider's SDK is not installed
- **THEN** the system skips that provider, logs a warning, and continues without crashing
