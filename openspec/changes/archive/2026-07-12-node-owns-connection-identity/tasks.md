## 1. SSH repository — Protocol and implementation

- [x] 1.1 Modify `MachineRepository` Protocol in `yascheduler/domain/ports.py`: drop `jump_host` / `jump_username` keyword arguments from `connect` signature; update docstring to state jump identity is read from `node`
- [x] 1.2 Rewrite `_resolve_tunnel` → `_build_tunnel_options(node, client_keys, connect_timeout) -> SSHClientConnectionOptions | None` in `yascheduler/infra/ssh/repository.py`: returns `None` when `node.jump_host is None`; otherwise builds `SSHClientConnectionOptions(options=DEFAULT_CONN_OPTS, host=node.jump_host, port=node.jump_port, username=node.jump_username, client_keys=client_keys or (), known_hosts=None, connect_timeout=connect_timeout)`
- [x] 1.3 Drop `jump_host` / `jump_username` parameters from `SSHMachineRepository.connect`, `_connect_impl`, and `_open_connection`; thread `node` into `_open_connection` (or read jump fields at the `connect`/`_connect_impl` layer and pass the built options object down)
- [x] 1.4 Update `_open_connection` body: pass the `_build_tunnel_options(...)` result to asyncssh `tunnel=` (in the `connect()` call and/or via `SSHClientConnectionOptions(tunnel=...)`); remove the old `_resolve_tunnel(jump_host, jump_username)` string-form call
- [x] 1.5 Update `START_CONTRACT: SSHMachineRepository.connect` / `_open_connection` blocks: input lists drop `jump_host` / `jump_username`, add `node` (for jump fields); update `START_BLOCK_BUILD_OPTS` / `START_BLOCK_CONNECT` markers and structured-log fields
- [x] 1.6 Update `LAST_CHANGE` / `CHANGE_SUMMARY` in `repository.py` and `ports.py`

## 2. Orchestrator — drop inline jump resolution

- [x] 2.1 In `yascheduler/application/orchestrator.py` `_connect_machine_consumer`: delete the `jump_host = self._remote_defaults.jump_host` / `jump_username = self._remote_defaults.jump_username` / `for cloud in self._config_clouds: if cloud.prefix == node.cloud: ...` block
- [x] 2.2 Update the `repository.connect(...)` call site to drop `jump_host=...` / `jump_username=...` kwargs (keep `node=`, `client_keys=`, `connect_timeout=10`, `data_dir=`, `engines_dir=`, `tasks_dir=`)
- [x] 2.3 Remove now-unused `_remote_defaults.jump_host` / `_remote_defaults.jump_username` reads from this method (leave `_remote_defaults.data_dir` / `engines_dir` / `tasks_dir` — those are still kwargs); if `_config_clouds` becomes unused on the orchestrator, leave the attribute (still used by allocator path)
- [x] 2.4 Update contract / block anchors / `CHANGE_SUMMARY` for the method

## 3. CLI `check_status` — drop `_resolve_conn_params`

- [x] 3.1 Delete `_resolve_conn_params(node, config) -> _ConnParams` and the `_ConnParams` dataclass fields `jump_host` / `jump_username` (keep the class only if other fields are still needed; otherwise inline the two remaining values at the call site)
- [x] 3.2 Update `_display_remote_output`: drop `conn_params` parameter; the `repository.connect(node=node, client_keys=..., ...)` call passes no jump kwargs (reads from `node`)
- [x] 3.3 Update `_render_view`: the `else` branch (no allocated node) currently builds `_ConnParams(username=config.remote.username, port=22, jump_host=config.remote.jump_host, jump_username=config.remote.jump_username)` — this branch is for tasks with no allocated node and never connects; either remove the unused jump fields from the local fallback shape or drop the conn-params object entirely if username/port become unused too
- [x] 3.4 Remove the `NOTE:` comment about "Promotion to a shared helper awaits a third consumer" (the helper is being deleted, not promoted)
- [x] 3.5 Update `START_CONTRACT: _display_remote_output` / `_render_view` input lists and `CHANGE_SUMMARY`

## 4. CLI `manage_node` — stamp jump on static `NewNode`

- [x] 4.1 In `_add_node` (or the `NewNode` construction site in `yascheduler/entrypoints/cli/manage_node.py`): resolve `jump_host = config.remote.jump_host`, `jump_username = config.remote.jump_username`, `jump_port = 22` from the parsed `config`
- [x] 4.2 Pass `jump_host=`, `jump_username=`, `jump_port=` into the `NewNode(...)` constructor alongside `hostname`, `port`, `username`, `ncpus`, `enabled=False`
- [x] 4.3 Confirm `repository.connect(node=tmp, client_keys=..., engines_dir=..., ...)` currently has no jump kwargs (it does not today); the tmp row's `jump_*` carries them after 4.1-4.2
- [x] 4.4 Update contract / `CHANGE_SUMMARY`

