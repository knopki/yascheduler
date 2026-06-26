## MODIFIED Requirements

### Requirement: CloudProvisionerImpl owns cloud-init rendering and SSH key management

The system SHALL provide cloud-init configuration rendering and SSH key
management within `infra/cloud/`, without depending on `clouds/cloud_api.py`.
SSH key generation, loading, and name extraction SHALL live in
`infra/cloud/ssh_keys.py`.

The cloud-init user-data renderer SHALL be a single concrete frozen dataclass
`CloudInitConfig` in `infra/cloud/cloud_init.py` (renamed from
`infra/cloud/cloud_config.py` `class CloudConfig` in the
`cloud-init-rename-and-prune` change). There SHALL be no `PCloudConfig`
Protocol in `infra/cloud/protocols.py`: the single-implementer Protocol was
collapsed into its sole concrete class because it had zero runtime dispatch
(`@runtime_checkable` was never applied; zero `isinstance` calls) and a
self-referential seam (`CreateNodeCallable.__call__` referenced it; providers
referenced it because `CreateNodeCallable` did). Provider `*_create_node`
callables and `CreateNodeCallable.__call__` SHALL type their `cloud_config`
parameter as `Optional[CloudInitConfig]` (the concrete class), not
`Optional[PCloudConfig]` (the deleted Protocol).

The `az_create_node` public entry point SHALL NOT carry a runtime `isinstance`
boundary guard narrowing `cloud_config` to the concrete class. The guard
introduced by `resolve-type-bridge-debt` D3a (bridging a public
`PCloudConfig | None` param to an internal `CloudConfig | None` param) is
removed in the `cloud-init-rename-and-prune` change: with both sides retyped
to the same concrete class, the guard's premise (a foreign `PCloudConfig`
impl reaching `az_create_node`) is structurally impossible, and the guard
would be dead code asserting a property the type system already guarantees.

#### Scenario: Cloud-init rendered without CloudAPI
- **WHEN** `CloudInitConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the cloud-config YAML is produced from `infra/cloud/cloud_init.py`
  (the renderer file was renamed from `infra/cloud/cloud_config.py` in the
  `cloud-init-rename-and-prune` change to disambiguate from the
  `ConfigCloud*` provider-config DTOs in `infra/cloud/cloud_configs.py`)

#### Scenario: SSH key generated for cloud provisioning
- **WHEN** a cloud provider needs an SSH key
- **THEN** the key is generated or loaded via `infra/cloud/ssh_keys.py`

#### Scenario: Cloud-init renderer is a single concrete class
- **WHEN** the `yascheduler/infra/cloud/` directory is inspected for
  `cloud_init.py` and `cloud_config.py`
- **THEN** `cloud_init.py` exists and contains `class CloudInitConfig` (a
  `@dataclass(frozen=True)` with no Protocol base class); `cloud_config.py`
  does NOT exist; `protocols.py` does NOT define `PCloudConfig`

#### Scenario: Provider create_node callables type cloud_config as CloudInitConfig
- **WHEN** each of `az_create_node`, `hetzner_create_node`,
  `upcloud_create_node`, `vastai_create_node` is inspected for its
  `cloud_config` parameter type annotation
- **THEN** the annotation is `CloudInitConfig | None` (or
  `Optional[CloudInitConfig]`), imported from `yascheduler.infra.cloud` or
  `yascheduler.infra.cloud.cloud_init`; no reference to `PCloudConfig` appears
  in any provider file

#### Scenario: CreateNodeCallable types cloud_config as CloudInitConfig
- **WHEN** `CreateNodeCallable.__call__` in `infra/cloud/protocols.py` is
  inspected for its `cloud_config` parameter type annotation
- **THEN** the annotation is `Optional[CloudInitConfig]` (or
  `CloudInitConfig | None`); the `PCloudConfig` Protocol class is absent from
  `protocols.py`

#### Scenario: az_create_node has no isinstance boundary guard
- **WHEN** `yascheduler/infra/cloud/providers/az.py` is inspected for
  `isinstance(cloud_config, CloudInitConfig)` or
  `isinstance(cloud_config, CloudConfig)`
- **THEN** zero matches are found in the `az_create_node` function body (the
  D3a boundary guard is removed; both sides of the call chain are the same
  concrete class, making the guard structurally unreachable)

#### Scenario: No PCloudConfig references remain in source
- **WHEN** the `yascheduler/` source tree is searched for `PCloudConfig\b`
- **THEN** zero matches are found (the Protocol is deleted; all references
  retyped to `CloudInitConfig`)

#### Scenario: CloudCapacity dataclass removed
- **WHEN** the `yascheduler/` source tree is searched for `class CloudCapacity`
  and `CloudCapacity(` (construction sites)
- **THEN** zero matches are found in source (the `CloudCapacity` dataclass in
  `infra/cloud/protocols.py` is deleted; its last consumer was removed in
  the archived `cloud-provisioner-pure` change which rewrote
  `_clouds_get_capacity` to return `int`; the unrelated
  `CloudCapacityExhaustedError` domain exception in `domain/exceptions.py` is
  NOT a `CloudCapacity` consumer and is unaffected)