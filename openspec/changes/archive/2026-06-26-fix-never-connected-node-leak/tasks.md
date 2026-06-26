## 1. CloudConfig Protocol + DTO defaults

- [x] 1.1 In `yascheduler/domain/ports.py`, add `connect_grace: int` to the `CloudConfig` Protocol between `idle_tolerance` and `username`; update the Protocol docstring's "6-field surface" wording to "7-field surface" and add `connect_grace` to the field list in the docstring
- [x] 1.2 In `yascheduler/infra/cloud/cloud_configs.py`, add `connect_grace: int = 60` to `ConfigCloudHetzner` and `ConfigCloudUpcloud`, and `connect_grace: int = 120` to `ConfigCloudAzure` and `ConfigCloudVastAI` (place each next to its `idle_tolerance` field for locality)
- [x] 1.3 Update the `START_MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` blocks in `ports.py` for the Protocol surface widening; bump `VERSION` per repo convention
- [x] 1.4 Update the `START_MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` blocks in `cloud_configs.py` for the new default; bump `VERSION` per repo convention

## 2. abandon_node use case

- [x] 2.1 Create `yascheduler/application/abandon_node.py` with a `FILE` / `VERSION` / `START_MODULE_CONTRACT` / `START_MODULE_MAP` / `START_CHANGE_SUMMARY` header per GRACE-lite (DEPENDS: M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-SSH-GATEWAY, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER; LINKS: M-APPLICATION-ABANDON-NODE)
- [x] 2.2 Implement the `abandon_node` async function with the signature `(node: Node, gateway: MachineGateway, clouds: CloudProvisioner, uow_factory: Callable[[], AbstractUnitOfWork], tracker: AllocationTracker) -> None`; TYPE_CHECKING imports for `MachineGateway`, `CloudProvisioner`, `Callable`, `AbstractUnitOfWork`; runtime imports for `Node`, `TaskStatus` from `yascheduler.domain` and `AllocationTracker` from `.allocation_tracker`
- [x] 2.3 Block 1 (CLOUD_DELETE): if `node.cloud` is not None, `try: await clouds.deallocate(node.cloud, node.ip) except Exception as err: logger.error("[abandon_node][CLOUD_DELETE_FAILED] ip=%s cloud=%s err=%s", node.ip, node.cloud, err)` — logged not raised, falls through to DB remove
- [x] 2.4 Block 2 (REMOVE_ROW): `try: async with uow_factory() as uow: await uow.nodes.remove(node.ip); await uow.commit() except Exception as err: logger.error("[abandon_node][REMOVE_FAILED] ip=%s err=%s", node.ip, err); raise` — re-raised so the caller's outer try/except keeps the worker alive
- [x] 2.5 Block 3 (RELEASE_TASK): open a second UoW, `await uow.tasks.list_by_status({TaskStatus.TO_DO})`, in-memory filter `allocated_ip == node.ip`; if exactly one match → `tracker.discard(task.task_id)`; if zero → no-op; if multiple → `logger.warning("[abandon_node][AMBIGUOUS_TASK] ip=%s count=%d", node.ip, count)` and no discard
- [x] 2.6 Add a `START_CONTRACT: abandon_node` block above the function covering PURPOSE / INPUTS / OUTPUTS / SIDE_EFFECTS / RAISES / LINKS per GRACE-lite; add `START_BLOCK_CLOUD_DELETE` / `START_BLOCK_REMOVE_ROW` / `START_BLOCK_RELEASE_TASK` markers around each block

## 3. Application facade re-export

- [x] 3.1 In `yascheduler/application/__init__.py`, add `from .abandon_node import abandon_node` and `"abandon_node"` to the `__all__` tuple; update the `MODULE_MAP` and `CHANGE_SUMMARY` blocks accordingly

## 4. Orchestrator connect-loop wiring

