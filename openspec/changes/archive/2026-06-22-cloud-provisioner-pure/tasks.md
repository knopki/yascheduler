## 1. Knowledge Graph & Contracts (GRACE-lite top-down)

- [x] 1.1 Update `docs/knowledge-graph.xml`: `M-CLOUD-PROVISIONER` — remove DB/persistence annotations, update `<annotations>` (remove `fn-allocate_with_tracking`, `fn-get_capacity`, `fn-mark_task_done`, `fn-capacity`; add `fn-select_provider` port method, `fn-allocate` updated signature). Note: M-DB is not currently in M-CLOUD-PROVISIONER depends (no-op to remove); do NOT add M-APPLICATION-UOW (adapter is pure cloud, no UoW dependency — would be reverse-layering smell)
- [x] 1.2 Add `M-CLOUD-PROVIDER-SELECTION` module entry to `docs/knowledge-graph.xml` (TYPE=UTILITY, path=`adapters/cloud/provider_selection.py`, depends=M-CLOUD-ADAPTERS, annotation `fn-select_provider_pure`)
- [x] 1.3 Add `M-APPLICATION-ALLOCATION-TRACKER` module entry to `docs/knowledge-graph.xml` (TYPE=CORE_LOGIC, path=`application/allocation_tracker.py`, depends=none, annotation `class-AllocationTracker`)
- [x] 1.4 Update `M-DI` in `docs/knowledge-graph.xml`: remove M-DB from `<depends>`; add M-APPLICATION-ALLOCATION-TRACKER to `<depends>` (make_daemon constructs tracker); remove `db` parameter annotation from `make_daemon`
- [x] 1.5 Update `M-APPLICATION-ORCHESTRATOR` in `docs/knowledge-graph.xml`: add `const-allocation_tracker`, `const-active_clouds`, `const-allocation_lock` annotations; add CrossLink `M-APPLICATION-ORCHESTRATOR → M-APPLICATION-ALLOCATION-TRACKER` relation="owns and injects tracker for in-flight allocation dedup"
- [x] 1.6 Update `M-APPLICATION-ALLOCATE` and `M-APPLICATION-DEALLOCATE` in `docs/knowledge-graph.xml`: add M-APPLICATION-ALLOCATION-TRACKER to `<depends>`; add CrossLinks (from=M-APPLICATION-ALLOCATE to=M-APPLICATION-ALLOCATION-TRACKER relation="dedupes in-flight cloud allocations"; from=M-APPLICATION-CONSUME to=M-APPLICATION-ALLOCATION-TRACKER relation="discards completed allocations"; remove M-CLOUD-PROVISIONER from M-APPLICATION-CONSUME depends since consume no longer takes clouds)
- [x] 1.7 Update `M-DOMAIN-PORTS` in `docs/knowledge-graph.xml`: update `CloudProvisioner` annotation (allocate takes provider str, deallocate takes cloud+ip, select_provider sync method, capacity removed); add `type-ProviderSelection` annotation to M-DOMAIN-MODEL
- [x] 1.8 Update `M-DOMAIN-EXCEPTIONS` in `docs/knowledge-graph.xml`: add `class-CloudAllocateError` and `class-CloudSetupError` annotations (relocated from M-CLOUD-PROVISIONER); add CrossLink from=M-CLOUD-PROVISIONER to=M-DOMAIN-EXCEPTIONS relation="re-exports relocated cloud exceptions"
- [x] 1.9 Run `python3 scripts/grace_check.py` — graph validates

## 2. Domain Layer — ports, value object, exceptions

- [x] 2.1 Update `yascheduler/domain/ports.py`: `CloudProvisioner` Protocol — `allocate(provider: str) -> Node` (async), `deallocate(cloud: str, ip: str) -> None` (async), `select_provider(platforms: list[str], current_counts: dict[str, int]) -> ProviderSelection | None` (sync); remove `capacity()`; update MODULE_MAP + CHANGE_SUMMARY + contract block
- [x] 2.2 Add `ProviderSelection` value object to `yascheduler/domain/model.py`: `@dataclass(frozen=True) class ProviderSelection: name: str; username: str`; update MODULE_MAP + CHANGE_SUMMARY
- [x] 2.3 Move `CloudAllocateError` and `CloudSetupError` from `adapters/cloud/manager.py` to `yascheduler/domain/exceptions.py`; preserve names, semantics, inheritance (Exception subclass); update MODULE_MAP + CHANGE_SUMMARY in exceptions.py
- [x] 2.4 Re-export `CloudAllocateError`, `CloudSetupError` from `yascheduler/adapters/cloud/manager.py` (import from `domain.exceptions`) for backwards compatibility with adapter-internal callers
- [x] 2.5 Re-export `CloudAllocateError`, `CloudSetupError` from `yascheduler/adapters/cloud/__init__.py` if currently exported there
- [x] 2.6 Update `yascheduler/domain/__init__.py` re-exports if needed (verify `ProviderSelection`, `CloudAllocateError`, `CloudSetupError` exported from domain)

