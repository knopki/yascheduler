## REMOVED Requirements

### Requirement: Wrapper code removed
**Reason**: The `clouds/` package and all compatibility wrappers (CloudAPIManager, CloudAPI) were removed in the completed `2026-06-02-cloud-adapter` / `2026-06-23-remove-legacy-modules` migrations. The spec documented a transitional state that no longer exists; keeping it leaves a live spec describing absent code. The `cloud-provisioner` capability already states where `CloudProvisionerImpl` lives.
**Migration**: Read `cloud-provisioner` for the cloud provisioning contract. The import path `infra/cloud/manager.py` is documented there.