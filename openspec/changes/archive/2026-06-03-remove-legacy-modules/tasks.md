## 1. Extract shared SSH helpers to adapters/ssh/helpers.py

- [x] 1.1 Create `adapters/ssh/helpers.py` — move `ADAPTERS`, `DEFAULT_CONN_OPTS`, `MySSHClient`, `MAX_SESSIONS`, `my_backoff_exc`, `_detect_platform`, `_init_paths`, `_resolve_tunnel` from `remote_machine/remote_machine.py`. Import platform adapters from `adapters/ssh/platform/adapters.py` instead of `remote_machine/adapters.py`.
- [x] 1.2 Update `adapters/ssh/gateway.py` — replace all `from yascheduler.remote_machine.remote_machine import ...` with `from .helpers import ...`. Verify gateway is self-contained (no `remote_machine/` imports).
- [x] 1.3 Create `adapters/ssh/exceptions.py` — move `SSHRetryExc`, `SFTPRetryExc`, `AllSSHRetryExc` from `remote_machine/protocol.py`. Update all consumers to import from new location.
- [x] 1.4 Run `uv run -m unit` to verify helpers extraction doesn't break existing tests.

## 2. Absorb CloudAPI logic into adapters/cloud/

- [x] 2.1 Create `adapters/cloud/ssh_keys.py` — extract SSH key generation, loading, and name extraction from `clouds/cloud_api.py` (`get_ssh_key_sync`, key generation logic).
- [x] 2.2 Verify `adapters/cloud/cloud_config.py` covers all `CloudConfig` rendering from `clouds/cloud_api.py`. Add missing functionality if any.
- [x] 2.3 Update `adapters/cloud/manager.py` (CloudProvisionerImpl) — absorb node-creation orchestration from `CloudAPI.create_node()`: cloud-init status wait, SSH connection, setup_node. Remove any imports from `clouds/` or `remote_machine/`.
- [x] 2.4 Move `_resolve_adapter` from `clouds/cloud_api_manager.py` to `adapters/cloud/adapters.py`.
- [x] 2.5 Run `uv run -m unit` to verify cloud adapter is self-contained.

## 3. Migrate use cases from RemoteMachine to MachineGateway

- [x] 3.1 Rewrite `application/allocate_task.py` — replace `RemoteMachine` / `RemoteMachineRepository` params with `SSHMachineGateway`. Use `gateway.list_free(platforms)` instead of `repo.filter()`. Use `gateway.run()` / `gateway.upload()` instead of `machine.run()` / `machine.sftp()`. Remove all `from yascheduler.remote_machine` imports.
- [x] 3.2 Rewrite `application/consume_task.py` — replace `RemoteMachine` param with `SSHMachineGateway` + ip-based operations. Use `gateway.download()` instead of SFTP via `machine.sftp()`. Import retry exceptions from `adapters/ssh/exceptions.py`. Remove all `from yascheduler.remote_machine` imports.
- [x] 3.3 Rewrite `application/deallocate_nodes.py` — replace `RemoteMachineRepository` param with `SSHMachineGateway`. Use `gateway.disconnect()` instead of `repo.disconnect_many()`. Remove `from yascheduler.remote_machine` import.
- [x] 3.4 Run `uv run -m unit` to verify use case rewrites.

## 4. Migrate orchestrator from RemoteMachineRepository to SSHMachineGateway

- [x] 4.1 Rewrite `application/orchestrator.py` — replace `RemoteMachineRepository` field with `SSHMachineGateway`. Update connect-machine loop to use `gateway.connect()`. Update deallocate to use `gateway.disconnect()`. Update SSH helpers (`_upload_task_data`, `_start_task_on_machine`, `_exec_spawn_command`) to use `gateway.run()` / `gateway.upload()`. Remove all `from yascheduler.remote_machine` imports.
- [x] 4.2 Run `uv run -m unit` to verify orchestrator rewrite.

## 5. Update DI and scheduler

- [x] 5.1 Rewrite `di.py` — remove `RemoteMachineRepository` import and creation. Import `_resolve_adapter` from `adapters/cloud/adapters.py`. Pass `SSHMachineGateway` directly to `Orchestrator`. Remove all imports from `remote_machine/` and `clouds/`.
- [x] 5.2 Update `scheduler.py` — remove any remaining `remote_machine/` or `clouds/` imports if present.
- [x] 5.3 Run `uv run -m unit` to verify DI wiring.

## 6. Delete legacy packages

- [x] 6.1 Delete `yascheduler/remote_machine/` package entirely.
- [x] 6.2 Delete `yascheduler/clouds/` package entirely.
- [x] 6.3 Update `tests/` — remove `tests/unit/test_remote_machine.py`, `tests/fixtures/mock_remote_machine.py`, `tests/unit/test_cloud_api_compat.py`, `tests/unit/test_cloud_api_manager.py`, `tests/unit/test_cloud_providers_sdk_handling.py`. Update `tests/e2e/test_full_cycle.py` and any remaining imports.
- [x] 6.4 Update `docs/knowledge-graph.xml` — remove all `M-REMOTE-*` and `M-CLOUD-API` / `M-CLOUD-MANAGER` / `M-CLOUD-AZ` / `M-CLOUD-HETZNER` / `M-CLOUD-UPCLOUD` / `M-CLOUD-ADAPTERS` / `M-CLOUDS-HUB` / `M-CLOUD-UTILS` / `M-CLOUD-PROTOCOLS` module entries. Update `M-APPLICATION-*` and `M-DI` dependencies to remove `M-REMOTE-REPO`, `M-REMOTE`, `M-CLOUD-MANAGER`. Update `M-SSH-GATEWAY` dependencies to remove `M-REMOTE`.
- [x] 6.5 Update `docs/ARCHITECTURE.md` — remove Phase 4 from remaining work. Mark SSH/cloud adapters as done. Remove `remote_machine/` and `clouds/` from project structure.

## 7. Verification

- [x] 7.1 Run `uv run -m unit` — all tests pass.
- [x] 7.2 Run `uv run zuban check` and `uv run ruff check .` — no lint errors.
- [x] 7.3 Run `python3 scripts/grace_check.py` — GRACE-lite validation passes.
- [x] 7.4 Run `openspec validate --all --json` — spec validation passes.