## 3. Provider Selection (adapter-internal pure function)

- [x] 3.1 Create `yascheduler/adapters/cloud/provider_selection.py` with MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY
- [x] 3.2 Implement `select_provider_pure(adapters, configs, platforms, current_counts, log) -> CloudAdapter | None` — extract algorithm verbatim from `CloudProvisionerImpl._select_best_provider` (manager.py:327-382), replace `self.node_repo.list_all()` with `current_counts` param, inline `_is_platform_supported` check
- [x] 3.3 Add `START_CONTRACT: select_provider_pure` block with INPUTS/OUTPUTS/SIDE_EFFECTS/LINKS
- [x] 3.4 (Optional) Re-export `select_provider_pure` from `yascheduler/adapters/cloud/__init__.py` only if needed by other adapter modules — it is adapter-internal, called only from `CloudProvisionerImpl.select_provider`

## 4. AllocationTracker

- [x] 4.1 Create `yascheduler/application/allocation_tracker.py` with MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY
- [x] 4.2 Implement `AllocationTracker` class: `__init__` (empty set), `add(task_id) -> bool`, `discard(task_id) -> None`, `__contains__(task_id) -> bool`
- [x] 4.3 Add `START_CONTRACT: AllocationTracker` and `START_CONTRACT: AllocationTracker.add`/`.discard` blocks
- [x] 4.4 Re-export `AllocationTracker` from `yascheduler/application/__init__.py`

## 5. CloudProvisionerImpl — strip DB, add port methods

- [x] 5.1 Update `yascheduler/adapters/cloud/manager.py` MODULE_CONTRACT: remove DB/persistence from PURPOSE and SCOPE; update DEPENDS (remove M-DB, M-PERSISTENCE-*); update LINKS
- [x] 5.2 Update `CloudProvisionerImpl` class contract: remove `node_repo` from INPUTS; remove `allocation_lock`, `on_tasks` from internal state description
- [x] 5.3 Remove `node_repo` field from `@define` constructor; remove `allocation_lock` field; remove `on_tasks` set
- [x] 5.4 Remove methods: `allocate_with_tracking`, `get_capacity`, `_select_best_provider`, `_acquire_provider_slot`, `_safe_remove_tmp`, `mark_task_done`, `apis` property, `capacity`
- [x] 5.5 Implement `select_provider(self, platforms, current_counts) -> ProviderSelection | None` (sync port method): call `select_provider_pure(self.adapters, self.configs, platforms, current_counts, self.log)`; if None, return None; if `adapter.get_op_semaphore().locked()`, return None (throttle, no raise); else return `ProviderSelection(name=adapter.name, username=self.configs[adapter.name].username)`
- [x] 5.6 Rewrite `allocate(self, provider: str) -> Node`: look up `adapter = self.adapters[provider]`, `config = self.configs[provider]`; create VM via adapter; wait SSH; cloud-init; setup; return Node (no DB write, no tmp-node — that's use case's job)
- [x] 5.7 Update `deallocate(self, cloud: str, ip: str) -> None`: look up `adapter = self.adapters[cloud]`; call `adapter.delete_node(ip)`; no DB read/write
- [x] 5.8 Keep `stop()` no-op, `_get_ssh_key`, `_get_cloud_config_data`, `_setup_vm`, `_connect_to_vm` helpers unchanged
- [x] 5.9 Update CHANGE_SUMMARY in manager.py

## 6. allocate_task Use Case — own cloud-fallback flow

