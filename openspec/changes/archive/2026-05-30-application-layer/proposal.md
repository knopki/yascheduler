## Why

Phase 3 of the Hexagonal + DDD migration. Phases 1-2 built the domain model
and persistence layer. These are currently unused — the system still runs
entirely through `scheduler.py` (806 lines) and `client.py`.

This change wires the new layers together: use cases orchestrate domain
objects through ports, the daemon orchestrator manages producer-consumer
loops, and DI factories compose the dependency graph per entry point.

The result: `scheduler.py` sheds ~500 lines of business logic, becoming a
thin loop runner. `client.py` breaks its import of `scheduler.py`.

## What Changes

- Create 4 use cases: `submit_task`, `allocate_task`, `consume_task`,
  `deallocate_nodes` — each a single async function orchestrating domain
  objects through ports.
- Create `application/orchestrator.py` — daemon poll loops, concurrency
  management, cancellation (extracted from `scheduler.py` start/stop and
  `create_producer_consumers`).
- Create `application/uow.py` with `AbstractUnitOfWork` Protocol (moved from
  domain as it depends on `TaskRepository`/`NodeRepository` which are domain ports).
- Create `di.py` — composition root with `make_daemon()` and `make_cli_deps()`
  factories.
- Refactor `scheduler.py` — replace inline logic with use-case calls. Keep
  the producer-consumer infrastructure but replace consumer bodies.
- **BREAKING** `client.py` — stops importing `scheduler.py`. `Yascheduler`
  now creates a lightweight `SubmitTask` use case via DI instead of
  instantiating the entire daemon.
- Refactor `utils.py` CLI commands to use use cases via `make_cli_deps()`.

## Capabilities

### New Capabilities
- `use-cases`: SubmitTask, AllocateTask, ConsumeTask, DeallocateIdleNodes —
  application services orchestrating domain objects through ports.
- `orchestrator`: Long-running daemon with producer-consumer loops, concurrency
  limits, graceful shutdown.
- `dependency-injection`: Manual DI factories per entry point (daemon, CLI,
  AiiDA) composing adapters and use cases at startup.
- `abstract-uow`: `AbstractUnitOfWork` Protocol defining the UoW contract
  (moved from domain to application to resolve package dependency).
- `client-refactor`: `Yascheduler` facade delegates to use cases via DI;
  breaks import of `scheduler.py`.

### Modified Capabilities
<!-- No existing specs affected — specs are domain-level. -->

## Impact

- New files: `application/submit_task.py`, `allocate_task.py`, `consume_task.py`,
  `deallocate_nodes.py`, `orchestrator.py`, `uow.py`, `di.py`.
- Modified: `scheduler.py` (thins ~500 lines → ~300 lines of loop infrastructure).
- Modified: `client.py` (breaks import of `scheduler.py`).
- Modified: `utils.py` (CLI commands switch to use cases).
- No new dependencies. No breaking API changes to external consumers
  (CLI commands, `Yascheduler` public methods).
- `docs/knowledge-graph.xml` updated.