- [x] 4.1 In `yascheduler/application/orchestrator.py`, add `self._connect_failures: dict[str, float] = {}` to `Orchestrator.__init__` (initialize near `self._occupancy_started`); add `import time` if not already present
- [x] 4.2 In `_connect_machine_consumer`, on the successful `await self._gateway.connect(...)` branch (before `self._machine_connected_event.set()`), add `self._connect_failures.pop(node.ip, None)`
- [x] 4.3 In `_connect_machine_consumer`, on the `except MachineConnectionError as err:` branch, replace the bare `self._log.error(...)` with: (a) `first_seen = self._connect_failures.setdefault(node.ip, time.monotonic())`, (b) `age = time.monotonic() - first_seen`, (c) `grace = self._connect_grace_for(node.cloud)`, (d) `if age < grace: self._log.warning("[Orchestrator][_connect_machine_consumer][CONNECT_RETRY] ip=%s age=%.1fs grace=%ds err=%s", node.ip, age, grace, err); return`, (e) else fall through to abandon
- [x] 4.4 Add the abandon branch after the grace check: `self._log.error("[Orchestrator][_connect_machine_consumer][CONNECT_ABANDON] ip=%s age=%.1fs grace=%ds — abandoning node", node.ip, age, grace)`, then `await abandon_node(node, self._gateway, self._clouds, self._uow_factory, self._tracker)`, then `self._connect_failures.pop(node.ip, None)`; wrap the abandon call in a nested `try/except Exception as err: self._log.error("[Orchestrator][_connect_machine_consumer][ABANDON_FAILED] ip=%s err=%s", node.ip, err)` so a failed abandon does not kill the worker
- [x] 4.5 Add a private helper `_connect_grace_for(self, cloud: str | None) -> int` that scans `self._config_clouds` for `prefix == cloud` and returns `cfg.connect_grace`, falling back to `120` if no match; add a `START_CONTRACT: Orchestrator._connect_grace_for` block
- [x] 4.6 Update `START_MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` blocks in `orchestrator.py` for the new `_connect_failures` field, the abandon dispatch, and the `_connect_grace_for` helper; bump `VERSION` per repo convention; add `from .abandon_node import abandon_node` import
- [x] 4.7 (review-driven scope fix) Restrict `_connect_machine_producer` to cloud nodes: add `n.cloud is not None` filter in the `new_nodes` comprehension so static operator-managed nodes never reach the connect consumer / abandon path; add a `START_BLOCK_FILTER_CLOUD_ONLY` marker + rationale comment; update `MODULE_CONTRACT` SCOPE + `CHANGE_SUMMARY` (v6.2.1); add the orchestrator spec scenario "Non-cloud node excluded from abandon path"; add `TestConnectMachineProducerExcludesStaticNodes` unit tests

## 5. GRACE knowledge graph

- [x] 5.1 Add a new `M-APPLICATION-ABANDON-NODE` module record to `docs/knowledge-graph.xml` (TYPE=CORE_LOGIC, STATUS=planned, depends=M-APPLICATION-UOW, M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-SSH-GATEWAY, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATION-TRACKER); add an `<fn-abandon_node PURPOSE="Clean up never-connected cloud node + release stuck task" />` annotation
- [x] 5.2 Add `<fn-_connect_grace_for PURPOSE="Resolve per-cloud connect grace with conservative fallback" />` and `<const-_connect_failures PURPOSE="Per-IP monotonic first-seen failure timestamp" />` annotations to `M-APPLICATION-ORCHESTRATOR`
- [x] 5.3 Add `<CrossLink from="M-APPLICATION-ORCHESTRATOR" to="M-APPLICATION-ABANDON-NODE" relation="delegates never-connected node cleanup" />` to the graph
- [x] 5.4 Add `<type-connect_grace PURPOSE="Per-cloud SSH connect-failure deadline in seconds" />` annotation to `M-DOMAIN-PORTS` (or update the existing `CloudConfig` annotation)

## 6. Unit tests

