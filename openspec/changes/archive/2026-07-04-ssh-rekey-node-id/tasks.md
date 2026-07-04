## 1. Prerequisite: commit task-allocated-node-id

- [x] 1.1 Verify `task-allocated-node-id` change is implemented and its 58 tasks are checked in the working tree
- [x] 1.2 Run `uv run pytest -m unit -m integration` on the working tree to confirm task-allocated-node-id is green
- [x] 1.3 Commit the `task-allocated-node-id` working-tree changes (code + tests + migration 004 + openspec artifacts) so this change starts from a clean tree
- [x] 1.4 Confirm `git status` is clean before starting ssh-rekey-node-id implementation

## 2. Domain layer: ConnectedMachine + events

- [x] 2.1 Add `node_id: NodeId` as the first field of `ConnectedMachine` in `yascheduler/domain/model.py`; update `occupy`/`release`/`replace()` to carry `node_id` (verify `replace(self, state=…)` preserves it automatically via frozen dataclass); add `node_id` to `MachineBusyError(self.ip)` log sites where the session machine is in hand (optional correlation)
- [x] 2.2 Update `Node` docstring in `domain/model.py` (ip-keyed lookup methods `get`/`get_by_ips` removed; `node_id` is the sole identity; `ip` is the transport attribute)
- [x] 2.3 Update `NewNode` docstring (cloud adapter reuses `tmp_node_id` as real node identity; returns `Node` not `NewNode`)
- [x] 2.4 Flip `TaskAllocated.node_ip: str → node_id: NodeId` in `yascheduler/domain/events.py`
- [x] 2.5 Flip `TaskAbandoned.node_ip: str → node_id: NodeId` in `yascheduler/domain/events.py`
- [x] 2.6 Update `Task.with_event` overloads for `TaskAllocated`/`TaskAbandoned` (`node_id` kwarg instead of `node_ip`)
- [x] 2.7 Update unit tests `tests/unit/test_domain_events.py`, `tests/unit/test_domain_model.py` (ConnectedMachine carries node_id; occupy/release preserve it; two machines sharing ip are distinct; TaskAllocated/TaskAbandoned carry node_id)

## 3. Domain ports: NodeRepository + MachineRepository + CloudProvisioner

- [x] 3.1 In `yascheduler/domain/ports.py`, remove `NodeRepository.get(ip: str)` and `NodeRepository.get_by_ips(ips: list[str])` from the Protocol; add `get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]`; keep `get_by_id(node_id)` unchanged; update the `NodeRepository` docstring (no ip-keyed lookups)
- [x] 3.2 In `yascheduler/domain/ports.py`, rekey `MachineRepository` Protocol: `connect(node: Node, username, client_keys, *, port=22, …) -> MachineSession`; `disconnect(node_id: NodeId) -> None`; `get_session(node_id: NodeId) -> MachineSession | None`; `contains(node_id: NodeId) -> bool`; `__contains__(node_id: NodeId) -> bool`. `disconnect_all`, `list_free`, `list_connected`, `__len__` keep signatures
- [x] 3.3 In `yascheduler/domain/ports.py`, change `CloudProvisioner.allocate` signature: `allocate(provider: str, tmp_node_id: NodeId) -> Node` (was `allocate(provider: str) -> NewNode`); keep `deallocate(cloud, ip)` and `select_provider` unchanged; update the port docstring (single-row UPDATE lifecycle; `deallocate` stays ip-keyed — cloud SDK host)
- [x] 3.4 Update `tests/unit/test_domain_ports.py` for the new signatures (structural subtyping assertions for NodeRepository, MachineRepository, CloudProvisioner)

## 4. SSH infrastructure: SSHMachineRepository + SSHMachineSession

