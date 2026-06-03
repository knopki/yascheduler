## REMOVED Requirements

### Requirement: CloudAPIManager becomes compatibility wrapper
**Reason**: The `clouds/` package is deleted. `CloudProvisionerImpl` in `adapters/cloud/manager.py` is the sole cloud adapter.
**Migration**: Use `CloudProvisionerImpl` directly from `adapters/cloud/manager.py`.

### Requirement: CloudAPI becomes compatibility wrapper
**Reason**: The `clouds/` package is deleted. Cloud-init rendering lives in `adapters/cloud/cloud_config.py`, SSH key management in `adapters/cloud/ssh_keys.py`, node lifecycle in `CloudProvisionerImpl`.
**Migration**: Use the `adapters/cloud/` modules directly.

### Requirement: Old imports preserved
**Reason**: The `clouds/` package is deleted. No backward-compatible re-exports needed.
**Migration**: Import from `adapters/cloud/` instead of `clouds/`.
