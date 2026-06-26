## ADDED Requirements

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

The Protocol is structural (no explicit inheritance required); every `ConfigCloud*`
DTO in `infra/cloud/cloud_configs.py` SHALL satisfy `CloudConfig` structurally because
it declares all 6 fields. Application-layer consumers SHALL type their
`config_clouds` / `active_clouds` parameters as `Sequence[CloudConfig]` (domain
Protocol), not `Sequence[ConfigCloud]` (infra Union), keeping `application → infra`
TYPE_CHECKING-only.

`CloudConfig` follows the precedent of `OccupancyConfig` and `TaskExecutionEngine`
already in `domain/ports.py` — structural Protocols for the minimal surface a consumer
needs, satisfied by the concrete class without inheritance.

The Protocol SHALL be importable via the `yascheduler.domain` facade
(`from yascheduler.domain import CloudConfig`) and the deep path
(`from yascheduler.domain.ports import CloudConfig`).

#### Scenario: CloudConfig Protocol is runtime_checkable
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
- **THEN** it returns `True` (the DTO satisfies the Protocol structurally)

#### Scenario: All four ConfigCloud DTOs satisfy CloudConfig
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI` is constructed with valid fields and checked with
  `isinstance(dto, CloudConfig)`
- **THEN** every check returns `True`

#### Scenario: deallocate_nodes types against CloudConfig
- **WHEN** `deallocate_nodes.py` is inspected for its `config_clouds` parameter type
  annotation
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