- [x] 4.1 In `yascheduler/infra/ssh/repository.py`, rekey `_sessions: dict[str, SSHMachineSession] → dict[NodeId, SSHMachineSession]`
- [x] 4.2 Change `connect(node: Node, username, client_keys, *, port=22, …) -> MachineSession` — pass `node.ip` into `_open_connection` (asyncssh host unchanged); construct `ConnectedMachine(node_id=node.node_id, ip=node.ip, platform=…, ncpus=…, state=FREE, free_since=…)`; store under `_sessions[node.node_id]`
- [x] 4.3 Change `disconnect(node_id: NodeId) -> None` — pop `_sessions[node_id]`, delegate to `session._close()` (pop-before-await ordering preserved)
- [x] 4.4 Change `_connect_impl` to take `node: Node` (thread `node` through where `ip` was threaded)
- [x] 4.5 Change `get_session(node_id) -> MachineSession | None`, `contains(node_id) -> bool`, `__contains__(node_id) -> bool` to key by `NodeId`
- [x] 4.6 Change `disconnect_all` to iterate `list(self._sessions)` (NodeId keys) — unchanged logic
- [x] 4.7 Keep `SSHMachineSession` in `infra/ssh/session.py` UNCHANGED (no `node_id` attribute — clean); it already receives `ConnectedMachine` via `_machine` and `session.machine.node_id` reading is transparent
- [x] 4.8 Keep `MachineConnectionError(ip, reason)` ip-keyed — read `ip` from `node.ip` at the raise site in `connect`'s `except` clause
- [x] 4.9 Update `MachineRepository` Protocol docstring (keyed by NodeId; `ip` survives only as `node.ip` read inside `connect` for the asyncssh transport address)
- [x] 4.10 Update unit tests `tests/unit/test_ssh_gateway*.py` for the new `connect(node, …)`/`disconnect(node_id)`/`get_session(node_id)`/`contains(node_id)` signatures

## 5. Cloud: CloudProvisionerImpl + adapters

- [x] 5.1 In `yascheduler/infra/cloud/manager.py`, change `allocate(provider: str, tmp_node_id: NodeId) -> Node`; thread `tmp_node_id` into `_setup_vm(ip_addr, tmp_node_id, adapter, config)` and `_connect_to_vm(ip_addr, tmp_node_id, adapter, config)`
- [x] 5.2 In `_connect_to_vm`, call `self.machine_repository.connect(node=Node(node_id=tmp_node_id, ip=ip_addr, ncpus=0, enabled=False, cloud=adapter.name, username=config.username, port=22), username=config.username, …)` — session registers under `tmp_node_id`
- [x] 5.3 In `_setup_vm`, after cloud-init/setup/get_cpu_cores, return `Node(node_id=tmp_node_id, ip=ip_addr, enabled=True, ncpus=…, cloud=adapter.name, username=config.username, port=22)` (a `Node`, NOT `NewNode`)
- [x] 5.4 In `allocate`'s two setup-failure `except` blocks, change `await self.machine_repository.disconnect(ip_addr)` → `await self.machine_repository.disconnect(tmp_node_id)` (BEFORE `adapter.delete_node`)
- [x] 5.5 Keep `CloudProvisionerImpl.stop()` unchanged (calls `machine_repository.disconnect_all()`)
- [x] 5.6 Keep `deallocate(cloud, ip)` unchanged (ip = cloud SDK host)
- [x] 5.7 Update `tests/unit/test_cloud_provisioner_impl.py`, `tests/unit/test_cloud_alloc_session_lifecycle.py` for `allocate(provider, tmp_node_id) -> Node`, `_connect_to_vm` session registered under `tmp_node_id`, setup-failure disconnect-by-tmp_node_id, success path session survives for orchestrator reuse

## 6. Persistence: PostgresNodeRepository + SQL

- [x] 6.1 In `yascheduler/infra/persistence/postgres.py`, remove `get(ip)` and `get_by_ips(ips)` from `PostgresNodeRepository`; remove their SQL bindings (`get_by_ip.sql`, `get_by_ips.sql`)
- [x] 6.2 Add `get_by_ids(node_ids: list[NodeId]) -> dict[NodeId, Node]` to `PostgresNodeRepository` — run `load_query("node/get_by_ids")` with `node_ids=[n.value for n in node_ids]`; build `{NodeId(int(row["node_id"])): self._row_to_node(row) for row in rows}`; empty-list returns empty dict
- [x] 6.3 Create `yascheduler/infra/persistence/sql/node/get_by_ids.sql`: `SELECT node_id, ip, ncpus, enabled, cloud, username, port FROM yascheduler_nodes WHERE node_id = ANY(:node_ids)`
- [x] 6.4 Delete `yascheduler/infra/persistence/sql/node/get_by_ip.sql` and `yascheduler/infra/persistence/sql/node/get_by_ips.sql`
- [x] 6.5 Keep `get_by_id(node_id)`, `insert`, `update`, `enable`, `disable`, `remove`, `list_enabled`, `list_disabled`, `list_all`, `count_by_status`, `count_by_cloud` unchanged
- [x] 6.6 Update `tests/integration/test_persistence_adapter.py` (remove `get`/`get_by_ips` tests; add `get_by_ids` tests including empty-list, missing-node, multi-node batch)

