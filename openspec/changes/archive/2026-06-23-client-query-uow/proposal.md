## Why

The legacy `yascheduler/db.py` module (~540 LOC) is slated for removal. It is
the last abstraction between the application and `pg8000` that does not go
through the Unit-of-Work pattern, and the ONLY remaining production caller is
the `Yascheduler` client facade's `queue_get_tasks_async` (`client.py:149`).
Migrating it to a query use case over UoW removes the last production
dependency on `db.py`, leaving it test-only and enabling its full removal in a
follow-up proposal. `docs/ARCHITECTURE.md` §6.4 names this exact migration as
deferred until `db.py` removal becomes a concrete goal.

## What Changes

- NEW `query_tasks` application use case
  (`yascheduler/application/query_tasks.py`) delegating to
  `AbstractUnitOfWork.tasks` for status- and job-id-based queries, returning
  domain `Task` aggregates. Symmetric with `submit_task`, `allocate_task`,
  `deallocate_nodes`.
- MODIFY `Yascheduler.__init__` to accept a keyword-only
  `deps_factory: Optional[Callable[[Config], CLIDeps]] = None` (lazy default
  `make_cli_deps`) as a test-injection seam. `Yascheduler()` zero-arg
  construction remains valid.
- MODIFY `Yascheduler.queue_get_tasks_async` to construct `CLIDeps` via
  `self._deps_factory(self.config)`, call `query_tasks`, and map results to
  the public dict shape via a new client-local helper `_task_to_dict`. The
  legacy `DB.create` call is removed.
- The migration covers the full query method family
  (`queue_get_tasks_async`, `queue_get_task_async`, and their sync wrappers
  `queue_get_tasks`, `queue_get_task`). `queue_get_task_async` keeps its
  current delegation pattern (calls `queue_get_tasks_async(jobs=[task_id])`
  and returns the first result); the sync wrappers keep delegating to their
  async counterparts via `to_sync`.
- The 6-key public dict shape
  (`{task_id, label, ip, status, metadata, cloud}`) is preserved exactly,
  with `status` returning the enum member and `cloud` remaining `None`
  (verified: only the zero-production-caller
  `get_tasks_with_cloud_by_id_status` ever populates `cloud`; the two paths
  the facade uses — `get_tasks_by_status`, `get_tasks_by_jobs` — never do).
- `TaskStatus` import in `client.py` is re-sourced from `yascheduler.domain`
  (identical IntEnum values 0/1/2). Class constants
  `STATUS_TO_DO / RUNNING / DONE` are re-sourced correspondingly; values
  unchanged.
- FIXME comments added to:
  - `yascheduler/di.py` `CLIDeps.query` method (vestigial — zero production
    callers; remove in cleanup).
  - `yascheduler/adapters/persistence/postgres_uow.py` (no `backoff` on
    `InterfaceError`; cross-cutting gap with legacy `DB.run`, follow-up).

### Behavior deltas (welcome improvements, documented)

- `queue_get_tasks_async` no longer runs schema migration on every call
  (today: `DB.create(automigrate=True)` runs
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` per invocation).
- `queue_get_tasks_async` no longer leaks a pg8000 connection per call
  (today: `DB.create` result is never closed). The UoW `async with` block
  closes the connection via `__aexit__`.
- `queue_get_tasks_async` no longer retries transient `InterfaceError` via
  `backoff.on_exception`. The UoW/repo layer has no backoff anywhere (grep
  verified); query now homogenizes with submit/allocate/deallocate (which
  also lack backoff). Tracked via the FIXME for a cross-cutting follow-up.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `use-cases`: add `QueryTasks` use case requirement (status- and job-id-based
  read-only task queries via UoW).
- `package-facades`: codify `Yascheduler()` zero-arg stability, query method
  signature freeze, and the 6-key dict return shape as the public contract.
- `dependency-injection`: add the `deps_factory` test seam on
  `Yascheduler.__init__`.
- `testing-unit`: add characterization scenarios for the query path via the
  `deps_factory` seam.
- `test-db-integration`: add a testcontainers integration scenario that
  exercises the query path end-to-end against real PostgreSQL (no patches —
  implementation-agnostic golden master).
- `db-wrapper`: note that production callers drop to zero after this change
  (module becomes test-only, pending a separate removal proposal).

## Impact

- **Code**: `yascheduler/client.py` (modify),
  `yascheduler/application/query_tasks.py` (new),
  `yascheduler/application/__init__.py` (export),
  `yascheduler/di.py` (FIXME),
  `yascheduler/adapters/persistence/postgres_uow.py` (FIXME).
- **Tests**: `tests/unit/test_client_query.py` (new),
  `tests/integration/test_client_query_integration.py` (new).
- **Docs**: `docs/ARCHITECTURE.md` §2.9 stale-claim fix + §6.4 resolved
  marker; `docs/knowledge-graph.xml` gains `M-APPLICATION-QUERY-TASKS` plus
  two CrossLinks plus revised `M-CLIENT` annotations.
- **Public API**: no breaking changes. `Yascheduler.__init__` adds a
  keyword-only optional arg only. Query method signatures unchanged. Return
  dict shape unchanged.
- **Out of scope**: test-fixture migration (`fake_db.py`, `models.py`, and
  the 10 test files still importing from `yascheduler.db`); submit-path
  conversion to `deps_factory` (stays on its existing module-patch test
  pattern — FIXME in `yascheduler/client.py:queue_submit_task_async`,
  tracked here as a follow-up proposal); full removal of `db.py`.
