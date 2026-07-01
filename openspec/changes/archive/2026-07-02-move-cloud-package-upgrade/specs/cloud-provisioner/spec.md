## REMOVED Requirements

### Requirement: Cloud-init package_upgrade sourced from local config
**Reason**: The `package_upgrade` flag is re-sourced from the per-cloud config
DTO (`config.package_upgrade`) instead of `self.local_config.cloud_package_upgrade`.
The knob has been relocated out of `LocalSettings` (a cloud-only concern does
not belong on the local-daemon DTO); see the `cloud-config` capability's
"Per-provider package_upgrade cloud-init field" requirement for the new
location and the ADDED requirement below for the new sourcing contract.
**Migration**: Set `[clouds] {prefix}_package_upgrade = ...` instead of
`[local] cloud_package_upgrade = ...`. The default (`True`) is unchanged, so
deployments that did not set the key see identical cloud-init behavior. A
leftover `[local] cloud_package_upgrade` key now surfaces as an "unknown field"
`ConfigWarning` (no error), signaling the move.

## ADDED Requirements

### Requirement: Cloud-init package_upgrade sourced from per-cloud config

`CloudProvisionerImpl._get_cloud_config_data` SHALL build the `CloudInitConfig`
passed to provider `create_node` callables with its `package_upgrade` flag
sourced from the per-cloud config DTO's `package_upgrade` field
(`config.package_upgrade`, default `True`), NOT from
`self.local_config.cloud_package_upgrade` (which no longer exists) and NOT
hardcoded to `True`.

The method signature SHALL be
`_get_cloud_config_data(self, adapter: CloudAdapter, config: ConfigCloud)`,
where `config` is the per-cloud DTO resolved by the caller. The `config`
parameter SHALL be typed `ConfigCloud` (the infra Union of the four
`ConfigCloud*` DTOs), NOT the domain `CloudConfig` Protocol — because
`package_upgrade` is declared on the concrete DTOs only (not on the Protocol),
typing against the Protocol would not resolve `config.package_upgrade`
statically.

The sole caller, `CloudProvisionerImpl.allocate`, SHALL pass the per-cloud
config it already resolves (`config = self.configs.get(provider)`) as the
`config` argument.

This lets operators (and tests) skip the slow cloud-init `apt-get upgrade` on
freshly-provisioned VMs on a per-provider basis. The `packages` list SHALL
continue to be derived from the platform-matched engines' `platform_packages`
(unchanged). Only the `package_upgrade` flag's sourcing changes.

#### Scenario: package_upgrade reflects config.package_upgrade
- **WHEN** `CloudProvisionerImpl._get_cloud_config_data(adapter, config)` builds the `CloudInitConfig` and `config.package_upgrade is True`
- **THEN** the resulting `CloudInitConfig.package_upgrade is True`
- **WHEN** the same is called with a `config` whose `package_upgrade is False`
- **THEN** the resulting `CloudInitConfig.package_upgrade is False`

#### Scenario: _get_cloud_config_data receives the resolved per-cloud config
- **WHEN** `CloudProvisionerImpl.allocate("hetzner")` is inspected for how it builds the cloud config passed to `adapter.create_node`
- **THEN** it resolves `config = self.configs.get("hetzner")` and passes that same `config` as the `config` argument to `_get_cloud_config_data(adapter, config)`

#### Scenario: config parameter typed as the infra ConfigCloud union
- **WHEN** `_get_cloud_config_data` is introspected for its `config` parameter type annotation
- **THEN** the annotation is `ConfigCloud` (imported from `yascheduler.infra.cloud` or intra-package `.cloud_configs`), NOT the domain `CloudConfig` Protocol

#### Scenario: Default behavior is unchanged
- **WHEN** a daemon is constructed from a `Config` whose active `ConfigCloud*` DTOs were parsed from a `[clouds]` section that does not set any `{prefix}_package_upgrade` key
- **THEN** each such DTO has `package_upgrade is True` (the field default), preserving the pre-change cloud-init behavior
