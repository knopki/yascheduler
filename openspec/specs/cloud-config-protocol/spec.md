# Cloud Config Protocol

## Purpose

The CloudConfig structural Protocol in `yascheduler/domain/ports.py` capturing the 6-field surface application-layer consumers read from cloud provider configs.

## Requirements

### Requirement: CloudConfig structural Protocol

The system SHALL define a structural `@runtime_checkable` `CloudConfig` Protocol in
`yascheduler/domain/ports.py` capturing the 6-field surface that application-layer
consumers (`deallocate_nodes`, `orchestrator`) read from cloud provider configs:

- `prefix: str`
- `max_nodes: int`
- `idle_tolerance: int`
- `username: str`
- `jump_username: str | None`
- `jump_host: str | None`

The Protocol is structural (a DTO outside the inheritance tree satisfies it
structurally per PEP 544). The concrete `ConfigCloud*` DTOs in
`infra/cloud/cloud_configs.py` SHALL **explicitly inherit** the Protocol as a
typing aid — this removes the writable-vs-frozen mismatch that previously
forced `cast("Sequence[CloudConfig]", ...)` bridges in the composition root
(`entrypoints/di.py`) and parser (`entrypoints/config_parser.py`).
Application-layer consumers SHALL type their `config_clouds` / `active_clouds`
parameters as `Sequence[CloudConfig]` (domain Protocol), not
`Sequence[ConfigCloud]` (infra Union), keeping `application → infra`
TYPE_CHECKING-only.

The Protocol SHALL NOT mandate inheritance (a DTO declaring all 6 fields
satisfies it structurally); the explicit inheritance by the 4 `ConfigCloud*`
DTOs is the chosen technique for the typing aid, not a structural requirement
relaxation. The Protocol stays in place because there are multiple DTO
implementers (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
`ConfigCloudVastAI`), in contrast to the single-implementer engine case where
the `OccupancyConfig` and `TaskExecutionEngine` Protocols were removed (per the
`engine-to-domain-frozen` D4 rationale that a single-implementer Protocol
mirroring a concrete class is duplication whose cost exceeds the
Interface-Segregation benefit).

The Protocol SHALL be importable via the `yascheduler.domain` facade
(`from yascheduler.domain import CloudConfig`) and the deep path
(`from yascheduler.domain.ports import CloudConfig`).

The composition root (`entrypoints/di.py`) SHALL NOT contain
`cast("Sequence[CloudConfig]", ...)` upcast bridges — the explicit DTO→Protocol
inheritance makes those upcasts dead weight (`list[ConfigCloud]` is assignable
to `Sequence[CloudConfig]` via covariance + inheritance). The parser
(`entrypoints/config_parser.py`) SHALL NOT contain `cast("Sequence[CloudConfig]",
...)`. Two Protocol→Union **downcasts** at the entrypoints→infra boundary
(`di.py` `cast("ConfigCloud", cfg)` and `cast("list[ConfigCloud]", [...])`)
are retained as honest boundary casts: `config.clouds` is typed
`Sequence[CloudConfig]` (domain Protocol), so iterating yields `CloudConfig`,
but the composition root feeds `cfg` to infra-side sinks that expect the
concrete `ConfigCloud` Union (`resolve_adapter(cfg: ConfigCloud)`,
`CloudProvisionerImpl.configs: dict[str, ConfigCloud]`,
`active_clouds: list[ConfigCloud]`). D1 (DTOs inherit Protocol) makes the
**upcast** direction typecheck; it does nothing for the opposite **downcast**
direction (`CloudConfig → ConfigCloud`), which remains invalid because a
Protocol variable is not assignable to a concrete-Union target regardless of
inheritance. These 2 downcasts are documented boundary casts, not debt. The
codebase SHALL NOT contain comments attributing the prior upcasts to
"`Sequence` invariance against the Protocol" — the actual cause was writable
Protocol attributes vs `@dataclass(frozen=True)` DTOs (for the upcasts) and
the Protocol→Union downcast direction (for the retained casts); the explicit
inheritance resolves the upcasts directly.