## 5. Cloud manager — stamp jump on cloud `Node` BEFORE setup connect; drop connect kwargs

- [x] 5.1 In `yascheduler/infra/cloud/manager.py` `_setup_vm`: BEFORE the call to `_connect_to_vm(node, adapter, config)` at line 352, resolve jump from the matching `CloudConfig` (`prefix == node.cloud`) if it sets BOTH `jump_host` and `jump_username`, else fall back to `self.remote_config.jump_host` / `self.remote_config.jump_username`; `jump_port = 22`. Stamp via `node = replace(node, jump_host=jump_host, jump_username=jump_username, jump_port=jump_port)` so the `_connect_to_vm` setup SSH session (cloud-init wait, `setup_node`, `get_cpu_cores`) opens through the bastion. This ordering is CRITICAL — the cloud spec requires "BEFORE the connect-setup SSH session is opened" (see Risks in design.md).
- [x] 5.2 The final `return replace(node, enabled=True, ncpus=ncpus)` at line 412 does NOT need to re-stamp jump — frozen-dataclass `replace` preserves the earlier stamp from 5.1. Verify by assertion or unit test that the returned `Node` carries `jump_host` / `jump_username` / `jump_port` from 5.1.
- [x] 5.3 In `_connect_to_vm` (lines 426-456): update `machine_repository.connect(node=node, client_keys=keys, connect_timeout=adapter.create_node_conn_timeout, data_dir=..., engines_dir=..., tasks_dir=...)` — drop the `jump_host=config.jump_host or None` / `jump_username=config.jump_username or None` kwargs (they were at lines 454-455). The node passed in already carries the stamped identity from 5.1.
- [x] 5.4 Decision: stamp in `_setup_vm` (site a) per 5.1, OR alternatively in `allocate` at the identity-establishing `replace` (manager.py:186-192). If choosing site (b), extend that `replace` with jump fields; widen `allocate`'s access to `config`/resolved-jump as needed; the `_setup_vm` connect path still reads stamped `node.jump_*`. Document the chosen site in the contract CHANGE_SUMMARY.
- [x] 5.5 Update `START_CONTRACT: CloudProvisionerImpl._setup_vm` / `_connect_to_vm` / `allocate` (whichever gained the stamping responsibility per 5.4) input+output lists; update `CHANGE_SUMMARY`

## 6. Unit tests — pure behavior

