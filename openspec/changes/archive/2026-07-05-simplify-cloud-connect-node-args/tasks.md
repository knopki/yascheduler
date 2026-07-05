# Tasks: simplify-cloud-connect-node-args

## 1. GRACE knowledge graph (top-down first)

- [x] 1.1 Update `docs/knowledge-graph.xml` `M-SSH-REPOSITORY` `<fn-connect>` PURPOSE (line ~1010) to state that `connect` reads the login user from `node.username` and the port from `node.port` and takes no `username`/`port` parameters.
- [x] 1.2 Update `M-CLOUD-PROVISIONER` `<class-CloudProvisionerImpl>` PURPOSE (line ~808) to note `allocate` constructs the identity `Node` once (after `create_node`), threads it through `_setup_vm`/`_connect_to_vm`, and returns `replace(node, enabled=True, ncpus)` — no ersatz `Node`.
- [x] 1.3 Verify no `<depends>`/`<CrossLink>` edges change (they do not — same modules, same call relationships); if a `fn-`/`class-` annotation names the old signature, update it. No new modules added.

## 2. Domain port: drop username/port from MachineRepository.connect

- [x] 2.1 In `yascheduler/domain/ports.py`, edit `MachineRepository.connect` (line ~274): remove the `username: str` positional param and the `port: int = 22` keyword param; keep `node`, `client_keys`, and all other kwargs. Remove the two `# FIXME: why username/port?` comments.
- [x] 2.2 Update the `connect` contract/docstring in `ports.py` to reflect that `node.username`/`node.port` are the source of the login user and port. Bump `VERSION` and add a `CHANGE_SUMMARY` entry in `ports.py`.

## 3. SSH repository: read node.username / node.port internally

- [x] 3.1 In `yascheduler/infra/ssh/repository.py`, edit `connect` (line ~149): remove `username`/`port` params and the two `# FIXME` comments; forward to `_connect_impl` without them.
- [x] 3.2 Edit `_connect_impl` (line ~199): remove `username`/`port` params and the two `# FIXME` comments; pass `node.username` and `node.port` into `_open_connection` (replacing the former `username`/`port` args at line ~216-224).
- [x] 3.3 Update the `connect`/`_connect_impl` GRACE contracts + `CHANGE_SUMMARY` in `repository.py` (bump VERSION); note the signature change and node-sourced user/port.

## 4. Cloud manager: single Node construction, drop ersatz

- [x] 4.1 In `yascheduler/infra/cloud/manager.py`, add `from dataclasses import replace` (verify import section).
- [x] 4.2 Edit `allocate` (line ~153): after `ip_addr = await adapter.create_node(...)`, construct `node = Node(node_id=tmp_node_id, ip=ip_addr, ncpus=0, enabled=False, cloud=adapter.name, username=config.username, port=22)`; call `await self._setup_vm(node, adapter, config)`.
- [x] 4.3 Change the two setup-failure `except` blocks (lines ~202-233) to `await self.machine_repository.disconnect(node.node_id)` (was `disconnect(tmp_node_id)`) before `delete_node`; update log fields to `node.node_id`/`node.ip`.
- [x] 4.4 Edit `_setup_vm` signature to `(self, node: Node, adapter, config)` (drop `ip_addr`, `tmp_node_id`); pass `node` to `_connect_to_vm`; use `node.ip` in cloud-init/error messages; return `replace(node, enabled=True, ncpus=ncpus)` instead of constructing a fresh `Node` (lines ~356-427).
- [x] 4.5 Edit `_connect_to_vm` signature to `(self, node: Node, adapter, config)` (drop `ip_addr`, `tmp_node_id`); remove the ersatz `Node(...)` construction and call `machine_repository.connect(node=node, client_keys=keys, connect_timeout=..., data_dir=..., engines_dir=..., tasks_dir=..., jump_host=..., jump_username=...)` with NO `username`/`port` args; use `node.ip` in the error message. Remove the `# FIXME: just use Node if you are already construct Node inside` comment.
- [x] 4.6 Update the `allocate`/`_setup_vm`/`_connect_to_vm` GRACE contracts, `MODULE_CONTRACT` scope line, and `CHANGE_SUMMARY` in `manager.py` (bump VERSION from 2.15.0); the public `allocate(provider, tmp_node_id)` signature and tmp-node UPDATE lifecycle are unchanged.

