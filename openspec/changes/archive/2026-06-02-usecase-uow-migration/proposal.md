## Why

Phases 1–4 built a clean hexagonal architecture: domain entities, repository
ports, PostgresUoW, SSH gateway, cloud provisioner adapter. Yet three of four
use cases (`allocate_task`, `consume_task`, `deallocate_nodes`) bypass all of
this by importing `DB` directly and operating on legacy `TaskModel`/`NodeModel`
row types. Only `submit_task` uses the proper UoW + domain entity path.

This creates a dual persistence pattern: `submit_task` goes through
`AbstractUnitOfWork` → domain `Task` → `TaskRepository`, while the other three
go through `DB` → `TaskModel` → internal repos. The `use-cases` spec already
defines the correct signatures (e.g., `allocate_task(task_id, uow_factory,
machine_gateway, engine, cloud)`) — the implementation never caught up.

## What Changes

- **Rewrite `allocate_task`** — accept `task_id` + `uow_factory` instead of
  `TaskModel` + `DB`. Load domain `Task` via UoW, validate engine, find free
  machine via `MachineGateway`, save transitions through domain lifecycle
  methods (`allocate_to`, `mark_running`).
- **Rewrite `consume_task`** — accept `task_id` + `uow_factory` instead of
  `TaskModel` + `DB`. Load domain `Task` via UoW, download outputs via
  `MachineGateway`, mark done/error through `task.complete()` / `task.fail()`.
- **Rewrite `deallocate_nodes`** — accept `uow_factory` instead of `DB`. Query
  nodes via `NodeRepository`, disable via UoW, delegate cloud deletion to
  `CloudProvisioner`.
- **Update `Orchestrator`** — accept `uow_factory` instead of `DB`. Producers
  query via UoW. SSH helper methods work with domain `Task` instead of
  `TaskModel`. Remove `self._db`.
- **Update `make_daemon`** — create `PostgresUnitOfWork` factory instead of
  passing `DB` to orchestrator. Keep `DB` creation only for schema migration.
- **Update `TaskRepository` port** — add `list_by_status` limit parameter to
  support producer queries with bounded results.

## Capabilities

### New Capabilities

### Modified Capabilities
- `use-cases`: Signatures change to accept `uow_factory` and domain types; remove `DB` dependency
- `orchestrator`: Remove `DB` dependency, use `uow_factory` for producer queries, work with domain `Task`
- `dependency-injection`: `make_daemon` creates UoW factory instead of passing `DB` to orchestrator
- `abstract-uow`: No requirement changes (port is sufficient)
- `domain-ports`: Add `limit` parameter to `TaskRepository.list_by_status`

## Impact

- Modified: `application/allocate_task.py`, `application/consume_task.py`,
  `application/deallocate_nodes.py` — full rewrite of signatures and internals.
- Modified: `application/orchestrator.py` — replace `DB` with `uow_factory`,
  convert producers to UoW queries, update SSH helpers for domain `Task`.
- Modified: `di.py` — `make_daemon` creates UoW factory, stops passing `DB` to
  orchestrator.
- Modified: `domain/ports.py` — `TaskRepository.list_by_status` gains optional
  `limit` parameter.
- Modified: `adapters/persistence/postgres.py` — `PostgresTaskRepository`
  supports `limit` parameter.
- No breaking changes to CLI commands, `Yascheduler` public API, or AiiDA plugin.
- No new dependencies.
- `docs/knowledge-graph.xml` updated — `M-APPLICATION-ALLOCATE`,
  `M-APPLICATION-CONSUME`, `M-APPLICATION-DEALLOCATE`, `M-APPLICATION-ORCHESTRATOR`
  drop `M-DB` dependency; gain `M-APPLICATION-UOW`.