#### Scenario: CloudConfig Protocol is runtime_checkable
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
- **THEN** it returns `True` (the DTO inherits the Protocol explicitly; the
  Protocol is `@runtime_checkable`)

#### Scenario: All four ConfigCloud DTOs satisfy CloudConfig via isinstance
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI` is constructed with valid fields and checked with
  `isinstance(dto, CloudConfig)`
- **THEN** every check returns `True`

#### Scenario: All four ConfigCloud DTOs explicitly inherit CloudConfig
- **WHEN** each `ConfigCloud*` DTO's `__mro__` is introspected
- **THEN** the `CloudConfig` Protocol from `yascheduler.domain` appears in the
  MRO (the inheritance is explicit, not merely structural)

#### Scenario: issubclass on the DTO class is not used by production code
- **WHEN** the `yascheduler/` source tree is searched for
  `issubclass(<class>, CloudConfig)`
- **THEN** zero matches are found in production code (PEP 544 bans
  `issubclass` on data-Protocols with non-method members; tests that need to
  verify the inheritance use `__mro__` introspection or `isinstance` on
  instances instead)

#### Scenario: deallocate_nodes types against CloudConfig
- **WHEN** `deallocate_nodes.py` is inspected for its `config_clouds` parameter
  type annotation
- **THEN** it is `Sequence[CloudConfig]` imported from `yascheduler.domain`
  (TYPE_CHECKING), not `Sequence[ConfigCloud]` from `yascheduler.config` or
  `yascheduler.infra.cloud`

#### Scenario: orchestrator types config_clouds and active_clouds against CloudConfig
- **WHEN** `orchestrator.py` is inspected for the `config_clouds` and `active_clouds`
  constructor parameter type annotations
- **THEN** both are `Sequence[CloudConfig]` imported from `yascheduler.domain`
  (TYPE_CHECKING)

#### Scenario: CloudConfig importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError

#### Scenario: CloudConfig does not expose provider-specific fields
- **WHEN** the `CloudConfig` Protocol is introspected for provider-specific fields
  (`tenant_id`, `token`, `login`, `api_key`, `server_type`, `vm_size`, `disk_gb`,
  `min_vram_mb`, `num_gpus`, `max_price_per_hr`, `onstart_script`, `docker_options`,
  `env`, `resource_group`, `location`, `vnet`, `subnet`, `nsg`, `vm_image`, `priority`,
  `client_id`, `client_secret`, `subscription_id`, `image_name`)
- **THEN** none of these fields are declared on the Protocol (ISP: application never
  reads them; only infra-layer consumers access provider specifics)

#### Scenario: No upcast bridges in composition root
- **WHEN** `entrypoints/di.py` is inspected for `cast("Sequence[CloudConfig]"`
- **THEN** zero matches are found (the explicit DTO→Protocol inheritance
  makes the upcasts `list[ConfigCloud] → Sequence[CloudConfig]` dead weight
  via covariance + inheritance)

#### Scenario: Retained Protocol→Union downcasts at entrypoints→infra boundary
- **WHEN** `entrypoints/di.py` is inspected for `cast("ConfigCloud"` and
  `cast("list[ConfigCloud]"`
- **THEN** exactly 2 matches are found (one `cast("ConfigCloud", cfg)` and
  one `cast("list[ConfigCloud]", [...])`); both are Protocol→Union downcasts
  at the boundary where `config.clouds: Sequence[CloudConfig]` feeds
  infra-side sinks typed `ConfigCloud` (`resolve_adapter`,
  `CloudProvisionerImpl.configs`, `active_clouds`); each carries a comment
  explaining the downcast direction (D1 removes the upcast direction only)

#### Scenario: No cast bridges in config parser
- **WHEN** `entrypoints/config_parser.py` is inspected for
  `cast("Sequence[CloudConfig]"`
- **THEN** zero matches are found
