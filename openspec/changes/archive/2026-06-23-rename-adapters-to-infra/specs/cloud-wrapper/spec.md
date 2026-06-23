## MODIFIED Requirements

### Requirement: Wrapper code removed

The system SHALL delete the `clouds/` package and all compatibility wrappers
(CloudAPIManager, CloudAPI). Consumers SHALL use `CloudProvisionerImpl` from
`infra/cloud/manager.py` for cloud provisioning, `infra/cloud/cloud_config.py`
for cloud-init rendering, and `infra/cloud/ssh_keys.py` for SSH key management.

#### Scenario: Import from new location
- **WHEN** cloud provisioning is needed
- **THEN** CloudProvisionerImpl is imported from infra.cloud.manager
