## Context

Phases 1–4 established: domain entities (`Task`, `Node`, `ConnectedMachine`),
repository ports (`TaskRepository`, `NodeRepository`), `AbstractUnitOfWork`,
Postgres implementations, `SSHMachineGateway`, `CloudProvisionerImpl`.

Current state of each use case:

| Use case         | Persistence       | Entity types          | Spec signature matched |
| ---------------- | ----------------- | --------------------- | ---------------------- |
| `submit_task`    | UoW + repository  | domain `Task`         | ✅                      |
| `allocate_task`  | `DB` + `TaskModel`| legacy `TaskModel`    | ❌                      |
| `consume_task`   | `DB` + `TaskModel`| legacy `TaskModel`    | ❌                      |
| `deallocate_nodes`| `DB` + `NodeModel`| legacy `NodeModel`    | ❌                      |

The orchestrator stores `self._db: DB` and uses it in all 4 producers. SSH
helper methods (`_start_task_on_machine`, `_upload_task_data`) accept
`TaskModel` and read `task.metadata["remote_folder"]` etc. — these must
shift to domain `Task.context`.

## Goals / Non-Goals

**Goals:**
- Rewrite 3 use cases to accept `uow_factory` and domain types.
- Remove `M-DB` dependency from `M-APPLICATION-ALLOCATE`,
  `M-APPLICATION-CONSUME`, `M-APPLICATION-DEALLOCATE`, and
  `M-APPLICATION-ORCHESTRATOR`.
- Update orchestrator producers to query via UoW.
- Update orchestrator SSH helpers to work with domain `Task`.
- Update `make_daemon` to create UoW factory.
- Bring use case signatures in line with the existing `use-cases` spec.
- Add `limit` parameter to `TaskRepository.list_by_status`.

**Non-Goals:**
- No migration of SSH helpers from `RemoteMachine`/`RemoteMachineRepository`
  to `MachineGateway`/`ConnectedMachine` — that requires a deeper refactor of
  `_start_task_on_machine` (SFTP, deployables, spawn command). The orchestrator
  will continue using `RemoteMachine` for SSH operations but load/save tasks
  via UoW.
- No domain events migration (separate change `domain-events`).
- No changes to `client.py`, `utils.py`, or AiiDA plugin.
- No removal of `DB` class — it remains for `client.py` queries and schema
  migration. Only the daemon path removes its dependency on it.
- No connection pooling (separate change `connection-pool`).

## Decisions

### D1: Use cases receive `task_id`, not domain objects

Following the `use-cases` spec, `allocate_task` and `consume_task` accept
`task_id: int` and load the domain `Task` inside their own UoW transaction.
This gives the use case exclusive ownership of the task for the transaction
duration.

```python
async def allocate_task(
    task_id: int,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    machine_gateway: MachineGateway,
    cloud: CloudProvisioner,
    webhook: Callable,
) -> bool:
```

Alternative considered: pass domain `Task` loaded by the producer. Rejected
because it splits transaction ownership — the producer loads the task outside
the UoW, the use case saves it inside. This can mask stale-read issues.

### D2: Orchestrator producers open short-lived UoW for queries

Producers need to poll tasks/nodes. Each poll cycle opens a UoW, queries,
closes:

```python
async def _allocator_producer(self):
    async with self._uow_factory() as uow:
        tasks = await uow.tasks.list_by_status({TaskStatus.TO_DO}, limit=tlim)
    for task in tasks:
        yield UMessage(task.task_id, task)
```

The UoW is opened/closed per poll cycle (every `sleep_interval` seconds).
This is acceptable overhead — producers are lightweight queries.

### D3: Orchestrator SSH helpers accept domain `Task`

`_start_task_on_machine` currently reads `task.metadata["remote_folder"]`,
`task.metadata["fort.9"]`, etc. With domain `Task`, this becomes
`task.context.remote_folder`, `task.context.extra["fort.9"]`.

The orchestrator stores domain `Task` in queue messages
(`UMessage[int, Task]` instead of `UMessage[int, TaskModel]`).

### D4: `deallocate_nodes` split into query + action

Following the spec (`deallocate_nodes(uow_factory, cloud, config)`), the use
case queries nodes via UoW and delegates cloud deletion to `CloudProvisioner`.
`RemoteMachineRepository` stays as an orchestrator-level concern for
disconnecting SSH before cloud deallocation — `deallocate_node` stays in the
orchestrator consumer, not in the use case.

The use case becomes:
```python
async def deallocate_nodes(
    uow_factory: Callable[[], AbstractUnitOfWork],
    cloud: CloudProvisioner,
    config_clouds: Sequence[ConfigCloud],
    idle_machines: dict[str, float],  # ip → free_since monotonic time
) -> list[str]:
```

It returns disabled node IPs. The orchestrator consumer handles SSH disconnect
and cloud deallocation using those IPs.

### D5: `TaskRepository.list_by_status` gains `limit` parameter

Current signature: `list_by_status(statuses: set[TaskStatus])`.
New signature: `list_by_status(statuses: set[TaskStatus], *, limit: int | None = None)`.

The `PostgresTaskRepository` adds `LIMIT :limit` to the SQL query when provided.
Default `None` returns all matching tasks (backward compatible).

### D6: `make_daemon` retains `DB` for schema migration only

`DB.create()` handles schema migration (`db.migrate()`). After migration, the
daemon path uses UoW exclusively. `make_daemon` creates `DB`, runs migration,
then builds a UoW factory. The `DB` instance is not passed to the orchestrator.

```python
async def make_daemon(config, log, *, db=None, clouds=None):
    if db is None:
        db = await DB.create(config.db)  # migration
    def uow_factory():
        return PostgresUnitOfWork(config.db)
    return Orchestrator(config, uow_factory=uow_factory, clouds=clouds, ...)
```

### D7: Webhook callback stays as callable parameter

Webhook calls remain a callable parameter to use cases (not domain events).
Domain events are a separate change. The callable signature changes from
`Callable[[int, Mapping, TaskStatus], Awaitable]` (db `TaskStatus`) to
`Callable[[int, Mapping, domain.TaskStatus], Awaitable]` (domain `TaskStatus`).

## Risks / Trade-offs

- **Two persistence paths in orchestrator**: Producers query via UoW but SSH
  helpers still use `RemoteMachine` (which uses `SSHMachineGateway`). This is
  acceptable — SSH operations are not persistence concerns. Full alignment
  arrives when SSH helpers migrate to `MachineGateway` directly.

- **UoW per poll cycle overhead**: Each producer poll opens/closes a UoW
  (pg8000 connection). At the default `sleep_interval` (e.g., 5s), this is
  ~0.2 QPS per producer — negligible. Connection pooling (separate change)
  will reduce this further.

- **Webhook callable coupling**: Use cases still receive webhook callback as
  parameter. Domain events change (`domain-events`) will resolve this. The
  callable signature changes to use domain `TaskStatus` — a minor breaking
  change internal to the application layer.

- **`TaskModel` → `Task` in queue messages**: Queue messages change from
  `UMessage[int, TaskModel]` to `UMessage[int, Task]`. This is an internal
  type change with no external API impact.

- **`deallocate_nodes` API split**: The use case returns disabled node IPs
  instead of performing SSH disconnect + cloud deletion. This means the
  orchestrator consumer must call `deallocate_node` after the use case. The
  spec's `deallocate_nodes(uow_factory, cloud, config)` signature implies
  cloud deletion is inside the use case, but SSH disconnect is an
  infrastructure concern outside UoW scope. The use case disables nodes in DB;
  the orchestrator handles SSH cleanup and cloud API calls.
