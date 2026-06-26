## ADDED Requirements

### Requirement: CloudConfig structural Protocol

The system SHALL define a `@runtime_checkable` `CloudConfig` Protocol in
`yascheduler/domain/ports.py` with attributes:
- `prefix: str`
- `max_nodes: int`
- `idle_tolerance: int`
- `username: str`
- `jump_username: str | None`
- `jump_host: str | None`

`CloudConfig` captures the 6-field surface that application-layer consumers
(`deallocate_nodes`, `orchestrator`) read from cloud provider configs. The
concrete `ConfigCloud*` DTOs in `infra/cloud/cloud_configs.py` SHALL
**explicitly inherit** `CloudConfig` as a typing aid — the inheritance removes
the writable-vs-frozen mismatch that previously forced `cast` bridges in the
composition root and parser. The Protocol remains structural: a DTO outside
the inheritance tree still satisfies `CloudConfig` structurally per PEP 544;
the explicit inheritance by the 4 `ConfigCloud*` DTOs does not relax the
structural contract.

Application-layer consumers SHALL type `config_clouds` / `active_clouds`
parameters as `Sequence[CloudConfig]`, not `Sequence[ConfigCloud]`, keeping
`application → infra` TYPE_CHECKING-only. `CloudConfig` is a structural
Protocol for the minimal surface a consumer needs; it stands as its own
requirement (previously sub-prose under the `MachineGateway port`
requirement) because it has its own implementers (the 4 `ConfigCloud*` DTOs)
and its own consumption surface (`deallocate_nodes`, `orchestrator`), unlike
the single-implementer `Engine` case where the `OccupancyConfig` and
`TaskExecutionEngine` Protocols were removed.

The `CloudConfig` Protocol's docstring SHALL reflect the explicit-inheritance
choice — the prior "(no explicit inheritance)" wording (currently at
`yascheduler/domain/ports.py:101-108`, sub-prose under the `MachineGateway
port` requirement) becomes stale after the 4 `ConfigCloud*` DTOs gain explicit
inheritance; the docstring SHALL state that the DTOs inherit the Protocol
explicitly as a typing aid while structural matching continues to apply to any
DTO declaring the 6 fields. The stale "satisfied ... without inheritance"
prose under the `MachineGateway port` requirement (lines 110-116 of the
current spec) SHALL be removed from that location — the CloudConfig contract
now stands as its own requirement (this one), and the `MachineGateway port`
requirement SHALL no longer carry CloudConfig sub-prose.

#### Scenario: CloudConfig is runtime_checkable and satisfied by ConfigCloud DTOs
- **WHEN** `isinstance(ConfigCloudAzure(...), CloudConfig)` is evaluated
- **THEN** it returns `True` (the DTO inherits the Protocol explicitly; the
  Protocol is `@runtime_checkable`)

#### Scenario: CloudConfig docstring reflects explicit inheritance
- **WHEN** the `CloudConfig` Protocol's docstring in
  `yascheduler/domain/ports.py` is inspected
- **THEN** it does NOT contain the phrase "(no explicit inheritance)" (the 4
  `ConfigCloud*` DTOs now inherit the Protocol explicitly); it SHALL state
  that the DTOs inherit the Protocol as a typing aid and that structural
  matching continues to apply to any DTO declaring the 6 fields

#### Scenario: No stale "without inheritance" prose under MachineGateway port
- **WHEN** the `### Requirement: MachineGateway port` block in
  `yascheduler/domain/ports.py` (or in the rendered spec) is inspected
- **THEN** it does NOT carry the CloudConfig sub-prose previously at lines
  100-117 of `openspec/specs/domain-ports/spec.md` (the CloudConfig contract
  now stands as its own requirement; the `MachineGateway port` requirement
  no longer carries CloudConfig sub-prose or the "CloudConfig is
  runtime_checkable and satisfied by ConfigCloud DTOs" Scenario previously
  at lines 162-164)

#### Scenario: CloudConfig importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import CloudConfig`
- **THEN** the Protocol class resolves without ImportError