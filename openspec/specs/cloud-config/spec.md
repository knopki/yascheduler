# Cloud Config

## Purpose

Cloud configuration contract: the CloudConfig structural Protocol, the frozen stdlib dataclass DTOs (ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference) relocated to infra, the per-prefix parser registry, the per-prefix parser functions, and Config.from_config_parser delegation of cloud assembly.

## Requirements

### Requirement: CloudConfig structural Protocol

The system SHALL define a structural `@runtime_checkable` `CloudConfig` Protocol in
`yascheduler/domain/ports.py` capturing the 7-field surface that application-layer
consumers (`deallocate_nodes`, `orchestrator`) read from cloud provider configs:

- `prefix: str`
- `max_nodes: int`
- `idle_tolerance: int`
- `connect_grace: int`
- `username: str`
- `jump_username: str | None`
- `jump_host: str | None`

The Protocol is structural (a DTO outside the inheritance tree satisfies it
structurally per PEP 544). The concrete `ConfigCloud*` DTOs in
`infra/cloud/cloud_configs.py` SHALL **explicitly inherit** the Protocol as a
typing aid. Application-layer consumers SHALL type their `config_clouds` /
`active_clouds` parameters as `Sequence[CloudConfig]` (domain Protocol), not
`Sequence[ConfigCloud]` (infra Union), keeping `application → infra`
TYPE_CHECKING-only.

The Protocol SHALL be importable via the `yascheduler.domain` facade
(`from yascheduler.domain import CloudConfig`) and the deep path
(`from yascheduler.domain.ports import CloudConfig`).

The composition root (`entrypoints/di.py`) and parser
(`entrypoints/config_parser.py`) SHALL NOT contain any
`cast("Sequence[CloudConfig]"`, `cast("ConfigCloud"`, or
`cast("list[ConfigCloud]"` bridges. The composition root types
`Config.clouds` as `Sequence[ConfigCloud]` (the infra Union); application-side
feeds receive `Sequence[ConfigCloud]` values assignable to their
`Sequence[CloudConfig]` parameter types via covariance + the explicit
DTO→Protocol inheritance.

The `connect_grace` field SHALL declare per-provider defaults on each of the
four `ConfigCloud*` DTOs: `ConfigCloudHetzner.connect_grace = 60`,
`ConfigCloudUpcloud.connect_grace = 60`, `ConfigCloudAzure.connect_grace = 120`,
`ConfigCloudVastAI.connect_grace = 120`. The INI parser
(`entrypoints/config_parser.py`) SHALL NOT parse `connect_grace` from the INI
file — the DTO default is the sole source.

#### Scenario: CloudConfig Protocol is runtime_checkable
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
- **THEN** it returns `True` (the DTO inherits the Protocol explicitly; the Protocol is `@runtime_checkable`)

