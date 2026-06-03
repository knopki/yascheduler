## Context

Phase 3 of the architecture migration. `domain-model` and `persistence-adapter`
provided the domain layer and repository implementations. Neither is wired
into the running system. This design connects them through use cases.

## Goals / Non-Goals

**Goals:**
- Extract business logic from `scheduler.py` into standalone use cases.
- Create an orchestrator for the daemon's producer-consumer loops.
- Create DI factories for each entry point.
- Break `client.py → scheduler.py` import.
- Refactor CLI commands to use use cases.

**Non-Goals:**
- No domain events (Phase 3.5).
- No SSH/cloud adapter migration (Phase 4).
- No CLI cleanup (Phase 5) — only refactor to use use cases; file stays.
- No changes to `aiida_plugin.py`.

## Decisions

### D1: Use cases as async functions with injected ports

Each use case is a single `async def` that receives ports and a UoW factory
as arguments:

```python
async def submit_task(
    label: str,
    context: TaskContext,
    engine_name: str,
    engines: EngineRepository,
    uow_factory: Callable[[], AbstractUnitOfWork],
    webhook_onsubmit: bool = False,
) -> int:
    engine = engines.get(engine_name)
    engine.validate_inputs(context)
    async with uow_factory() as uow:
        task = Task(...)
        await uow.tasks.save(task)
        await uow.commit()
    return task.task_id
```

Use cases are stateless. The DI factory creates closures or partials with
pre-bound ports if needed.

### D2: Orchestrator manages daemon lifecycle

`application/orchestrator.py` contains the long-running daemon logic:

- 4 producer-consumer loops (connect_machine, allocate, consume, deallocate)
  using `UniqueQueue`.
- Concurrency limits from config.
- `cancellation_event` for graceful shutdown.
- Stats printing (periodic log).
- First-machine wait logic.

The orchestrator calls use cases in its consumer loops:

```python
async def _allocate_consumer(self, msg):
    await allocate_task(
        task_id=msg.payload.task_id,
        uow_factory=self._uow_factory,
        machines=self._machines,
        engine=self._engines[msg.payload.context.engine],
        cloud=self._cloud_provisioner,
    )
```

### D3: DI factories — one per entry point

`di.py` has three factory functions:

**`make_daemon(config) -> Orchestrator`:**
- Creates `PostgresUnitOfWork` factory
- Creates `SSHMachineGateway` (or wraps old `RemoteMachineRepository` during transition)
- Creates `CloudAPIManager` (old — until Phase 4)
- Creates `EngineRepository` from config
- Wires use cases with all ports
- Returns `Orchestrator` ready to `await orchestrator.start()`

**`make_cli_deps(config) -> CLIDeps`:**
- Creates `PostgresUnitOfWork` factory only
- Creates `EngineRepository`
- Wires `submit_task`, query use cases
- Returns lightweight `CLIDeps` (no SSH, no cloud)

**`make_aiida(config)`** (future, currently stubbed)

### D4: UoW Protocol lives in application

`AbstractUnitOfWork` Protocol is defined in `application/uow.py`, not in
`domain/`. Rationale: it depends on `TaskRepository` and `NodeRepository`
which are domain ports — but the Protocol itself is an application concern
(multiple repositories sharing a transaction). Domain doesn't need to know
about UoW at all.

### D5: client.py breaks scheduler.py import

**Before:**
```python
from .scheduler import Scheduler
yac = await Scheduler.create(config=self.config, log=self._logger)
```

**After:**
```python
from .di import make_cli_deps
deps = make_cli_deps(self.config)
task_id = await deps.submit.by_engine(label, metadata, engine_name)
```

This eliminates the heavyweight `Scheduler.create()` call (which creates
DB, clouds, SSH connections) for a simple task insert.

### D6: Transitional compatibility — old code still works

During Phase 3, `scheduler.py` still exists but delegates to use cases.
The `Scheduler` class retains its public API (`start()`, `stop()`,
`create_new_task()`) but these now call use cases internally.

```python
class Scheduler:
    async def create_new_task(self, ...):
        # old inline code replaced with:
        return await submit_task(...)
```

This ensures `Yascheduler` (which currently imports `Scheduler`) continues
to work while the import is being broken.

## Risks / Trade-offs

- **Use cases are not yet testable independently**: They depend on the old
  `RemoteMachineRepository` and `CloudAPIManager` directly (not through domain
  ports). Full port-based injection arrives in Phase 4. During Phase 3, use
  cases accept these as-is.
- **Two code paths during transition**: `scheduler.py` both calls use cases
  AND still contains loop infrastructure. Risk of drift between old inline
  code and new use case. Mitigation: remove old inline code immediately after
  use case is wired.
- **client.py refactoring may break AiiDA**: AiiDA plugin imports `Yascheduler`.
  Mitigation: public API preserved; integration smoke test validates.
