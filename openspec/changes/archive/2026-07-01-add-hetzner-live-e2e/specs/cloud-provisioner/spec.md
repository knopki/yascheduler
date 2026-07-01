## ADDED Requirements

### Requirement: Cloud-init package_upgrade sourced from local config

`CloudProvisionerImpl._get_cloud_config_data` SHALL build the `CloudInitConfig` passed
to provider `create_node` callables with its `package_upgrade` flag sourced from
`self.local_config.cloud_package_upgrade` (`LocalSettings` field, default `True`), NOT
hardcoded to `True`. This lets operators (and tests) skip the slow cloud-init
`apt-get upgrade` on freshly-provisioned VMs.

The `packages` list SHALL continue to be derived from the platform-matched engines'
`platform_packages` (unchanged). Only the `package_upgrade` flag's sourcing changes.

#### Scenario: package_upgrade reflects LocalSettings.cloud_package_upgrade
- **WHEN** `CloudProvisionerImpl._get_cloud_config_data(adapter)` builds the `CloudInitConfig` and `self.local_config.cloud_package_upgrade is True`
- **THEN** the resulting `CloudInitConfig.package_upgrade is True`
- **WHEN** `self.local_config.cloud_package_upgrade is False`
- **THEN** the resulting `CloudInitConfig.package_upgrade is False`

#### Scenario: Default behavior is unchanged
- **WHEN** a daemon is constructed from a `Config` whose `LocalSettings` was parsed from a `[local]` section that does not set `cloud_package_upgrade`
- **THEN** `local_config.cloud_package_upgrade is True` (the field default), preserving the pre-change cloud-init behavior
