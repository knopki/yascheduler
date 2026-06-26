## ADDED Requirements

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function in
`yascheduler/application/abandon_node.py` that cleans up a cloud node that
never established its SSH connection, releasing the originating task to
re-allocate on the next cycle. The function SHALL accept `node: Node`,
`gateway: MachineGateway` (Protocol type), `clouds: CloudProvisioner`
(Protocol type), `uow_factory: Callable[[], AbstractUnitOfWork]`, and
`tracker: AllocationTracker`. It SHALL NOT import from `yascheduler.infra`
at runtime (TYPE_CHECKING only).

The use case SHALL NOT call `gateway.disconnect` — by construction the node
was never registered in the gateway (that is why it is being abandoned). The
use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node.cloud, node.ip)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `ip`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal (the row may already be stale, but
   removing it is idempotent and lets the orchestrator stop re-yielding the
   IP).
2. Open a UoW, call `uow.nodes.remove(node.ip)`, and commit. Failure here
   SHALL be logged at `error` level with `ip` and the exception and
   re-raised (the caller — `_connect_machine_consumer` — wraps its body in a
   try/except that keeps the worker alive, mirroring `_allocator_consumer`).
3. Open a second UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`,
   and in-memory filter for the task whose `allocated_ip == node.ip`. If
   exactly one such task exists, call `tracker.discard(task.task_id)`. If
   zero or multiple match, no `discard` is called — zero means the task has
   already advanced (e.g. operator reassignment), multiple is an
   invariant violation that SHOULD be logged at `warning` level but not
   fatal.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle with no retry counter (per
the proposal's Non-Goal on re-allocation limits). The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly, which is stronger than disabling and matches the never-connected
semantics (there is no transient-disconnect risk to protect against, since
the node was never in the gateway).

#### Scenario: Happy path — VM deleted, DB row removed, tracker released
- **WHEN** `abandon_node(node, gateway, clouds, uow_factory, tracker)` is called for a cloud node (`node.cloud` non-None) with one TO_DO task whose `allocated_ip == node.ip`
- **THEN** `clouds.deallocate(node.cloud, node.ip)` is called, `uow.nodes.remove(node.ip)` is called and committed, `tracker.discard(task.task_id)` is called for the matching task, and the function returns without raising

#### Scenario: Non-cloud node skips VM deletion
- **WHEN** `abandon_node(...)` is called with `node.cloud is None`
- **THEN** `clouds.deallocate` is NOT called, `uow.nodes.remove(node.ip)` is still called and committed, and the stuck-task lookup still runs

#### Scenario: Cloud deletion failure does not block DB cleanup
- **WHEN** `clouds.deallocate(node.cloud, node.ip)` raises an exception
- **THEN** the exception is logged at `error` level with `ip`, `cloud`, and the message, `uow.nodes.remove(node.ip)` is still called and committed, and the function continues to the stuck-task lookup

#### Scenario: DB remove failure is re-raised
- **WHEN** `uow.nodes.remove(node.ip)` or its commit raises an exception
- **THEN** the exception is logged at `error` level with `ip` and the message, and the exception is re-raised (the caller keeps the worker alive via its outer try/except)

#### Scenario: No matching TO_DO task
- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_ip == node.ip`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran

#### Scenario: Multiple matching TO_DO tasks is logged not fatal
- **WHEN** the stuck-task lookup finds more than one TO_DO task with `allocated_ip == node.ip`
- **THEN** a warning is logged, `tracker.discard` is NOT called (ambiguous which task to release), the VM deletion + DB removal still ran, and the function returns without raising

#### Scenario: No adapter imports at runtime
- **WHEN** `abandon_node.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)