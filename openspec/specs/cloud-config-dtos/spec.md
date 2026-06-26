# Cloud Config DTOs

## Purpose

Cloud provider configuration DTOs (Azure, Hetzner, UpCloud, VastAI) and the ConfigCloud union as frozen stdlib dataclasses in `yascheduler/infra/cloud/cloud_configs.py`.

## Requirements

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

The 4 `ConfigCloud*` DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`,
`ConfigCloudUpcloud`, `ConfigCloudVastAI`) SHALL explicitly inherit the domain
`CloudConfig` Protocol from `yascheduler.domain` as a typing aid — this removes
the writable-vs-frozen mismatch that previously forced `cast` bridges in the
composition root (`entrypoints/di.py`) and parser
(`entrypoints/config_parser.py`). The inheritance is explicit (a runtime import
of `CloudConfig` in `cloud_configs.py`); structural matching (PEP 544) continues
to apply to any DTO declaring the 6 Protocol fields, with or without inheritance.
`AzureImageReference` SHALL NOT inherit `CloudConfig` (it does not declare the
6 Protocol fields). The `infra → domain` runtime edge this creates is permitted
by the layers contract (`infra` sits above `domain` in
`pyproject.toml`); `uv run lint-imports` reports `KEPT`. A runtime import
(not `TYPE_CHECKING`-only) is required because Python resolves base classes at
class definition time — a `TYPE_CHECKING`-only import of `CloudConfig` would
raise `NameError` on module load. No circular-import risk: `domain/ports.py`
imports only stdlib `typing`.

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

#### Scenario: DTOs explicitly inherit the CloudConfig Protocol
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI` is introspected via `__mro__`
- **THEN** the `CloudConfig` Protocol from `yascheduler.domain` appears in the MRO
  (the inheritance is explicit, not merely structural; `__mro__` introspection is
  used instead of `issubclass` because PEP 544 bans `issubclass` on data-Protocols
  with non-method members)

#### Scenario: DTOs satisfy CloudConfig via isinstance at runtime
- **WHEN** each `ConfigCloud*` DTO instance is checked with
  `isinstance(dto, CloudConfig)`
- **THEN** the check returns `True` (the Protocol is `@runtime_checkable` and the
  DTOs inherit it explicitly)

#### Scenario: AzureImageReference does not inherit CloudConfig
- **WHEN** `AzureImageReference.__mro__` is introspected
- **THEN** `CloudConfig` is NOT in the MRO (it does not declare the 6 Protocol
  fields)

#### Scenario: Infra-to-domain edge permitted by layers contract
- **WHEN** `uv run lint-imports` is executed after the runtime
  `from yascheduler.domain import CloudConfig` import is added to
  `infra/cloud/cloud_configs.py`
- **THEN** the "Clean architecture layers" contract reports `KEPT` (the
  `infra → domain` edge is permitted; an identical runtime edge already exists
  in `infra/cloud/manager.py:30`)

#### Scenario: No circular import on package load
- **WHEN** a fresh interpreter runs
  `python -c "from yascheduler.infra.cloud.cloud_configs import ConfigCloudAzure"`
- **THEN** the import succeeds without `NameError` or `ImportError` (the runtime
  `CloudConfig` import in `cloud_configs.py` resolves because
  `domain/ports.py` imports only stdlib `typing`)