#### Scenario: All four ConfigCloud DTOs satisfy CloudConfig via isinstance
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI` is constructed with valid fields and checked with `isinstance(dto, CloudConfig)`
- **THEN** every check returns `True`

#### Scenario: All four ConfigCloud DTOs explicitly inherit CloudConfig
- **WHEN** each `ConfigCloud*` DTO's `__mro__` is introspected
- **THEN** the `CloudConfig` Protocol from `yascheduler.domain` appears in the MRO (the inheritance is explicit, not merely structural)

#### Scenario: deallocate_nodes types against CloudConfig
- **WHEN** `deallocate_nodes.py` is inspected for its `config_clouds` parameter type annotation
- **THEN** it is `Sequence[CloudConfig]` imported from `yascheduler.domain` (TYPE_CHECKING)

#### Scenario: orchestrator types config_clouds and active_clouds against CloudConfig
- **WHEN** `orchestrator.py` is inspected for the `config_clouds` and `active_clouds` constructor parameter type annotations
- **THEN** both are `Sequence[CloudConfig]` imported from `yascheduler.domain` (TYPE_CHECKING)

#### Scenario: CloudConfig importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: CloudConfig does not expose provider-specific fields
- **WHEN** the `CloudConfig` Protocol is introspected for provider-specific fields (`tenant_id`, `token`, `login`, `api_key`, `server_type`, `vm_size`, `disk_gb`, etc.)
- **THEN** none of these fields are declared on the Protocol (ISP: application never reads them)

#### Scenario: No cast bridges in composition root
- **WHEN** `entrypoints/di.py` is parsed with `ast` and walked for `Call` nodes whose function is the bare name `cast` or the attribute `typing.cast`, and for `ImportFrom` from `typing` binding the name `cast`
- **THEN** zero matches are found (comments and string literals, including `CHANGE_SUMMARY` lines that reference historical `cast(...)` tokens verbatim, are not visited by the AST walk)

#### Scenario: No cast bridges in config parser
- **WHEN** `entrypoints/config_parser.py` is inspected for `cast("Sequence[CloudConfig]"`
- **THEN** zero matches are found

#### Scenario: Config.clouds typed as the infra ConfigCloud Union
- **WHEN** `yascheduler/entrypoints/config.py` is inspected for the `clouds` field annotation on the `Config` dataclass
- **THEN** the annotation is `Sequence[ConfigCloud]` (not `Sequence[CloudConfig]`), with `ConfigCloud` imported `TYPE_CHECKING`-only from `yascheduler.infra.cloud.cloud_configs`

#### Scenario: connect_grace declared on the CloudConfig Protocol
- **WHEN** the `CloudConfig` Protocol in `yascheduler/domain/ports.py` is introspected for the `connect_grace` attribute
- **THEN** a `connect_grace: int` field is declared on the Protocol

#### Scenario: connect_grace defaults on all four DTOs
- **WHEN** each of `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudAzure`, `ConfigCloudVastAI` is constructed without an explicit `connect_grace` argument
- **THEN** the resulting instance has `connect_grace == 60` for Hetzner and Upcloud, and `connect_grace == 120` for Azure and VastAI

#### Scenario: connect_grace is not parsed from INI
- **WHEN** `entrypoints/config_parser.py` is inspected for any `connect_grace` token
- **THEN** zero matches are found (the DTO default is the sole source)

### Requirement: Cloud config parser registry

The system SHALL define a `CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]]` registry in `yascheduler/entrypoints/config_parser.py` mapping each cloud provider prefix (`az`, `hetzner`, `upcloud`, `vastai`) to its parser function.

The registry lives at the composition-root layer (`entrypoints`) so the `infra → entrypoints` dependency direction stays R3-legal (the registry references parser functions, which are composition-root concerns; the DTOs live in `infra/cloud/cloud_configs.py`).

Adding a new cloud provider SHALL require only:
1. Defining a frozen dataclass DTO in `infra/cloud/cloud_configs.py`.
2. Defining a parser function in `entrypoints/config_parser.py`.
3. Registering one entry in `CLOUD_CONFIG_PARSERS`.

No edit to `Config.from_config_parser` (the aggregate root) SHALL be required to add a provider — the registry is the open/closed seam.

#### Scenario: Registry maps all four provider prefixes
- **WHEN** `CLOUD_CONFIG_PARSERS` is inspected
- **THEN** it contains exactly the keys `az`, `hetzner`, `upcloud`, `vastai` mapped to callable parser functions

#### Scenario: Adding a provider does not touch the aggregate root
- **WHEN** a contributor adds a new provider `foo` by adding a `ConfigCloudFoo` DTO, a `_parse_foo_section` parser, and a `"foo": _parse_foo_section` registry entry
- **THEN** no edit to `Config.from_config_parser` is required; the new provider's `[cloud.foo]` sections round-trip into `Config.clouds` via registry iteration

### Requirement: Cloud section parser functions

The system SHALL define `parse_cloud_section(sec: SectionProxy, prefix: str) -> CloudConfig` and `parse_clouds(cfg: ConfigParser, remote: RemoteDefaults) -> list[CloudConfig]` in `yascheduler/entrypoints/config_parser.py`.

`parse_clouds` SHALL:
1. Derive `cloud_prefixes` from `[clouds]` section options (splitting each option name on `_` and taking the first segment).
2. Inherit `remote.username` into `[clouds]` for any prefix whose `{prefix}_user` key is absent.
3. For each prefix present in `cloud_prefixes`, dispatch to `CLOUD_CONFIG_PARSERS[prefix](cfg["clouds"])` to build the DTO.
4. Return the list of constructed DTOs.

`parse_cloud_section` SHALL dispatch to `CLOUD_CONFIG_PARSERS[prefix]` and return the parsed DTO. Unknown prefixes raise `KeyError` (the registry is the source of truth for supported providers).

Validation (`warn_unknown_fields`, `validators.ge(0)`, `validators.ge(1)`, `_check_az_user`, `opt_str_val`) SHALL run inside the per-prefix parser functions before constructing the DTO — not in dataclass `__post_init__`.

The per-prefix parser functions (`_parse_azure_section`, `_parse_hetzner_section`, `_parse_upcloud_section`, `_parse_vastai_section`) and the `cloud_valid_fields(prefix)` helper SHALL live in `entrypoints/config_parser.py`.

#### Scenario: parse_clouds dispatches via registry
- **WHEN** `parse_clouds(cfg, remote)` is called with a config parser whose `[clouds]` section contains `az_*`, `hetzner_*`, and `vastai_*` keys
- **THEN** `CLOUD_CONFIG_PARSERS["az"]`, `CLOUD_CONFIG_PARSERS["hetzner"]`, and `CLOUD_CONFIG_PARSERS["vastai"]` are each called once; the returned list contains one `ConfigCloudAzure`, one `ConfigCloudHetzner`, and one `ConfigCloudVastAI` (in registry-iteration order)

#### Scenario: parse_clouds inherits remote username
- **WHEN** `parse_clouds(cfg, remote)` is called and `[clouds]` lacks `hetzner_user` but `remote.username == "root"`
- **THEN** the parser reads `hetzner_user = "root"` (inherited) when constructing `ConfigCloudHetzner`

#### Scenario: parse_cloud_section raises on unknown prefix
- **WHEN** `parse_cloud_section(sec, "unknown")` is called
- **THEN** `KeyError` is raised (the registry has no entry for `unknown`)

#### Scenario: warn_unknown_fields runs parser-side
- **WHEN** `parse_clouds(cfg, remote)` is called with an `[clouds]` section containing an unknown key `az_bogus_key`
- **THEN** `warn_unknown_fields` emits a `ConfigWarning` from inside the parser, not from a `__post_init__` on the DTO

#### Scenario: VastAI section round-trips via registry
- **WHEN** `parse_clouds(cfg, remote)` is called with a config parser whose `[clouds]` section contains `vastai_*` keys
- **THEN** the returned list contains a `ConfigCloudVastAI` instance with `prefix == "vastai"`

### Requirement: Cloud config DTOs

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
(`from yascheduler.infra.cloud import ConfigCloudAzure, ...`); the deep module path
(`from yascheduler.infra.cloud.cloud_configs import ...`) is for intra-package use
only.

The 4 `ConfigCloud*` DTOs SHALL explicitly inherit the domain `CloudConfig`
Protocol from `yascheduler.domain` as a typing aid. The inheritance is explicit (a
runtime import of `CloudConfig` in `cloud_configs.py`); structural matching
(PEP 544) continues to apply to any DTO declaring the 7 Protocol fields, with or
without inheritance. `AzureImageReference` SHALL NOT inherit `CloudConfig` (it does
not declare the Protocol fields). The `infra → domain` runtime edge this creates is
permitted by the layers contract (`infra` sits above `domain`); a runtime import
(not `TYPE_CHECKING`-only) is required because Python resolves base classes at class
definition time. No circular-import risk: `domain/ports.py` imports only stdlib
`typing`.

#### Scenario: DTOs are stdlib frozen dataclasses
- **WHEN** any of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`, `AzureImageReference` is introspected
- **THEN** it is a `@dataclass(frozen=True)` (stdlib `dataclasses`), has no `attrs`-defined fields, and raises on field assignment after construction