## 7. Use cases: allocate_task, consume_task, deallocate_nodes, abandon_node

- [x] 7.1 In `yascheduler/application/allocate_task.py`, change `_provision_and_persist` to call `clouds.allocate(selected_name, tmp_node_id) -> Node` (pass the `tmp_node_id`), then `_persist_node_with_cleanup(node)` which does a single `uow.nodes.update(node)` + commit (flips enabled=TRUE, sets ip/ncpus) — REMOVE the `insert(NewNode) + remove(tmp_node_id)` pair; on persist-failure best-effort `clouds.deallocate(cloud_name, node.ip)` + `_cleanup_tmp_node_best_effort(tmp_node_id)`, re-raise
- [x] 7.2 Change `_allocate_cloud_node` to call `clouds.allocate(selected_name, tmp_node_id)`; on failure `_cleanup_tmp_node_best_effort(tmp_node_id)`, re-raise
- [x] 7.3 In `_find_free_machines`: build `nodes_by_id = {n.node_id: n for n in enabled_nodes}` (was `nodes_by_ip`); build `busy_node_ids = {t.allocated_node_id for t in running_tasks if t.allocated_node_id}` (was `busy_node_ips`); pair sessions via `nodes_by_id[s.machine.node_id]` filtered by `s.machine.node_id in nodes_by_id and s.machine.node_id not in busy_node_ids`
- [x] 7.4 In `_try_start_on_machine`, keep `(session, node)` shape; update `TaskAllocated` emission: `task.with_event(TaskAllocated, node_id=node.node_id, engine_name=task.context.engine)` (was `node_ip=session.ip`)
- [x] 7.5 In `yascheduler/application/consume_task.py`: CONFIRM (no signature change needed — `consume_task` already takes `session: MachineSession` directly and the orchestrator already resolves it via `get_session` and passes `session=session`; lines 216-224). Verify the orchestrator now resolves via `get_session(task.allocated_node_id)` (covered by task 8.5). Update `TaskCompleted`/`TaskFailed` emissions (unchanged fields — verify). Update docstring/contract if stale.
- [x] 7.6 In `yascheduler/application/deallocate_nodes.py`: change `idle_machines: dict[str, float] -> dict[NodeId, float]`; `busy_ips -> busy_node_ids = {t.allocated_node_id for t in running_tasks if t.allocated_node_id}`; phase-1 disable matches by `node.node_id in idle_machines` and `node.node_id not in busy_node_ids`; phase-2 filter `node.node_id not in busy_node_ids and node.cloud`. Remove any `"." in node.ip` post-filter (already removed but verify).
- [x] 7.7 In `yascheduler/application/deallocate_nodes.py`, the `deallocate_node` function (NOT a separate module): rekey `repository.contains(node.ip)`/`repository.disconnect(node.ip)` → `repository.contains(node.node_id)`/`repository.disconnect(node.node_id)`. These calls are ALREADY before the `if node.cloud:` guard (`deallocate_nodes.py:56-62`, guard at L63) — only the key argument changes from `node.ip` to `node.node_id`; no re-ordering needed.
- [x] 7.8 In `yascheduler/application/abandon_node.py`: change stuck-task matching `matching = [t for t in todo_tasks if t.allocated_node_id == node.node_id]` (was `t.allocated_ip == node.ip`); keep `clouds.deallocate(node.cloud, node.ip)` (ip = cloud SDK host); keep `uow.nodes.remove(node.node_id)`
- [x] 7.9 Update unit tests `tests/unit/test_application_use_cases.py`, `tests/unit/test_allocate_task_node_pairing.py`, `tests/unit/test_application_orchestrator.py` for: V1 single-row UPDATE in cloud path; `_find_free_machines` nodes_by_id with dup-IP disambiguation; deallocate busy_node_ids matching; abandon matching by allocated_node_id; consume_task takes session

## 8. Orchestrator