- [x] 6.1 In `tests/unit/test_orchestrator.py` (or create `tests/unit/test_connect_machine_consumer.py` if more appropriate), add `test_connect_failure_within_grace_retries_without_abandoning`: stub `gateway.connect` to raise `MachineConnectionError`, set `connect_grace=60`, advance monotonic by 10s, assert `abandon_node` is NOT called and IP stays in `_connect_failures`
- [x] 6.2 Add `test_connect_failure_past_grace_triggers_abandon`: stub `gateway.connect` to raise `MachineConnectionError`, set `connect_grace=60`, advance monotonic by 65s, assert `abandon_node` IS called and IP is popped from `_connect_failures`
- [x] 6.3 Add `test_successful_connect_resets_failure_timer`: first call raises `MachineConnectionError` (records `first_seen`), second call succeeds, assert IP is popped from `_connect_failures`
- [x] 6.4 Add `test_unknown_cloud_falls_back_to_120s_grace`: node with `cloud="unknown"`, assert `_connect_grace_for("unknown")` returns 120
- [x] 6.5 Add `test_abandon_failed_does_not_kill_worker`: stub `abandon_node` to raise, assert the consumer catches and returns without propagating
- [x] 6.5b Add `test_daemon_restart_resets_failure_timers`: construct a fresh `Orchestrator` instance, assert `self._connect_failures` is `{}` (enforces the in-memory-only contract from the orchestrator spec's "Daemon restart resets failure timers" scenario)
- [x] 6.6 Create `tests/unit/test_abandon_node.py` with `test_happy_path_vm_deleted_row_removed_tracker_discarded`: stub `clouds.deallocate`, `uow.nodes.remove`, one TO_DO task with matching `allocated_ip`; assert all three called and `tracker.discard` invoked
- [x] 6.7 Add `test_abandon_node_non_cloud_skips_vm_deletion`: `node.cloud is None`; assert `clouds.deallocate` NOT called, `uow.nodes.remove` called, tracker lookup runs
- [x] 6.8 Add `test_abandon_node_cloud_delete_failure_does_not_block_db_cleanup`: `clouds.deallocate` raises; assert `uow.nodes.remove` still called and committed, function does not raise
- [x] 6.9 Add `test_abandon_node_db_remove_failure_reraised`: `uow.nodes.remove` raises; assert exception propagates and is logged
- [x] 6.10 Add `test_abandon_node_no_matching_task_no_discard`: zero TO_DO tasks with matching `allocated_ip`; assert `tracker.discard` NOT called, no raise
- [x] 6.11 Add `test_abandon_node_multiple_matching_tasks_logs_warning_no_discard`: two TO_DO tasks with same `allocated_ip`; assert warning logged, `tracker.discard` NOT called, no raise
- [x] 6.12 Add `test_connect_grace_defaults_on_all_four_dtos`: construct each `ConfigCloud*` without `connect_grace`; assert 60 for Hetzner/Upcloud, 120 for Azure/VastAI; assert `isinstance(dto, CloudConfig)` is True for all four

## 7. Integration / e2e tests

- [x] 7.1 In `tests/integration/` (or `tests/e2e/` per the `e2e-testing` spec), add `test_never_connected_node_abandoned_and_task_reallocated`: against real PostgreSQL + SSH testcontainer, allocate a task with a deliberately bad node IP (or a cloud mock that provisions a VM but the SSH connection is pointed at a dead port), advance past `connect_grace`, assert the `yascheduler_nodes` row is removed, the VM-delete stub was called, the task's `AllocationTracker` entry is discarded, and the task re-allocates on the next cycle (a second VM is provisioned with a working SSH endpoint → task transitions to RUNNING)
- [x] 7.2 Add `test_connect_grace_lookup_uses_cloud_prefix`: integration test confirming that a node with `cloud="hetzner"` gets `connect_grace=60` and a node with `cloud="azure"` gets `connect_grace=120` from the same orchestrator instance

## 8. Static checks and validation

- [x] 8.1 `uv run ruff check .` passes
- [x] 8.2 `uv run ruff format --check .` passes
- [x] 8.3 `uv run lint-imports` passes
- [x] 8.4 `uv run zuban check` passes
- [x] 8.5 `uv run pytest -m unit` passes (focused on the new `test_orchestrator` / `test_abandon_node` / `test_connect_grace` tests)
- [x] 8.6 `uv run pytest -m integration` passes against PostgreSQL + SSH testcontainers
- [x] 8.7 `python3 scripts/grace_check.py` exits 0 (XML + source checks; validates the new `M-APPLICATION-ABANDON-NODE` record and the updated annotations)
- [x] 8.8 `openspec validate fix-never-connected-node-leak --json` reports `valid: true`
- [x] 8.9 `openspec validate --all --json` passes (no regressions to existing specs from the `cloud-config-protocol` / `orchestrator` / `use-cases` deltas)
- [x] 8.10 Run `rg "connect_grace" yascheduler/entrypoints/config_parser.py` and confirm zero matches (enforces the cloud-config-protocol spec's "connect_grace is not parsed from INI in this change" scenario — the DTO default is the sole source)