#### Scenario: DTOs have no INI-parsing methods
- **WHEN** any `ConfigCloud*` DTO is introspected for `from_config_parser_section` or `get_valid_config_parser_fields`
- **THEN** neither attribute exists on the class (parsing is delegated to `entrypoints/config_parser.py`)

#### Scenario: AzureImageReference.from_urn retained
- **WHEN** `AzureImageReference.from_urn("Debian:debian-11-daily:11-backports-gen2:latest")` is called
- **THEN** an `AzureImageReference(publisher="Debian", offer="debian-11-daily", sku="11-backports-gen2", version="latest")` is returned

#### Scenario: AzureImageReference.from_urn rejects malformed URN
- **WHEN** `AzureImageReference.from_urn("bad-urn")` is called
- **THEN** `ValueError` is raised

#### Scenario: ConfigCloudAzure rejects username root via parser
- **WHEN** `parse_cloud_section(sec, "az")` parses an `[clouds]` section with `az_user = root`
- **THEN** the parser raises `ValueError("Root user is forbidden on Azure")` (the `_check_az_user` validator runs parser-side, not in `__post_init__`)

#### Scenario: DTOs importable from infra cloud facade
- **WHEN** a consumer imports `from yascheduler.infra.cloud import ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference, ConfigCloud`
- **THEN** all six symbols resolve without ImportError

#### Scenario: ConfigCloud union covers all four providers
- **WHEN** the `ConfigCloud` Union alias is introspected
- **THEN** it is `Union[ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI]`