- [x] 8.1 In `yascheduler/application/orchestrator.py`, change `_occupancy_started: set[str] -> set[NodeId]` and key it by `task.allocated_node_id`
- [x] 8.2 Change `_connect_failures: dict[str, float] -> dict[NodeId, float]` and key it by `node.node_id`
- [x] 8.3 In `_connect_machine_producer`: filter `new_nodes = [n for n in enabled_nodes if not self._repository.contains(n.node_id)]`; yield `UMessage(n.node_id, n)` (was `UMessage(n.ip, n)`)
- [x] 8.4 In `_connect_machine_consumer`: call `self._repository.connect(node=node, username=node.username, client_keys=keys, …, port=node.port, …)` (pass the `Node`); `_connect_failures.pop(node.node_id, …)`; static-node retry branch keyed by `node.node_id`; grace-check `self._connect_failures.setdefault(node.node_id, time.monotonic())`; `abandon_node(node, self._clouds, self._uow_factory, self._tracker)`; `_connect_failures.pop(node.node_id, None)`
- [x] 8.5 In `_task_consumer_consumer`: `node_id = task.allocated_node_id`; `session = self._repository.get_session(node_id)` (was `ip = task.allocated_ip`); `_occupancy_started.add(node_id)` (was ip); `_occupancy_started.discard(node_id)` on finalise; `TaskAbandoned` emission `task.with_event(TaskAbandoned, node_id=node_id)` (was `node_ip=ip`)
- [x] 8.6 In `_start_task_on_machine`: `node = await uow.nodes.get_by_id(task.allocated_node_id)` (was `uow.nodes.get(task.allocated_ip or "")`); fall back to `operations.get_cpu_cores(session)` when `node is None`
- [x] 8.7 In `_deallocator_producer`: build `idle_machines: dict[NodeId, float] = {s.machine.node_id: s.machine.free_since for s in list_connected() if FREE and free_since is not None}` (was `s.machine.ip`); pass to `deallocate_nodes`
- [x] 8.8 In `_deallocator_consumer`: keep `deallocate_node(node, self._repository, self._clouds, self._uow_factory)`; remove any `self._repository.contains(ip)`/`disconnect(ip)` fallback (verify absent per spec); keep the `try/except Exception` log with `node_id`/`ip`
- [x] 8.9 Update `_connect_grace_for` (no change — keyed by `cloud`, not ip); keep `_conn_machine_q: UniqueQueue[NodeId, Node]` (was `UniqueQueue[str, Node]`)
- [x] 8.10 Update unit tests `tests/unit/test_orchestrator_producer_resilience.py`, `tests/unit/test_orchestrator_consumer_resilience.py`, `tests/unit/test_connect_machine_consumer.py`, `tests/unit/test_queue.py` for NodeId-keyed state, get_session(allocated_node_id), connect(node), get_by_id ncpus resolution, idle_machines dict[NodeId]

## 9. CLI: check_status, show_nodes, manage_node