- [x] 6.1 Update `yascheduler/application/allocate_task.py` MODULE_CONTRACT: add M-APPLICATION-ALLOCATION-TRACKER to DEPENDS; update LINKS
- [x] 6.2 Update `allocate_task` signature: replace `clouds: CloudProvisionerImpl` with `clouds: CloudProvisioner` (Protocol); add `tracker: AllocationTracker`, `allocation_lock: asyncio.Lock` params; do NOT add `adapters`/`configs` params
- [x] 6.3 Implement cloud-fallback flow: `tracker.add(task_id)` dedup check at start with early-return-on-False
- [x] 6.4 Implement critical section under `allocation_lock`: open UoW, read `uow.nodes.list_all()`, compute counts, call `clouds.select_provider(platforms, counts)` (port method); if `selection is None`, call `tracker.discard(task_id)`, return False; else `uow.nodes.add_tmp(selection.name, selection.username)`, commit (before lock release)
- [x] 6.5 Implement cloud allocation outside lock: `node = await clouds.allocate(selection.name)`; on `CloudAllocateError`/`CloudSetupError` or other exception, open UoW, remove tmp-node, commit, `tracker.discard(task_id)`, re-raise
- [x] 6.6 Implement final persist outside lock: open UoW, `uow.nodes.add(node)`, `uow.nodes.remove(tmp_ip)`, commit
- [x] 6.7 Update `_try_start_on_machine` and `_allocate_free_machine`: replace `clouds: CloudProvisionerImpl` param with `tracker: AllocationTracker` (remove `clouds` param — these helpers don't deallocate); replace `clouds.mark_task_done(task.task_id)` with `tracker.discard(task.task_id)`; propagate `tracker` param through both helper signatures
- [x] 6.8 Add `START_BLOCK_*` semantic blocks for new flow sections; add structured logging at block boundaries
- [x] 6.9 Update CHANGE_SUMMARY

## 7. consume_task Use Case — tracker integration

- [x] 7.1 Update `yascheduler/application/consume_task.py` MODULE_CONTRACT: add M-APPLICATION-ALLOCATION-TRACKER to DEPENDS; remove M-CLOUD-PROVISIONER from DEPENDS (consume no longer takes clouds)
- [x] 7.2 Update `consume_task` signature: replace `clouds: CloudProvisionerImpl` with `tracker: AllocationTracker` (consume no longer needs clouds — it doesn't deallocate)
- [x] 7.3 Update `_finalize_task`: replace `clouds.mark_task_done(task.task_id)` with `tracker.discard(task.task_id)`
- [x] 7.4 Update `_finalize_task` contract block INPUTS (replace `clouds` with `tracker`)
- [x] 7.5 Update `consume_task` contract block INPUTS
- [x] 7.6 Update CHANGE_SUMMARY

## 8. deallocate_nodes Use Case — own disable+remove bracketing

- [x] 8.1 Update `yascheduler/application/deallocate_nodes.py` MODULE_CONTRACT: verify M-APPLICATION-UOW in DEPENDS; update LINKS
- [x] 8.2 Update `deallocate_node` signature: add `uow_factory: Callable[[], AbstractUnitOfWork]` param; narrow `clouds` type from `CloudProvisionerImpl` to `CloudProvisioner` Protocol; update contract block
- [x] 8.3 Implement `deallocate_node` new flow: `gateway.disconnect` → UoW disable + commit → `clouds.deallocate(node.cloud, node.ip)` → UoW remove + commit
- [x] 8.4 Add `START_BLOCK_DISABLE`, `START_BLOCK_CLOUD_DELETE`, `START_BLOCK_REMOVE` semantic blocks with structured logging
- [x] 8.5 Update `deallocate_nodes` (plural sweep) — no change to disable logic (already UoW-based); verify it doesn't call `clouds.deallocate` (it shouldn't — only returns IPs)
- [x] 8.6 Update CHANGE_SUMMARY

## 9. Orchestrator — inline capacity + new dependencies

- [x] 9.1 Update `yascheduler/application/orchestrator.py` MODULE_CONTRACT: add M-APPLICATION-ALLOCATION-TRACKER to DEPENDS; update LINKS
- [x] 9.2 Update `Orchestrator.__init__` signature: add `allocation_tracker: AllocationTracker`, `active_clouds: Sequence[ConfigCloud]`, `allocation_lock: asyncio.Lock` params; store as `self._tracker`, `self._active_clouds`, `self._allocation_lock`; do NOT add `adapters`/`configs` params
- [x] 9.3 Update `Orchestrator.__init__` contract block INPUTS
- [x] 9.4 Rewrite `_clouds_get_capacity`: open UoW, `uow.nodes.list_all()`, `Counter(n.cloud for n in nodes if n.cloud)`, return `max(0, sum(c.max_nodes for c in self._active_clouds) - sum(counts[c.prefix] for c in self._active_clouds))`
- [x] 9.5 Update `_allocator_consumer`: pass `tracker=self._tracker`, `allocation_lock=self._allocation_lock` to `allocate_task` (no `adapters`/`configs` — port method handles selection)
- [x] 9.6 Update `_task_consumer_consumer`: pass `tracker=self._tracker` to `consume_task` instead of `clouds`
- [x] 9.7 Update `_deallocator_consumer`: pass `uow_factory=self._uow_factory` to `deallocate_node`; verify `clouds.deallocate(node.cloud, node.ip)` two-arg call
- [x] 9.8 Remove `self._clouds.configs` access (line 385) — replaced by `self._active_clouds`
- [x] 9.9 Verify `stop()` — `self._clouds.stop()` still valid (no-op preserved)
- [x] 9.10 Add `START_BLOCK_*` for new `_clouds_get_capacity` sections; update structured logging
- [x] 9.11 Update CHANGE_SUMMARY

## 10. Dependency Injection — remove DB from make_daemon

- [x] 10.1 Update `yascheduler/di.py` MODULE_CONTRACT: remove M-DB from DEPENDS; add M-APPLICATION-ALLOCATION-TRACKER to DEPENDS; update LINKS
- [x] 10.2 Remove `from .db import DB` import
- [x] 10.3 Update `make_daemon` signature: remove `db: DB | None = None` parameter; update contract block INPUTS
- [x] 10.4 Remove `if db is None: db = await DB.create(config.db)` block
- [x] 10.5 Construct `AllocationTracker` instance, `asyncio.Lock()` (in running loop), `active_clouds` filtered list (same filter as current di.py:154-167: `max_nodes > 0` AND `_resolve_adapter` success)
- [x] 10.6 Construct `CloudProvisionerImpl` without `node_repo` param
- [x] 10.7 Pass `allocation_tracker`, `active_clouds`, `allocation_lock` to `Orchestrator` constructor; do NOT pass `adapters`/`configs` (stay on CloudProvisionerImpl)
- [x] 10.8 Update `make_daemon` contract block SIDE_EFFECTS (remove "Creates DB connection for schema migration")
- [x] 10.9 Update CHANGE_SUMMARY

## 11. Unit Tests — update existing

- [x] 11.1 `tests/unit/test_cloud_provisioner_impl.py`: remove `_make_mock_node_repo` helper and all `node_repo=` call sites (~13); update `make_provisioner` factory to not accept `node_repo`
- [x] 11.2 `tests/unit/test_cloud_provisioner_impl.py`: remove tests for `allocate_with_tracking`, `get_capacity`, `mark_task_done`, `apis`, `_select_best_provider` (moved to new test files or deleted)
- [x] 11.3 `tests/unit/test_cloud_provisioner_impl.py`: update `allocate` test — new signature `allocate(provider: str)`; assert no `node_repo.add` call; assert Node returned with correct fields; assert `CloudAllocateError`/`CloudSetupError` raised on VM failure
- [x] 11.4 `tests/unit/test_cloud_provisioner_impl.py`: update `deallocate` test — new signature `deallocate(cloud, ip)`; assert no `node_repo.get/disable/remove` calls; assert `adapter.delete_node` called
- [x] 11.5 `tests/unit/test_cloud_provisioner_impl.py`: add `select_provider` test — sync port method; assert returns `ProviderSelection` when capacity available; returns `None` when no capacity; returns `None` when throttle (op semaphore locked); assert no DB access
- [x] 11.6 `tests/unit/test_application_use_cases.py`: update `allocate_task` tests — mock `tracker`, `allocation_lock`; assert `clouds.select_provider` port method called (not `select_provider_pure`); assert tmp-node insertion, cloud alloc, final persist flow; split into 11.6a (allocate-to-machine — tracker.discard swap), 11.6b (cloud-fallback happy path), 11.6c (cloud-fallback failure cleanup), 11.6d (dedup — tracker.add returns False), 11.6e (throttle — select_provider returns None)
- [x] 11.7 `tests/unit/test_application_use_cases.py`: update `consume_task` tests — mock `tracker` instead of `clouds`; assert `tracker.discard` called
- [x] 11.8 `tests/unit/test_application_orchestrator.py`: update `_clouds_get_capacity` tests — mock `uow.nodes.list_all()`; assert inline arithmetic over `active_clouds`
- [x] 11.9 `tests/unit/test_application_orchestrator.py`: add Orchestrator constructor tests — assert `allocation_tracker`, `active_clouds`, `allocation_lock` stored and passed to use cases; assert no `adapters`/`configs` stored
- [x] 11.10 `tests/unit/test_application_orchestrator.py`: update `_deallocator_consumer` tests — assert `deallocate_node` called with `uow_factory`
- [x] 11.11 `tests/unit/test_di.py`: remove `DB.create` assertions; remove `db` parameter tests; assert `AllocationTracker`, `allocation_lock`, `active_clouds` constructed and passed to Orchestrator; assert no `adapters`/`configs` passed to Orchestrator
- [x] 11.12 `tests/unit/test_domain_ports.py`: update `CloudProvisioner` Protocol stub — `allocate(provider)`, `deallocate(cloud, ip)`, `select_provider(platforms, current_counts)` sync, no `capacity`
- [x] 11.13 `tests/unit/test_domain_model.py`: add `ProviderSelection` tests — frozen, name+username fields
- [x] 11.14 `tests/unit/test_domain_exceptions.py`: add `CloudAllocateError`/`CloudSetupError` tests — importable from `yascheduler.domain.exceptions`, re-exported from `yascheduler.adapters.cloud`
- [x] 11.15 Update or delete `tests/fixtures/mock_clouds.py` — fixture stubs `mark_task_done`, `get_capacity`, `configs.values()` (all removed/changed); if dead code, delete; otherwise update to match new CloudProvisioner surface

## 12. Unit Tests — new

- [x] 12.1 Create `tests/unit/test_allocation_tracker.py` with MODULE_CONTRACT: test `add` new (returns True), `add` duplicate (returns False), `discard` tracked, `discard` untracked (no-op), `__contains__` True/False
- [x] 12.2 Create `tests/unit/test_provider_selection.py` with MODULE_CONTRACT: test `select_provider_pure` — higher priority wins, full provider skipped, no platform support returns None, multiple platforms, empty adapters, empty current_counts
- [x] 12.3 Add tests for `allocate_task` cloud-fallback flow: tracker dedup, `clouds.select_provider` port method called, tmp-node insertion under lock, commit before lock release, cloud alloc outside lock, failure cleanup, final persist, throttle None-return path
- [x] 12.4 Add tests for `deallocate_node` bracketing: disable+commit → cloud delete → remove+commit ordering; failure in cloud delete leaves node disabled

## 13. E2E Test Update

- [x] 13.1 Update `tests/e2e/test_full_cycle.py` line 85: `make_daemon(config, db=db)` → `make_daemon(config)` (drop `db=` param)
- [x] 13.2 Verify e2e `db` fixture wiring survives the `make_daemon` signature change (fixture already constructs DB independently via `DB.create(automigrate=False)` + `apply_schema()` in `tests/e2e/conftest.py:168-184` — no fixture change needed, only the call-site at line 85)
- [x] 13.3 Verify e2e test passes with new orchestrator flow (UoW-based cloud paths, `deallocate(cloud, ip)` two-arg, `select_provider` port method, `allocate(provider)` one-arg)

## 14. Static Checks & Validation

- [x] 14.1 Run `uv run ruff check .` — no lint errors
- [x] 14.2 Run `uv run ruff format --check .` — no format errors
- [x] 14.3 Run `uv run lint-imports` — import layering respected (verify application layer does NOT import `CloudAdapter`/`ConfigCloud`/`CloudAllocateError` from `adapters`; verify `CloudAllocateError`/`CloudSetupError` imported from `domain.exceptions` in application layer)
- [x] 14.4 Run `uv run zuban check` — no type errors
- [x] 14.5 Run `python3 scripts/grace_check.py` — XML + source checks pass
- [x] 14.6 Run `openspec validate --all --json` — all specs valid
- [x] 14.7 Run `uv run pytest -m unit` — all unit tests pass
- [x] 14.8 Run `uv run pytest -m integration` — all integration tests pass
- [x] 14.9 Run `uv run pytest -m e2e` — all e2e tests pass
- [x] 14.10 Verify no residual references to removed/changed symbols in source (non-test): grep for `mark_task_done`, `allocate_with_tracking`, `.capacity()`, `.get_capacity()`, `_select_best_provider`, `_acquire_provider_slot`, `_safe_remove_tmp`, `on_tasks`, `node_repo=` (constructor arg), `from yascheduler.db import DB` in `di.py`, `orchestrator.py`, `allocate_task.py`, `consume_task.py`, `deallocate_nodes.py`, `cloud/manager.py`
- [x] 14.11 Verify `CloudAllocateError`/`CloudSetupError` defined in `domain/exceptions.py` and re-exported from `adapters/cloud/manager.py` and `adapters/cloud/__init__.py`
