## MODIFIED Requirements

### Requirement: Node setup after provisioning

The system SHALL run cloud-init status check and engine setup after a VM is
created, before returning the Node. All setup logic SHALL be contained within
`infra/cloud/` — no imports from `clouds/` or `remote_machine/`.

#### Scenario: Cloud-init must complete
- **WHEN** a VM is created
- **THEN** cloud-init status --wait is executed before setup

#### Scenario: Engine packages installed
- **WHEN** node setup runs on a fresh VM
- **THEN** required packages for configured engines are installed

#### Scenario: No CloudAPI dependency
- **WHEN** CloudProvisionerImpl creates a node
- **THEN** no code from `clouds/cloud_api.py` is invoked

### Requirement: CloudProvisionerImpl owns cloud-init rendering and SSH key management

The system SHALL provide cloud-init configuration rendering and SSH key
management within `infra/cloud/`, without depending on `clouds/cloud_api.py`.
SSH key generation, loading, and name extraction SHALL live in
`infra/cloud/ssh_keys.py`.

#### Scenario: Cloud-init rendered without CloudAPI
- **WHEN** `CloudConfig(bootcmd=..., packages=...).render()` is called
- **THEN** the cloud-config YAML is produced from `infra/cloud/cloud_config.py`

#### Scenario: SSH key generated for cloud provisioning
- **WHEN** a cloud provider needs an SSH key
- **THEN** the key is generated or loaded via `infra/cloud/ssh_keys.py`
