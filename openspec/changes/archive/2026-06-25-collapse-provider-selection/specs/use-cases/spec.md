## MODIFIED Requirements

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function
SHALL accept `task_id: int`, `uow_factory`, `gateway: MachineGateway`
(Protocol type), `clouds: CloudProvisioner` (Protocol type), `tracker:
AllocationTracker`, and `allocation_lock: asyncio.Lock`. It SHALL NOT
import from `yascheduler.infra` at runtime. It SHALL NOT accept
`adapters` or `configs` parameters — provider selection is delegated to
the `clouds.select_provider` port method.

For the cloud-fallback path, the use case SHALL own the full flow:
tracker dedup, capacity check, provider selection (via
`clouds.select_provider` port method returning `str | None`), tmp-node
insertion, cloud allocation (via `clouds.allocate(selection)`), final
node persistence, and tmp-node cleanup on failure. The
`allocation_lock` SHALL serialize the capacity-read + select + add_tmp
critical section as a single UoW with commit before lock release.

#### Scenario: Allocate to free machine
- **WHEN** `allocate_task(task_id, engines, uow_factory, gateway, clouds, start_task_on_machine, tracker, allocation_lock)` is called and a free compatible machine exists
- **THEN** the task is loaded via UoW, allocated via `task.allocate_to(ip)`, transitioned to RUNNING via `task.mark_running()`, saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called

#### Scenario: No free machine — cloud fallback with full ownership
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the use case calls `tracker.add(task_id)` (returns False → return immediately if already in-flight). Then opens a UoW under `allocation_lock`, reads `uow.nodes.list_all()`, calls `clouds.select_provider(platforms, counts)` (port method). If `selection is None`, calls `tracker.discard(task_id)` and returns False. Otherwise inserts a tmp-node via `uow.nodes.add_tmp(selection)`, commits, calls `clouds.allocate(selection)` outside the lock, then opens a second UoW to persist the final Node and remove the tmp-node. Returns False.

#### Scenario: Cloud allocation failure cleans up tmp-node
- **WHEN** `clouds.allocate(selection)` raises `CloudAllocateError` or `CloudSetupError` after tmp-node insertion
- **THEN** the use case opens a UoW, removes the tmp-node via `uow.nodes.remove(tmp_ip)`, commits, calls `tracker.discard(task_id)`, and re-raises

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a task_id already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without creating a second VM

#### Scenario: Throttle returns None — no tmp-node inserted
- **WHEN** `clouds.select_provider(platforms, counts)` returns `None` because the selected provider's op semaphore is locked
- **THEN** the use case calls `tracker.discard(task_id)` and returns False (no tmp-node inserted, no exception raised)

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.reject("unsupported engine")`, saved, committed, and `TaskFailed` event is recorded