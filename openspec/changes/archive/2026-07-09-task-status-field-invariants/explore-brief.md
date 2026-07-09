# Explore Brief — task-status-field-invariants

## Problem
The `yascheduler_tasks` table has no DB-level enforcement of the persisted-state contract between `status`, `allocated_node_id`, `error`, and `remote_folder`. The contract exists only in Python (`Task.allocate_to`, `mark_running`, `complete`, `fail`, `reject`). A buggy caller or a future regression can persist forbidden combinations silently.

## Target persisted-state contract (exhaustive, 3 states)
| status   | allocated_node_id | error      | remote_folder |
|----------|-------------------|------------|---------------|
| TO_DO    | NULL (must)       | NULL (must)| free          |
| RUNNING  | NOT NULL (must)   | NULL (must)| NOT NULL (must) |
| DONE     | free              | free       | free          |

"free" = NULL or NOT NULL, no constraint.

## CHECK constraint
```sql
ALTER TABLE yascheduler_tasks ADD CONSTRAINT task_status_field_invariants CHECK (
    (status = 'TO_DO'   AND allocated_node_id IS NULL     AND error IS NULL)
 OR (status = 'RUNNING' AND allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL)
 OR (status = 'DONE')
);
```

## Alternatives rejected
- **Compact forbid-only form** (`NOT (status='TO_DO' AND allocated_node_id IS NOT NULL) AND ...`): looser, less self-documenting. Rejected — exhaustive form is stricter and documents the contract in place.
- **4th status `ALLOCATING`** for the cloud-allocation mid-flight state: rejected — audit confirmed no production path persists TO_DO+allocated_node_id; the state never reaches the DB, so a new status is unnecessary.
- **Application-only enforcement** (status quo): rejected — defense-in-depth; the DB is the last line.

## Key findings from code audit (all production `uow.tasks.save()` sites)
| call site | status at save | allocated_node_id | error |
|-----------|----------------|-------------------|-------|
| submit_task.py:107 | TO_DO | NULL | NULL |
| allocate_task.py:96 (reject) | DONE | NULL | "unsupported engine" |
| allocate_task.py:148 (alloc+mark_running) | RUNNING | NOT NULL | NULL |
| consume_task.py:191 (complete/fail) | DONE | NOT NULL or NULL | NULL or str |
| orchestrator.py:474 (MACHINE_GONE fail) | DONE | NOT NULL or NULL* | "node is gone" |
| manage_node.py:234 (update_status) | DONE | NOT NULL (then FK SET NULL) | NULL |

*NULL in the "double-abandon edge" where FK ON DELETE SET NULL already fired.

**No production code path persists TO_DO + NOT NULL allocated_node_id.**

## Dead code discovered
`abandon_node.py:76-78` reads TO_DO tasks and matches by `allocated_node_id == node.node_id` to release a "stuck" task. Since no production path creates TO_DO+allocated_node_id, `matching` is always empty and `tracker.discard(matching[0].task_id)` never fires. The comment at lines 71-75 defends a race that can't occur. This dead code is out of scope for this change (separate cleanup).

## Interaction with ON DELETE SET NULL
The FK is `ON DELETE SET NULL` deliberately:
- soft delete of a node with RUNNING tasks → `disable()` (row kept, no FK action)
- soft delete of a node with no RUNNING tasks → `remove()` (FK SET NULL on DONE rows)
- hard delete → RUNNING→DONE via `update_status`, then `remove()` (FK SET NULL on DONE rows)

**With the CHECK**: a bare `DELETE` on a node that still has RUNNING tasks will be **rejected** at the DB (the SET NULL cascade would violate the RUNNING row's CHECK). This is stronger protection. `_remove_node_hard` already does the right thing (flips RUNNING→DONE first), so it is unaffected.

## Migration safety
- Migration `011_task_status_field_check.sql`: `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)`.
- No production path creates forbidden states → existing data is clean → `ADD CONSTRAINT` succeeds.
- Defensive pre-clean `UPDATE` before `ADD CONSTRAINT` is NOT needed (audit confirms no bad rows in production). Optionally included as belt-and-braces, decision deferred to design.
- Update `last_migration` CONSTANT in `schema.sql` to `'011'`.
- Add the same `CHECK` to the `CREATE TABLE yascheduler_tasks` snapshot in `schema.sql`.

## Test fix required
`tests/integration/test_never_connected_node_abandon.py:169-171` fabricates TO_DO+allocated_node_id:
```python
inserted_task = inserted_task.allocate_to(persisted_node)  # TO_DO + node_id
await uow.tasks.save(inserted_task)                        # would violate CHECK
```
This state never occurs in production. The test must be rewritten to drive the real flow (TO_DO+NULL, tracker holds the binding in-memory) or to insert a RUNNING task instead.

## Cross-module data flows (unchanged by this change)
- `submit_task` → `uow.tasks.insert(NewTask)` (TO_DO, NULL node) → `with_remote_folder` → `save` (TO_DO, NULL node, remote_folder set)
- `allocate_task._try_start_on_machine` → `task.allocate_to(node).mark_running()` → `save` (RUNNING, NOT NULL node)
- `consume_task._finalize_task` → `task.complete()` or `task.fail(reason)` → `save` (DONE, node free, error free or set)
- `orchestrator._task_consumer_consumer` MACHINE_GONE → `task.fail("node is gone")` → `save` (DONE)
- `manage_node._remove_node_hard` → `update_status(task_id, DONE)` per RUNNING task → `nodes.remove(node_id)` (FK SET NULL on DONE rows)

## Open questions
1. Should the migration include a defensive `UPDATE ... SET allocated_node_id = NULL WHERE status = 'TO_DO'` before `ADD CONSTRAINT`? Decision: defer to design — audit says no bad rows exist, but belt-and-braces costs nothing.
2. Should the `abandon_node` dead-code cleanup be in this change or a separate one? Decision: **separate** — this change is DB-only, the cleanup is application-layer.
3. Should the test fix for `test_never_connected_node_abandon.py` be in this change? Decision: **yes, in this change** — the CHECK would break the test, so it must be fixed atomically.
4. CHECK constraint name: `task_status_field_invariants` (chosen).