- [x] 9.1 In `yascheduler/entrypoints/cli/check_status.py`: `_check_status_async` query-phase UoW builds `nodes_by_id = await uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if t.allocated_node_id])` (was `get_by_ips([t.allocated_ip…])`); `_render_json`/`_render_view` look up `nodes_by_id.get(task.allocated_node_id)` (was `nodes_by_ip.get(task.allocated_ip)`); keep `allocated_ip` in the JSON object (transport display)
- [x] 9.2 In `_display_remote_output`: resolve `node = nodes_by_id.get(task.allocated_node_id)`; build `_ConnParams` from node; `SSHMachineRepository().connect(node, …)` (was `connect(ip=…)`, the node is the task's resolved node); finally `repository.disconnect(session.machine.node_id)` (was `disconnect(session.ip)`)
- [x] 9.3 In `yascheduler/entrypoints/cli/show_nodes.py`: `_fetch_nodes_view` builds `tasks_by_node_id = {t.allocated_node_id: t for t in tasks if t.allocated_node_id is not None}`; `task = tasks_by_node_id.get(node.node_id)` (was `tasks_by_ip.get(node.ip)`); row/columns unchanged
- [x] 9.4 In `yascheduler/entrypoints/cli/manage_node.py` `_add_node`: adopt V1-pattern — insert `NewNode(ip=spec.host, port=spec.port, username=username, ncpus=…, enabled=False) -> Node(T)` + commit (UoW#1); `repository.connect(node=T, …)`; optional `operations.setup_node(session, …)`; `uow.nodes.update(Node(node_id=T.node_id, ip=spec.host, port=spec.port, username=username, ncpus=…, enabled=True, …))` + commit (UoW#2); print; finally `repository.disconnect(T.node_id)`; on connect-failure best-effort `uow.nodes.remove(T.node_id)` + commit, re-raise
- [x] 9.5 In `_manage_node_async` validation UoW: host_spec path resolves node via `get_by_id` after a host-spec lookup (the ip-keyed `get(spec.host)` is removed — resolve via the existing `NodeTarget` host_spec branch producing a `Node`, or by listing+filtering); the node_id path stays `get_by_id(target.node_id)`; pass the resolved `Node` to remove helpers
- [x] 9.6 Update unit tests `tests/unit/test_cli_check_status*.py`, `tests/unit/test_cli_show_nodes*.py`, `tests/unit/test_cli_manage_node*.py` for the new flows

## 10. Integration / e2e tests

- [x] 10.1 Add/update `tests/integration/test_persistence_adapter.py` for `get_by_ids` (batch, empty list, missing nodes) and the removed `get`/`get_by_ips`
- [x] 10.1b Migrate `tests/integration/test_db_integration.py` off `get`/`get_by_ips`: `test_add_and_get_node`, `test_has_node`, `test_enable_disable_node`, `test_remove_node` at lines 82/135/136/159/168/187/192 and `test_get_tasks_with_cloud_by_id_status` at line 565 (`get_by_ips`) → use `get_by_id`/`get_by_ids` instead
- [x] 10.1c Migrate `tests/integration/test_never_connected_node_abandon.py:206` (`uow.nodes.get(dead_ip)`) to `get_by_id`
- [x] 10.2 Add integration test for the cloud allocation lifecycle: tmp-node row inserted (enabled=False, ip=""), clouds.allocate reuses tmp_node_id, single-row UPDATE flips enabled=True + ip + ncpus; verify only ONE row exists in yascheduler_nodes per cloud allocation; verify `remove(tmp_node_id)` cleans up on failure
- [x] 10.3 Update `tests/e2e/test_full_cycle.py` (submit→allocate→consume→done) for node_id-keyed SSH and persistence
- [x] 10.4 Add e2e test for dup-IP disambiguation: two enabled nodes sharing one ip (different jump hosts), two free sessions — both are returned by `_find_free_machines` as distinct `(session, Node)` pairs (no collapse)
- [x] 10.5 Update `tests/e2e/test_consume_retry.py` for the new `get_session(node_id)` consume resolution AND migrate line 326 `uow.nodes.get(ssh_container["host"])` to `get_by_id` (resolve the Node by node_id, not the host)
- [x] 10.6 Run `uv run pytest -m unit`, `uv run pytest -m integration`, `uv run pytest -m e2e` — all green

## 11. Static checks + GRACE-lite + OpenSpec validation

- [x] 11.1 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` — all clean
- [x] 11.2 Update `docs/knowledge-graph.xml`: `M-SSH-REPOSITORY` purpose/annotations (`_sessions` key change, `node_id` key); `M-CLOUD-PROVISIONER` allocate contract (`tmp_node_id` -> Node); `M-DOMAIN-MODEL` (ConnectedMachine +node_id); `M-DOMAIN-EVENTS` (TaskAllocated/TaskAbandoned node_id); add/adjust CrossLinks for the rekey
- [x] 11.3 Update MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY on every touched source file (per GRACE-lite rules): `ssh/repository.py`, `ssh/session.py` (annotations only — no behavior change), `cloud/manager.py`, `persistence/postgres.py`, `domain/model.py`, `domain/ports.py`, `domain/events.py`, `application/orchestrator.py`, `application/allocate_task.py`, `application/consume_task.py`, `application/deallocate_nodes.py` (contains the `deallocate_node` function — same module), `application/abandon_node.py`, `entrypoints/cli/check_status.py`, `entrypoints/cli/show_nodes.py`, `entrypoints/cli/manage_node.py`
- [x] 11.4 Update GRACE-lite function contracts and semantic block anchors where signatures/logic changed (connect/disconnect/get_session/contains; allocate; get_by_ids; _find_free_machines; _task_consumer_consumer; _start_task_on_machine; _add_node)
- [x] 11.5 Run `python3 scripts/grace_check.py` — exit 0
- [x] 11.6 Run `openspec validate --all --json` — valid: true
- [x] 11.7 Final review pass on the diff: confirm no ip-keyed `_sessions`/`get_session`/`connect`/`disconnect`/`contains`/`get`/`get_by_ips` remnants outside the explicit "forever ip" sites (deallocate cloud-host, MachineConnectionError, check_status JSON `allocated_ip` display)

## 12. Archive preparation

- [x] 12.1 Confirm all tasks checked; all tests green; all static checks clean
- [x] 12.2 Run `/opsx-verify` to verify implementation matches the proposal artifacts
- [x] 12.3 Run `/opsx-archive` to archive the change and sync specs to `openspec/specs/`