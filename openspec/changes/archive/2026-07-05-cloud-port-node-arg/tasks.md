## 1. Port contract (domain)

- [x] 1.1 In `yascheduler/domain/ports.py`, change `CloudProvisioner.allocate` signature from `allocate(self, provider: str, tmp_node_id: NodeId) -> Node` to `allocate(self, provider: str, node: Node) -> Node`; change `deallocate(self, cloud: str, ip: str) -> None` to `deallocate(self, node: Node) -> None`. Ensure `Node` is imported (it is already used as the return type).
- [x] 1.2 Update the `CloudProvisioner` docstring in `ports.py` to describe: `allocate` receives the tmp-node `Node` (reusing its `node_id`), `deallocate` reads `node.cloud`/`node.ip` internally and no-ops on `cloud is None`. Remove the stale `deallocate(cloud, ip)` / "enriching it to carry external_id/Node is a future change" wording.
- [x] 1.3 Bump the `ports.py` MODULE_CONTRACT VERSION and add a CHANGE_SUMMARY entry (cloud-port-node-arg).

## 2. Adapter (infra)

- [x] 2.1 In `yascheduler/infra/cloud/manager.py` `allocate`, change the signature to `allocate(self, provider: str, node: Node) -> Node`. Replace the fresh `Node(node_id=tmp_node_id, ip=ip_addr, ncpus=0, enabled=False, cloud=adapter.name, username=config.username, port=22)` construction (lines ~200-208) with `node = replace(node, ip=ip_addr, cloud=adapter.name, username=config.username)`. Rename any internal `tmp_node_id` references to `node.node_id`.
- [x] 2.2 In `manager.py` `deallocate`, change the signature to `deallocate(self, node: Node) -> None`. Add a `node.cloud is None` warn-and-return guard, then resolve provider via `self.adapters.get(node.cloud)` / `self.configs.get(node.cloud)` (keep the existing unsupported/no-config warn-and-return branches), and call `adapter.delete_node(log=self.log, cfg=config, host=node.ip)`. Update all log lines to use `node_id`/`node.cloud`/`node.ip`.
- [x] 2.3 Update the `allocate`/`deallocate` function CONTRACT blocks, MODULE_CONTRACT SCOPE/MODULE_MAP, VERSION bump, and CHANGE_SUMMARY in `manager.py` to reflect the `node: Node` arguments.

## 3. Callers (application)

- [x] 3.1 In `yascheduler/application/allocate_task.py`, change `_TmpSelection` from `(name: str, node_id: NodeId)` to `(name: str, node: Node)`; update `_select_and_insert_tmp` to `return _TmpSelection(name=selected_name, node=tmp_node)`.
- [x] 3.2 Update `_allocate_cloud_node` to accept the tmp `Node` (replacing `selected_name`/`tmp_node_id` params as needed), call `clouds.allocate(selected_name, node)`, and clean up via `node.node_id` on failure. Keep `_cleanup_tmp_node_best_effort` taking `tmp_node_id: NodeId`.
- [x] 3.3 Update `_persist_node_with_cleanup` to call `clouds.deallocate(node)` (drop the `cloud_name = node.cloud or selected_name` fallback and the `selected_name` param if now unused).
- [x] 3.4 Update the `allocate_task` body: read the tmp `Node` from `selected.node`, thread it to `_allocate_cloud_node`, and derive `tmp_node_id` for the `finally` cleanup via `selected.node.node_id`.
- [x] 3.5 Update affected CONTRACT/MODULE_MAP/CHANGE_SUMMARY/VERSION markers in `allocate_task.py`.
- [x] 3.6 In `yascheduler/application/deallocate_nodes.py` `deallocate_node`, change `await clouds.deallocate(node.cloud, node.ip)` to `await clouds.deallocate(node)`. Update CONTRACT/CHANGE_SUMMARY/VERSION.
- [x] 3.7 In `yascheduler/application/abandon_node.py`, change `await clouds.deallocate(node.cloud, node.ip)` to `await clouds.deallocate(node)`. Update CONTRACT/CHANGE_SUMMARY/VERSION.

## 4. Tests

- [x] 4.1 Update the port test doubles: `FakeCloudProvisioner.allocate/deallocate` in `tests/unit/test_cloud_alloc_session_lifecycle.py` (~385, 421) and the stub in `tests/unit/test_domain_ports.py` (~336) to the new signatures.
- [x] 4.2 Update `tests/unit/test_cloud_provisioner_impl.py`: `prov.allocate("test", <Node>)` call sites (pass a tmp `Node` instead of `NodeId`) and `prov.deallocate(<Node>)` call sites (~275-483); add a test for `deallocate(node)` no-op when `node.cloud is None`.
- [x] 4.3 Update assertion call sites: `tests/unit/test_allocate_task_failure_modes.py` (~241-243: `clouds.allocate.assert_called_once_with(...)` and `clouds.deallocate.assert_called_once_with(...)`), `tests/unit/test_abandon_node.py` (~124, 173, 208: `clouds.deallocate.assert_awaited_once_with(...)`), `tests/integration/test_never_connected_node_abandon.py` (~214: `orch._clouds.deallocate.assert_awaited_once_with(...)`) to the new `deallocate(node)` / `allocate(provider, node)` shapes.
- [x] 4.4 Update `tests/unit/test_application_use_cases.py` for any `_TmpSelection`, `clouds.allocate`, or `clouds.deallocate` call-shape assertions.
- [x] 4.5 Run `uv run pytest -m unit` and `uv run pytest -m integration` (SSH/Postgres testcontainers) — all green.

## 5. GRACE + docs

- [x] 5.1 Update `docs/knowledge-graph.xml`: `<class-CloudProvisioner>` PURPOSE (line ~399) and `<export-CloudProvisioner>` PURPOSE to the new `allocate(provider, node: Node)` / `deallocate(node: Node)` signatures.
- [x] 5.2 Update `docs/ARCHITECTURE.md` if it names the `allocate(tmp_node_id)` / `deallocate(cloud, ip)` signatures.
- [x] 5.3 Run `python3 scripts/grace_check.py` — exit 0.

## 6. Static checks + spec sync

- [x] 6.1 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` — all pass.
- [x] 6.2 Run `openspec validate cloud-port-node-arg` — valid.