#### Scenario: DTOs explicitly inherit the CloudConfig Protocol
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI` is introspected via `__mro__`
- **THEN** the `CloudConfig` Protocol from `yascheduler.domain` appears in the MRO (the inheritance is explicit; `__mro__` introspection is used instead of `issubclass` because PEP 544 bans `issubclass` on data-Protocols with non-method members)

#### Scenario: DTOs satisfy CloudConfig via isinstance at runtime
- **WHEN** each `ConfigCloud*` DTO instance is checked with `isinstance(dto, CloudConfig)`
- **THEN** the check returns `True` (the Protocol is `@runtime_checkable` and the DTOs inherit it explicitly)

#### Scenario: AzureImageReference does not inherit CloudConfig
- **WHEN** `AzureImageReference.__mro__` is introspected
- **THEN** `CloudConfig` is NOT in the MRO (it does not declare the Protocol fields)

#### Scenario: Infra-to-domain edge permitted by layers contract
- **WHEN** `uv run lint-imports` is executed after the runtime `from yascheduler.domain import CloudConfig` import is added to `infra/cloud/cloud_configs.py`
- **THEN** the "Clean architecture layers" contract reports `KEPT`

#### Scenario: No circular import on package load
- **WHEN** a fresh interpreter runs `python -c "from yascheduler.infra.cloud.cloud_configs import ConfigCloudAzure"`
- **THEN** the import succeeds without `NameError` or `ImportError`

### Requirement: Per-provider package_upgrade cloud-init field

The system SHALL declare a `package_upgrade: bool` dataclass field (default `True`) on each of the four cloud-provider config DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`) in `yascheduler/infra/cloud/cloud_configs.py`. The field controls the cloud-init `package_upgrade` flag on freshly-provisioned VMs for that provider (it flows into `CloudInitConfig.package_upgrade` via `CloudProvisionerImpl._get_cloud_config_data`). The default `True` preserves the pre-change cloud-init behavior (an `apt-get upgrade` runs on first boot).

The field SHALL be declared on the concrete DTOs only. It SHALL NOT be added to the `CloudConfig` domain Protocol (`yascheduler/domain/ports.py`): the Protocol captures the 7-field application-facing surface (`prefix`, `max_nodes`, `idle_tolerance`, `connect_grace`, `username`, `jump_username`, `jump_host`) read by `deallocate_nodes`, `orchestrator`, and the never-connected-node cleanup path. `package_upgrade` is read only by infra (`CloudProvisionerImpl`), so it sits in the same category as `token`, `vm_size`, `server_type`, and `api_key` — infra-only fields on the concrete DTOs.

Each per-prefix parser (`_parse_azure_section`, `_parse_hetzner_section`, `_parse_upcloud_section`, `_parse_vastai_section` in `yascheduler/entrypoints/config_parser.py`) SHALL read the optional `{prefix}_package_upgrade` key (e.g. `hetzner_package_upgrade`, `az_package_upgrade`) via `sec.getboolean(fmt("package_upgrade"), fallback=True)` and pass the result to the DTO constructor. Because `cloud_valid_fields(prefix)` derives the valid key set from `dataclasses.fields(dto_cls)` minus excludes, the new `{prefix}_package_upgrade` key SHALL be auto-registered as a known field — no edit to `_CLOUD_FIELD_RULES` is required, `_ALL_CLOUD_VALID_FIELDS` follows automatically, and `warn_unknown_fields` SHALL NOT warn about the key.

#### Scenario: package_upgrade defaults to True on all four DTOs
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI` is constructed without a `package_upgrade` argument
- **THEN** the resulting instance has `package_upgrade is True` (preserving the pre-change cloud-init behavior)

#### Scenario: package_upgrade accepts False
- **WHEN** `ConfigCloudHetzner(package_upgrade=False)` is constructed
- **THEN** the resulting instance has `package_upgrade is False`

#### Scenario: package_upgrade is NOT on the CloudConfig Protocol
- **WHEN** the `CloudConfig` Protocol in `yascheduler/domain/ports.py` is introspected for a `package_upgrade` attribute
- **THEN** no such attribute is declared (the field lives on the concrete DTOs only, like `token`/`vm_size`)

#### Scenario: [clouds] package_upgrade parsed per provider
- **WHEN** `parse_clouds(cfg, remote)` parses a `[clouds]` section containing `hetzner_package_upgrade = false` and no other `{prefix}_package_upgrade` keys
- **THEN** the returned `ConfigCloudHetzner` has `package_upgrade is False`
- **AND** the returned `ConfigCloudAzure`/`ConfigCloudUpcloud`/`ConfigCloudVastAI` (if their prefixes are present) each have `package_upgrade is True` (the per-provider default)

#### Scenario: absent package_upgrade key defaults to True
- **WHEN** `parse_clouds(cfg, remote)` parses a `[clouds]` section whose `{prefix}_*` keys do not include any `{prefix}_package_upgrade`
- **THEN** every returned `ConfigCloud*` DTO has `package_upgrade is True`

#### Scenario: package_upgrade key does not warn as unknown
- **WHEN** `parse_clouds(cfg, remote)` parses a `[clouds]` section containing `hetzner_package_upgrade = false`
- **THEN** `warn_unknown_fields` does NOT emit a `ConfigWarning` for `hetzner_package_upgrade` (it is auto-registered via `cloud_valid_fields("hetzner")` introspection of the DTO field)