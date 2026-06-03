## 1. Provider Relocation

- [x] 1.1 Create `adapters/cloud/__init__.py` and `adapters/cloud/providers/__init__.py`
- [x] 1.2 Move `clouds/az.py` → `adapters/cloud/providers/az.py`
- [x] 1.3 Move `clouds/hetzner.py` → `adapters/cloud/providers/hetzner.py`
- [x] 1.4 Move `clouds/upcloud.py` → `adapters/cloud/providers/upcloud.py`
- [x] 1.5 Move `clouds/adapters.py` → `adapters/cloud/adapters.py`
- [x] 1.6 Move `clouds/protocols.py` → `adapters/cloud/protocols.py`
- [x] 1.7 Move `clouds/utils.py` → `adapters/cloud/utils.py`
- [x] 1.8 Update internal imports in moved files to new package paths
- [x] 1.9 Handle optional SDK imports gracefully (try/except ImportError, log warning)

## 2. CloudProvisionerImpl

- [x] 2.1 Create `adapters/cloud/manager.py` with `CloudProvisionerImpl` class
- [x] 2.2 Implement `allocate(platforms)` — select provider, create VM, wait SSH, setup
- [x] 2.3 Implement `deallocate(ip)` — identify provider, delete VM, remove from DB
- [x] 2.4 Implement `capacity()` — aggregate available nodes across all providers
- [x] 2.5 Implement `_select_best_provider(platforms)` — priority + capacity algorithm
- [x] 2.6 Integrate SSH key generation and cloud-init config (moved from CloudAPI)
- [x] 2.7 Integrate cloud-init wait and node setup (moved from CloudAPI)
- [x] 2.8 Implement concurrent allocation throttling per task_id
- [x] 2.9 Switch from self.db.method() to NodeRepository (injected)
- [x] 2.10 Switch from RemoteMachine to SSHMachineGateway for machine connections
- [x] 2.11 Add GRACE-lite markup
- [x] 2.12 Write unit tests with mocked provider SDKs

## 3. Compatibility Wrappers

- [x] 3.1 Refactor `CloudAPIManager` to delegate to `CloudProvisionerImpl`
- [x] 3.2 Preserve `CloudAPIManager.create()` factory method — unchanged signature, builds `CloudProvisionerImpl` internally
- [x] 3.3 Keep `CloudAPI` as-is — no longer used by `CloudAPIManager`, preserved for backward compat
- [x] 3.4 Re-export old symbols from `clouds/__init__.py` — already exports `CloudAPIManager`, no changes needed

## 4. Wiring

- [x] 4.1 Update `di.make_daemon()` to create `CloudProvisionerImpl` instead of `CloudAPIManager`
- [x] 4.2 Inject `NodeRepository` (via UoW) into `CloudProvisionerImpl`
- [x] 4.3 Inject `SSHMachineGateway` into `CloudProvisionerImpl`
- [x] 4.4 Update orchestrator to use `CloudProvisioner` port interface
- [x] 4.5 Remove cloud-specific DB methods from `db.py` wrapper (no longer needed)

## 5. Tests

- [x] 5.1 Write unit tests for `CloudProvisionerImpl` with faked providers
- [x] 5.2 Write characterization tests: old CloudAPIManager behavior preserved
- [x] 5.3 Write tests for graceful handling of missing provider SDKs

## 6. Verification

- [x] 6.1 Run `grace_check.py` — all files pass
- [x] 6.2 Update `docs/knowledge-graph.xml`
- [x] 6.3 Run `openspec validate --all --json`
- [x] 6.4 Run all unit tests — no regressions
- [x] 6.5 Run full test suite
- [x] 6.6 Verify old imports from yascheduler.clouds still resolve
