## REMOVED Requirements

### Requirement: DB provides task and node CRUD
**Reason**: The `DB` facade class, its task/node CRUD methods, and the lifecycle
methods (`commit`, `migrate`, `close`) are deleted along with
`yascheduler/db.py`. Production code already routes persistence through
`PostgresUnitOfWork` and the repository adapters; the `db-wrapper` capability
has no remaining subject.
**Migration**: Persistence callers SHALL use `PostgresUnitOfWork` (via
`async with uow_factory() as uow:`) and the repository ports
(`uow.tasks`, `uow.nodes`) directly. There is no drop-in replacement for the
`DB` class — it is intentionally not replaced by another facade. The task
methods (`get_task`, `get_tasks_by_status`, `add_task`, `set_task_running`,
`set_task_done`, `set_task_error`, etc.) map to `PostgresTaskRepository`
methods; node methods map to `PostgresNodeRepository` methods.

### Requirement: TaskModel and NodeModel are immutable attrs
**Reason**: `TaskModel` and `NodeModel` were legacy attrs mirrors of the
canonical domain entities `Task` and `Node` (`yascheduler.domain.model`). They
are deleted with `yascheduler/db.py`. The canonical domain entities remain.
**Migration**: Callers SHALL use `yascheduler.domain.Task` and
`yascheduler.domain.Node` (frozen dataclasses) and
`yascheduler.domain.TaskStatus` (IntEnum: TO_DO=0, RUNNING=1, DONE=2). Domain
entity field names differ from the legacy models: `Task.allocated_ip` (not
`ip`), `Task.context` (not `metadata`); `Node` fields are unchanged.