# Cloud Wrapper

## Purpose

Transitional compatibility wrappers in the legacy clouds/ package that delegated
to CloudProvisionerImpl during the migration to infra/cloud/. The clouds/
package and all wrappers are removed; use CloudProvisionerImpl directly.

## Requirements

### Requirement: Wrapper code removed

The system SHALL delete the `clouds/` package and all compatibility wrappers
(CloudAPIManager, CloudAPI). Consumers SHALL use `CloudProvisionerImpl` from
`infra/cloud/manager.py` for cloud provisioning, `infra/cloud/cloud_config.py`
for cloud-init rendering, and `infra/cloud/ssh_keys.py` for SSH key management.

#### Scenario: Import from new location
- **WHEN** cloud provisioning is needed
- **THEN** CloudProvisionerImpl is imported from adapters.cloud.manager
