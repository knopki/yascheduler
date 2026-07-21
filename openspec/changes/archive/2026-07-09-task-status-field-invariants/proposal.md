## Why

The `yascheduler_tasks` table has no DB-level enforcement of the persisted-state contract between `status`, `allocated_node_id`, `error`, and `remote_folder`. The contract is enforced only in Python (`Task.allocate_to`, `mark_running`, `complete`, `fail`, `reject`). A buggy caller, a future regression, or a manual DB edit can persist forbidden combinations silently — e.g. a RUNNING task with NULL `allocated_node_id`, or a TO_DO task with an `error`. The database is the last line of defense and currently has none.

Rejected alternatives are documented in `explore-brief.md` (compact forbid-only form, a 4th `ALLOCATING` status, application-only enforcement).

## What Changes

- Add a `CHECK` constraint `task_status_field_invariants` to `yascheduler_tasks` enforcing the exhaustive per-status field contract:
  - `TO_DO`: `allocated_node_id IS NULL AND error IS NULL`
  - `RUNNING`: `allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL`
  - `DONE`: unconstrained on those three fields
- Add migration `011_task_status_field_check.sql` applying the `CHECK` via `ALTER TABLE ... ADD CONSTRAINT`. No defensive pre-clean `UPDATE` is included — the audit confirmed zero production paths create the forbidden states, so `ADD CONSTRAINT` succeeds on existing data; if that assumption ever breaks the constraint fails fast at migration time.
- Update `schema.sql`: add the same `CHECK` to the `CREATE TABLE yascheduler_tasks` snapshot and bump `last_migration` to `'011'`.
- Fix `tests/integration/test_never_connected_node_abandon.py` which fabricates a `TO_DO + allocated_node_id` state that never occurs in production and would now violate the `CHECK`. The test is rewritten to drive the real flow (TO_DO with NULL `allocated_node_id`; the allocation binding is held in-memory by the `AllocationTracker`, which is how production actually works).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `db-migrations`: add Migration 011 — the `task_status_field_invariants` `CHECK` constraint; update the migration edit procedure reference to the new `last_migration = '011'`.
- `postgres-schema-apply`: the `CREATE TABLE yascheduler_tasks` snapshot in `schema.sql` gains the `task_status_field_invariants` `CHECK` constraint and the `last_migration` CONSTANT is bumped to `'011'`.

## Impact

- **DB schema** (`yascheduler/infra/persistence/sql/schema.sql`): `CREATE TABLE yascheduler_tasks` gains the `CHECK`; `last_migration` CONSTANT bumped from `'010'` to `'011'`.
- **Migration** (`yascheduler/infra/persistence/sql/migrations/011_task_status_field_check.sql`): new file, forward-only, additive (`ADD CONSTRAINT`).
- **Tests** (`tests/integration/test_never_connected_node_abandon.py`): the seed block at lines ~166-171 that does `allocate_to(persisted_node)` + `save` on a TO_DO task must be reworked so it no longer persists the forbidden state. The test's intent (verify the abandon path removes the DB row, releases the tracker, leaves the task re-allocatable) is preserved.
- **Application code**: no changes. The audit confirmed every production `uow.tasks.save()` / `update_status()` site already produces states that satisfy the `CHECK`. Dead code in `abandon_node.py:76-78` (an always-empty `matching` list that reads TO_DO tasks by `allocated_node_id`) was discovered during the audit but is out of scope — separate cleanup.
- **Public API / CLI / INI / AiiDA entrypoint**: unchanged.
- **Side effect (stronger protection)**: a bare `DELETE FROM yascheduler_nodes` on a node that still has RUNNING tasks is now **rejected** by the DB (the `ON DELETE SET NULL` cascade would NULL out a RUNNING row's `allocated_node_id`, violating the `CHECK`). Existing `_remove_node_hard` flips RUNNING→DONE first and is unaffected; the new behavior is defense-in-depth against future bugs.