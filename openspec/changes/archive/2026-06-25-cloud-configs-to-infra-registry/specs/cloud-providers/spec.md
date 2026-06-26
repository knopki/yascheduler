## MODIFIED Requirements

### Requirement: Provider code relocated

The system SHALL move provider-specific VM lifecycle code from clouds/ to
infra/cloud/providers/ preserving functionality. Provider modules
(`infra/cloud/providers/{az,hetzner,upcloud,vastai}.py`) SHALL import their config
DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
`ConfigCloudVastAI`, `AzureImageReference`) from `yascheduler.infra.cloud` (the
subpackage facade, R2-compliant), not from `yascheduler.config`. The DTOs are frozen
stdlib dataclasses (no attrs) with no INI-parsing methods; INI parsing is invoked via
the `CLOUD_CONFIG_PARSERS` registry from the composition root.

#### Scenario: Azure provider accessible
- **WHEN** az_create_node is imported from adapters.cloud.providers.az
- **THEN** the function is available and creates Azure VMs

#### Scenario: Hetzner provider accessible
- **WHEN** hetzner_create_node is imported from adapters.cloud.providers.hetzner
- **THEN** the function is available and creates Hetzner servers

#### Scenario: UpCloud provider accessible
- **WHEN** upcloud_create_node_sync is imported from adapters.cloud.providers.upcloud
- **THEN** the function is available and creates UpCloud servers

#### Scenario: Provider modules import config DTOs from infra cloud facade
- **WHEN** `infra/cloud/providers/az.py` is inspected for its `ConfigCloudAzure` /
  `AzureImageReference` import (TYPE_CHECKING)
- **THEN** the import is `from yascheduler.infra.cloud import ConfigCloudAzure,
  AzureImageReference` (R2 facade path), not `from yascheduler.config import ...` and
  not `from yascheduler.infra.cloud.cloud_configs import ...` (deep path, R2 violation)

#### Scenario: Provider config DTOs are frozen dataclasses
- **WHEN** a provider module's `cfg: ConfigCloudAzure` parameter is introspected
- **THEN** `ConfigCloudAzure` is a stdlib `@dataclass(frozen=True)` with no
  `from_config_parser_section` / `get_valid_config_parser_fields` methods