- [x] 6.1 `tests/unit/test_ssh_gateway.py` (or a new `test_ssh_repository.py`): add tests for `_build_tunnel_options` — returns `None` when `node.jump_host is None`; builds options with `host=node.jump_host`, `port=node.jump_port`, `username=node.jump_username`, the same `client_keys` / `known_hosts` / `connect_timeout` as the destination; inherits `DEFAULT_CONN_OPTS` (keepalive/compression)
- [x] 6.2 Update existing SSH-repository tests: drop `jump_host=` / `jump_username=` from `repository.connect(...)` mock calls; assert jump is read from the `node` fixture instead
- [x] 6.3 `tests/unit/test_connect_machine_consumer.py`: remove assertions that `connect` was called with `jump_host=` / `jump_username=`; assert the call shape is `connect(node=node, client_keys=keys, connect_timeout=10, data_dir=..., engines_dir=..., tasks_dir=...)`; remove any cloud-prefix-resolution setup
- [x] 6.4 `tests/unit/test_cli_check_status.py`: drop `remote_jump_host=` / `cloud.jump_host=` fixtures from the connect-path tests; assert `_resolve_conn_params` no longer exists — DELETE THE WHOLE `TestResolveConnParams` CLASS (lines ~646-713, including `test_matching_cloud_uses_cloud_jump_host`, the fallback tests, AND `test_returns_node_username_not_cloud_username` / `test_returns_node_port` which are all bound to the deleted helper); replace with `test_connect_reads_jump_from_node`
- [x] 6.5 `tests/unit/test_cloud_provisioner_impl.py`: update `_setup_vm` tests — drop `jump_host=...` / `jump_username=...` from the expected `machine_repository.connect(...)` kwargs; assert the returned `Node` carries `jump_host` / `jump_username` stamped from the matching `CloudConfig` (or `[remote]` fallback); keep `cfg_cloud.jump_host = None` setup only where it confirms the fallback path
- [x] 6.6 `tests/unit/test_cloud_alloc_session_lifecycle.py`: drop `config.jump_host = None` setup lines if they exist to silence the old kwargs; assert session lifecycle is unaffected by the jump-stamping change
- [x] 6.6a `tests/unit/test_domain_ports.py`: drop `jump_host: str | None = None` / `jump_username: str | None = None` parameters from `StubMachineRepository.connect` (lines 240-253). `@runtime_checkable` won't catch the divergence, but the ssh-infrastructure spec scenario "Repository satisfies Protocol structurally" requires no jump kwargs on `connect` — the stub must mirror the new contract. Consider adding an `inspect.signature` assertion to lock the contract.
- [x] 6.7 Add a unit test for static-node stamping in `tests/unit/test_cli_manage_node.py` (or equivalent): when `config.remote.jump_host` is set, the `NewNode` passed to `uow.nodes.insert` carries `jump_host` / `jump_username` / `jump_port=22`; when `config.remote.jump_host is None`, the `NewNode.jump_host is None`
- [x] 6.8 Add a unit test for cloud-node stamping: when the matching `CloudConfig` sets jump, `_setup_vm` stamps `node.jump_*` BEFORE `_connect_to_vm` is called (assert the node passed to `_connect_to_vm` / `machine_repository.connect` carries the cloud's jump, not None); when `CloudConfig` does NOT set jump and `config.remote.*` does, the stamp carries the remote fallback
- [x] 6.9 Update `tests/unit/test_domain_model.py` only if `Node` field assertions changed — the field list itself is unchanged, but new scenarios (`Static node stamps jump from remote defaults at creation`, etc.) get one assertion test each per the spec scenarios in `domain-entities` delta
- [x] 6.10 Add a regression test for the cloud-first-connect ordering bug: construct a node with `jump_host=None`, call `_setup_vm`, and assert the stamp happens before `_connect_to_vm` (e.g. mock `_connect_to_vm` to capture the node snapshot it received and assert `node.jump_host` is already set)

## 7. Integration / e2e tests — multi-layer behavior

- [x] 7.1 Audit `tests/integration/` and `tests/e2e/` for `repository.connect(...)` calls with `jump_host=` / `jump_username=`; update signatures
- [x] 7.2 If there is an SSH-bastion testcontainers setup, add an e2e that: creates a node with `jump_host` set on the row, runs the connect path, and asserts the bastion leg is used (otherwise document that bastion e2e is not feasible in CI and cover via unit tests only)

## 8. GRACE-lite knowledge graph and module contracts

- [x] 8.1 Update `docs/knowledge-graph.xml` only if a module's public surface changed at the graph level: `M-SSH-REPOSITORY` (connect signature in `<annotations>`), `M-ENTRYPOINTS-CLI-CHECK-STATUS` (`_resolve_conn_params` removed), `M-ENTRYPOINTS-CLI-MANAGE-NODE` (NewNode construction surface), `M-CLOUD-PROVISIONER` (`_setup_vm`/`_connect_to_vm` annotations — NOTE: the actual graph ID is `M-CLOUD-PROVISIONER`, NOT `M-CLOUD-MANAGER`). Add `CrossLink` entries if dependency edges shifted.
- [x] 8.2 Run `python3 scripts/grace_check.py` — exit 0 required

## 9. Static checks and spec validation

- [x] 9.1 `uv run pytest -m unit` — all green
- [x] 9.2 `uv run pytest -m integration` — all green (or skipped if no testcontainers)
- [x] 9.3 `uv run zuban check` — clean
- [x] 9.4 `uv run ruff check .` — clean
- [x] 9.5 `uv run ruff format --check .` — clean
- [x] 9.6 `uv run lint-imports` — clean
- [x] 9.7 `openspec validate --all --json` — exit 0
- [x] 9.8 `python3 scripts/grace_check.py` — exit 0 (duplicate of 8.2; re-run after any final edits)

## 10. Documentation

- [x] 10.1 Update `README.md` jump-host section (line ~248, ~290) to clarify that `jump_host` is now stamped at node creation from `[remote]` / `[engine.*]` defaults, not re-read at runtime; note the operational consequence (INI changes do not propagate to existing nodes)
- [x] 10.2 Update `CLOUD.md` (lines ~103, ~144) if the description of `az_jump_host` / `vastai_jump_host` suggests runtime resolution; clarify values are read once at allocation and persisted on the node
- [x] 10.3 Scan `docs/ARCHITECTURE.md` (line ~82 mentions `username`, `jump_username`, `jump_host` as cloud DTO fields) — confirm wording still accurate
