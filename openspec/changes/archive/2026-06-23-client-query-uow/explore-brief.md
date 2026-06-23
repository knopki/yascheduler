# explore-brief — client-query-uow

## Goal
Migrate `Yascheduler` client facade query methods (`queue_get_tasks_async`,
`queue_get_task_async`, plus sync wrappers) off the legacy `yascheduler/db.py`
module onto the Unit-of-Work pattern. This is the next step toward removing
`db.py` entirely; test consumers are explicitly out of scope and deferred.

## Current state (verified)
- The ONLY production caller of legacy `DB.create` is `client.py:149`
  (`queue_get_tasks_async`). `grep` for `DB.create` in `yascheduler/` returns
  exactly one match.
- All CLI adapters (`check_status`, `show_nodes`, `manage_node`, `submit`)
  already use `deps.uow_factory()` directly; they do NOT go through the
  `Yascheduler` facade.
- `docs/ARCHITECTURE.md` §6.4 names this exact migration as deferred.
- §2.9 of the same doc claims `db.py` is "Consumed by `client.py` and
  `CloudProvisionerImpl`" — STALE; `CloudProvisionerImpl` was decoupled in
  `di.py` v5.0.0. Only `client.py` remains.
- `CLIDeps.query(task_id)` already exists in `di.py:105-108` but has zero
  production callers (only its own unit test). Vestigial.
- `queue_get_tasks_async` / `queue_get_task_async` have ZERO unit/integration
  test coverage today.

## Rejected alternatives (and why)
- **Option A (extend CLIDeps with `query_many` only, no use case)** — rejected
  for lack of symmetry with `submit_task` / `allocate_task` /
  `deallocate_nodes` use cases.
- **Option X (DTO `TaskView`)** — rejected as one-more-type-to-retire; the
  inline dict mapping in `client.py` is sufficient given the dict shape is
  itself the frozen public contract.
- **Test seam Option (i) (module-level patch of `make_cli_deps`)** — rejected
  because the patched symbol landscape changes during the swap; pure
  characterization tests wouldn't survive the refactor unchanged. Replaced by
  constructor injection (Option α) per the user's "optional test args"
  allowance.
- **Test seam Option β (patch + accept one fixture edit at swap)** — rejected
  in favor of α for stricter characterization-first discipline.
- **Test seam Option (ii) integration-only (γ alone)** — kept as γ, but
  paired with α so unit characterization also survives swap.
- **Option (ii)/(iii) for backoff loss (UoW-wide retry or query-local
  retry)** — rejected as scope creep. Backoff gap is pre-existing and
  cross-cutting across all UoW paths; gets FIXME + follow-up note instead.
- **Folding test-fixture migration (`fake_db.py`, `models.py`, 10 test
  files) into this proposal** — rejected; would bloat blast radius. Production
  consumer first; tests as a separate follow-up proposal.

## Final approach

### Decisions locked
1. New `application/query_tasks.py` use case:
   `query_tasks(jobs, statuses, uow_factory) -> list[Task]`.
2. `Yascheduler.__init__` gains kw-only `deps_factory: Optional[Callable[[Config], CLIDeps]] = None`;
   lazy default `make_cli_deps`. `Yascheduler()` still works.
3. Inline `_task_to_dict(t: Task) -> Mapping[str, Any]` in `client.py`
   (no new DTO type).
4. Status field returns the enum member (`t.status`, `domain.TaskStatus`),
   not `.value` — preserves cross-class IntEnum equality and `.name` access.
5. Six-key dict shape preserved exactly:
   `{task_id, label, ip, status, metadata, cloud}` with `cloud: None`
   (verified: legacy paths `get_tasks_by_status`/`get_tasks_by_jobs` never
   populate `cloud`; only the zero-caller `get_tasks_with_cloud_by_id_status`
   does).
6. `TaskStatus` import re-sourced from `yascheduler.domain` (not `yascheduler.db`).
7. Class constants `STATUS_TO_DO/RUNNING/DONE` re-sourced from
   `domain.TaskStatus`; values unchanged (0/1/2).
8. `queue_get_task_async` keeps delegating to `queue_get_tasks_async`
   (single mapping helper, minimal diff).
9. Submit path unchanged (stays on its existing module-patch test pattern);
  routing submit through `deps_factory` too is out of scope, noted as follow-up.

### Cross-module data flow
```
Yascheduler.queue_get_tasks_async(jobs, status)
  -> self._deps_factory(self.config)            # CLIDeps (test seam)
  -> query_tasks(jobs, statuses, deps.uow_factory)   # application use case
  -> async with uow_factory() as uow:
       uow.tasks.list_by_status(set(statuses))  OR
       uow.tasks.list_by_jobs(list(jobs))
  -> [_task_to_dict(t) for t in tasks]          # client-local mapping
```

### Behavior deltas (documented improvements, not regressions)
- Today: `DB.create(automigrate=True)` runs `ALTER TABLE ... ADD COLUMN IF
  NOT EXISTS username/port` on EVERY query call. After: no migration on query
  path. Welcome improvement.
- Today: `DB.create` opens a connection that `queue_get_tasks_async` NEVER
  closes (leak per call). After: `async with uow_factory()` closes via
  `__aexit__`. Welcome improvement.
- Today: `DB.run` retries `InterfaceError` via `@backoff.on_exception(fibo,
  max_time=60)`. UoW/repos have ZERO backoff (verified by grep). Migration
  homogenizes query with the rest of the app (submit/allocate/deallocate also
  lack backoff). FIXME added to `postgres_uow.py`, follow-up proposal filed
  separately if it bites.

### FIXMEs added
- `yascheduler/di.py` on `CLIDeps.query` — vestigial, remove in cleanup.
- `yascheduler/adapters/persistence/postgres_uow.py` — no backoff on
  `InterfaceError`; cross-cutting gap, follow-up.

## Test plan
- NEW `tests/unit/test_client_query.py` — characterization via `deps_factory`
  seam (inject `FakeCLIDeps`). Asserts: dispatch routing, mutual-exclusivity
  `ValueError`, six-key dict shape, enum-preserve `status`, `allocated_ip`
  None -> `ip == ""`, `cloud: None`.
- NEW `tests/integration/test_client_query_integration.py` — testcontainers
  Postgres. Submit real task, query back via `queue_get_tasks(jobs=[id])` and
  `queue_get_tasks(status=[0])`, assert six-key shape. Zero patches;
  implementation-agnostic by construction (golden master for the swap).

## GRACE-lite obligations
- New module: `M-APPLICATION-QUERY-TASKS` (CORE_LOGIC).
- CrossLinks: `M-CLIENT -> M-APPLICATION-QUERY-TASKS` (delegates query);
  `M-APPLICATION-QUERY-TASKS -> M-PERSISTENCE-UOW`.
- `M-CLIENT` annotations: add `deps_factory`, `_task_to_dict`, revised
  `queue_get_tasks_async` contract.
- `M-DB` annotations trim: no production callers remain after this change.
- `docs/ARCHITECTURE.md` §2.9 stale claim + §6.4 resolved marker.

## OpenSpec delta targets (6)
1. `package-facades` — `Yascheduler()` zero-arg stability + query method
   signatures frozen + 6-key dict shape contract.
2. `use-cases` — `query_tasks` requirement.
3. `dependency-injection` — `deps_factory` test seam on `Yascheduler.__init__`.
4. `testing-unit` — characterization scenario via `deps_factory`.
5. `test-db-integration` — γ integration scenario (testcontainers).
6. `db-wrapper` — note production callers drop to zero (test-only).

## Known open questions
None. All locked in explore conversation rounds.
