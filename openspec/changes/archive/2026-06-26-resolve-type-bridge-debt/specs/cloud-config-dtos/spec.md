## MODIFIED Requirements

### Requirement: Cloud config DTOs relocated to infra

The system SHALL define the cloud provider configuration DTOs
(`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
`ConfigCloudVastAI`, `AzureImageReference`) and the `ConfigCloud` Union alias in
`yascheduler/infra/cloud/cloud_configs.py` as `@dataclass(frozen=True)` stdlib
dataclasses with no `attrs` dependency and no INI-parsing methods
(`from_config_parser_section`, `get_valid_config_parser_fields`).

The 4 `ConfigCloud*` DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`,
`ConfigCloudUpcloud`, `ConfigCloudVastAI`) SHALL explicitly inherit the domain
`CloudConfig` Protocol from `yascheduler.domain` (`from yascheduler.domain
import CloudConfig`) as a runtime import. The Protocol field types declared in
`yascheduler/domain/ports.py` (`prefix: str`, `max_nodes: int`,
`idle_tolerance: int`, `username: str`, `jump_username: str | None`,
`jump_host: str | None`) SHALL match the DTO field types verbatim (no
override-invariance clash). The DTOs remain frozen stdlib dataclasses;
explicit Protocol inheritance is a typing aid that removes the writable-vs-frozen
mismatch that previously forced `cast("Sequence[CloudConfig]", ...)` bridges in
the composition root and parser. Structural matching continues to apply — a DTO
outside the inheritance tree still satisfies `CloudConfig` structurally (PEP
544); the explicit inheritance does not relax the structural contract.

`AzureImageReference.from_urn` SHALL be retained as a classmethod — it is a pure
URN string parser (`publisher:offer:sku:version`), not an INI parser, and does
not import `ConfigParser`/`SectionProxy`. `AzureImageReference` is not a
`CloudConfig` (it does not declare the 6 Protocol fields) and SHALL NOT
inherit `CloudConfig`.

The DTOs SHALL be importable via the `yascheduler.infra.cloud` subpackage
facade (`from yascheduler.infra.cloud import ConfigCloudAzure, ...`) and the
deep module path (`from yascheduler.infra.cloud.cloud_configs import ...`) is
for intra-package use only.

The field sets of all 4 `ConfigCloud*` DTOs and `AzureImageReference` SHALL be
preserved verbatim from the prior `config/cloud.py` definitions — no field
removals, no field renames, no type changes. Only the form (attrs frozen →
stdlib frozen dataclass), the parser-location change, and the addition of
explicit `CloudConfig` Protocol inheritance on the 4 `ConfigCloud*` DTOs.

The new `infra → domain` runtime edge (`from yascheduler.domain import
CloudConfig` in `infra/cloud/cloud_configs.py`) is permitted by the layers
contract (`pyproject.toml:125-131`: `entrypoints > infra > application >
domain > shared`); the layers contract already permits runtime `infra →
domain` edges (e.g. `infra/cloud/manager.py:30` imports
`CloudAllocateError`, `ConnectedMachine`, `Node` from `yascheduler.domain`).

#### Scenario: DTOs are stdlib frozen dataclasses
- **WHEN** any of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI`, `AzureImageReference` is introspected
- **THEN** it is a `@dataclass(frozen=True)` (stdlib `dataclasses`), has no
  `attrs`-defined fields, and raises on field assignment after construction

#### Scenario: DTOs explicitly inherit the CloudConfig Protocol
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`,
  `ConfigCloudUpcloud`, `ConfigCloudVastAI` is introspected via its `__mro__`
- **THEN** the domain `CloudConfig` Protocol (imported from
  `yascheduler.domain`, defined in `yascheduler/domain/ports.py`) appears in
  the class's method resolution order; the import in `cloud_configs.py` is a
  runtime import (not `TYPE_CHECKING`-only), because Python evaluates base
  classes at class definition time and a `TYPE_CHECKING`-only import would
  raise `NameError` on module load

#### Scenario: DTOs satisfy CloudConfig via isinstance at runtime
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
  (where `CloudConfig` is imported from `yascheduler.domain`)
- **THEN** it returns `True` (the DTO inherits the `@runtime_checkable`
  Protocol explicitly; `isinstance` on instances is permitted even though
  `issubclass(ConfigCloudAzure, CloudConfig)` would raise `TypeError` per the
  PEP 544 data-Protocol ban)

#### Scenario: AzureImageReference does not inherit CloudConfig
- **WHEN** `AzureImageReference.__mro__` is introspected
- **THEN** the domain `CloudConfig` Protocol does not appear
  (`AzureImageReference` declares `publisher`, `offer`, `sku`, `version`, not
  the 6 cloud-config fields)

#### Scenario: DTOs have no INI-parsing methods
- **WHEN** any `ConfigCloud*` DTO is introspected for `from_config_parser_section`
  or `get_valid_config_parser_fields`
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
- **WHEN** a consumer imports `from yascheduler.infra.cloud import
  ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud,
  ConfigCloudVastAI, AzureImageReference, ConfigCloud`
- **THEN** all six symbols resolve without ImportError

#### Scenario: ConfigCloud union covers all four providers
- **WHEN** the `ConfigCloud` Union alias is introspected
- **THEN** it is `Union[ConfigCloudAzure, ConfigCloudHetzner,
  ConfigCloudUpcloud, ConfigCloudVastAI]`

#### Scenario: Infra-to-domain edge permitted by layers contract
- **WHEN** `uv run lint-imports` is executed after `infra/cloud/cloud_configs.py`
  adds `from yascheduler.domain import CloudConfig`
- **THEN** the "Clean architecture layers" contract reports `KEPT` (the
  `infra → domain` runtime edge is permitted; `infra` is above `domain` in
  `pyproject.toml:125-131`)

#### Scenario: No circular import on package load
- **WHEN** `from yascheduler.infra.cloud.cloud_configs import ConfigCloudAzure`
  is executed in a fresh Python interpreter
- **THEN** the import succeeds without `ImportError`/`NameError` (the
  `domain/ports.py` module imports only stdlib `typing`; it does not import
  `infra`, so no cycle is introduced)