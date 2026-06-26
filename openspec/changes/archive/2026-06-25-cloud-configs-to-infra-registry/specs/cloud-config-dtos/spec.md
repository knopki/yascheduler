## ADDED Requirements

### Requirement: Cloud config DTOs relocated to infra

The system SHALL define the cloud provider configuration DTOs
(`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
`ConfigCloudVastAI`, `AzureImageReference`) and the `ConfigCloud` Union alias in
`yascheduler/infra/cloud/cloud_configs.py` as `@dataclass(frozen=True)` stdlib
dataclasses with no `attrs` dependency and no INI-parsing methods
(`from_config_parser_section`, `get_valid_config_parser_fields`).

`AzureImageReference.from_urn` SHALL be retained as a classmethod — it is a pure URN
string parser (`publisher:offer:sku:version`), not an INI parser, and does not
import `ConfigParser`/`SectionProxy`.

The DTOs SHALL be importable via the `yascheduler.infra.cloud` subpackage facade
(`from yascheduler.infra.cloud import ConfigCloudAzure, ...`) and the deep module path
(`from yascheduler.infra.cloud.cloud_configs import ...`) is for intra-package use
only.

The field sets of all 4 `ConfigCloud*` DTOs and `AzureImageReference` SHALL be
preserved verbatim from the prior `config/cloud.py` definitions — no field removals,
no field renames, no type changes. Only the form (attrs frozen → stdlib frozen
dataclass) and the parser-location change.

#### Scenario: DTOs are stdlib frozen dataclasses
- **WHEN** any of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI`, `AzureImageReference` is introspected
- **THEN** it is a `@dataclass(frozen=True)` (stdlib `dataclasses`), has no `attrs`-
  defined fields, and raises on field assignment after construction

#### Scenario: DTOs have no INI-parsing methods
- **WHEN** any `ConfigCloud*` DTO is introspected for `from_config_parser_section` or
  `get_valid_config_parser_fields`
- **THEN** neither attribute exists on the class (parsing is delegated to
  `entrypoints/config_parser.py`)

#### Scenario: AzureImageReference.from_urn retained
- **WHEN** `AzureImageReference.from_urn("Debian:debian-11-daily:11-backports-gen2:latest")`
  is called
- **THEN** an `AzureImageReference(publisher="Debian", offer="debian-11-daily",
  sku="11-backports-gen2", version="latest")` is returned

#### Scenario: AzureImageReference.from_urn rejects malformed URN
- **WHEN** `AzureImageReference.from_urn("bad-urn")` is called
- **THEN** `ValueError` is raised

#### Scenario: ConfigCloudAzure rejects username root via parser
- **WHEN** `parse_cloud_section(sec, "az")` parses an `[clouds]` section with
  `az_user = root`
- **THEN** the parser raises `ValueError("Root user is forbidden on Azure")`
  (the `_check_az_user` validator runs parser-side, not in `__post_init__`)

#### Scenario: DTOs importable from infra cloud facade
- **WHEN** a consumer imports `from yascheduler.infra.cloud import ConfigCloudAzure,
  ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference,
  ConfigCloud`
- **THEN** all six symbols resolve without ImportError

#### Scenario: ConfigCloud union covers all four providers
- **WHEN** the `ConfigCloud` Union alias is introspected
- **THEN** it is `Union[ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud,
  ConfigCloudVastAI]`