## 5. Call sites: stop passing username/port

- [x] 5.1 In `yascheduler/application/orchestrator.py` (`_connect_machine_consumer`, line ~285): remove `username=node.username` and `port=node.port` from the `connect(...)` call.
- [x] 5.2 In `yascheduler/entrypoints/cli/check_status.py` (`_display_remote_output`, line ~323): remove `username=conn_params.username` and `port=conn_params.port` from the `connect(...)` call. Keep `_ConnParams` and `_resolve_conn_params` (still supply `jump_host`/`jump_username`); leave `_ConnParams.username`/`.port` fields in place (Decision 3 — DTO unchanged).
- [x] 5.3 In `yascheduler/entrypoints/cli/manage_node.py` (`_add_node`, line ~321): remove `username=username` and `port=spec.port` from the `connect(...)` call. Verify the local `username` var is still used by the later `NewNode`/`update` (it is) so no unused-var lint fires.
- [x] 5.4 Bump `CHANGE_SUMMARY` (and VERSION where present) in `orchestrator.py`, `check_status.py`, `manage_node.py` module headers.

## 6. Test doubles and assertions

- [x] 6.1 In `tests/unit/test_domain_ports.py`, edit `StubMachineRepository.connect` (line ~241): remove `username`/`port` params to match the new port signature.
- [x] 6.2 In `tests/unit/test_cloud_alloc_session_lifecycle.py`, edit `FakeMachineRepository.connect` (line ~118): drop the `username` param (keep `**kwargs`); ensure `connect_calls`/session registration still key off `node`.
- [x] 6.3 Grep the whole `tests/` tree for `.connect(` and `connect(` usages and for `username=`/`port=` kwargs passed to a repository `connect`; update every call/assertion (candidates: `test_ssh_gateway*.py`, `test_cloud_provisioner_impl.py`, `test_allocate_task_failure_modes.py`). **Positional-arg hazard:** `tests/unit/test_ssh_gateway_connect.py` calls `gw.connect(node, "root", None)` with `username` as the 2nd positional arg — after the change `client_keys` becomes the 2nd positional param, so `"root"` would map to `client_keys` and `None` becomes an extra positional → `TypeError`. These calls use positional args, not kwargs; fix them by dropping the `"root"` arg (and shifting `None`/keys to the new 2nd positional slot or using `client_keys=` keyword).
- [x] 6.4 In `tests/unit/test_cloud_provisioner_impl.py`, update/add assertions: `allocate` constructs one `Node`, `_connect_to_vm` calls `connect(node=..., ...)` with no `username`/`port`, `_setup_vm` returns `replace(node, enabled=True, ncpus)`.

## 7. Focused tests for new behavior

- [x] 7.1 Add a unit test asserting `SSHMachineRepository.connect` reads `node.username`/`node.port` (e.g. a node with `username="yascheduler"`, `port=2222` reaches `_open_connection` with those values) — mock `_open_connection`.
- [x] 7.2 Add/extend a cloud unit test asserting the setup-failure `except` path calls `disconnect(node.node_id)` before `delete_node` (node_id == tmp_node_id) — covers the renamed disconnect arg.

## 8. Static checks and validation

- [x] 8.1 `uv run zuban check` — resolve any signature/type fallout (especially positional-arg shifts after dropping `username`).
- [x] 8.2 `uv run ruff check .` and `uv run ruff format --check .` — fix unused vars/imports left by removed params.
- [x] 8.3 `uv run lint-imports` — confirm no layering violation introduced.
- [x] 8.4 `uv run pytest -m unit` — all unit tests pass; then `uv run pytest -m integration` and `uv run pytest -m e2e` for the SSH/cloud/orchestrator paths (testcontainers).
- [x] 8.5 `python3 scripts/grace_check.py` — GRACE markup/graph validation passes (exit 0).
- [x] 8.6 `openspec validate simplify-cloud-connect-node-args --json` — passes; confirm the five modified requirement names still match main specs before archive/sync.
