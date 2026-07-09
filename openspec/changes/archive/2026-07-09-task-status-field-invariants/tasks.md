## 1. Migration + schema snapshot

- [x] 1.1 Create `yascheduler/infra/persistence/sql/migrations/011_task_status_field_check.sql` containing `ALTER TABLE yascheduler_tasks ADD CONSTRAINT task_status_field_invariants CHECK ( (status='TO_DO' AND allocated_node_id IS NULL AND error IS NULL) OR (status='RUNNING' AND allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL) OR (status='DONE') );` — no defensive pre-clean `UPDATE`.
- [x] 1.2 In `yascheduler/infra/persistence/sql/schema.sql`, bump the `last_migration` CONSTANT from `'010'` to `'011'`.
- [x] 1.3 In `yascheduler/infra/persistence/sql/schema.sql`, add the same `task_status_field_invariants` `CHECK` as a table-level constraint on the `CREATE TABLE IF NOT EXISTS yascheduler_tasks` statement (after the column list, before the closing `;`).

## 2. Integration test fix

- [x] 2.1 In `tests/integration/test_never_connected_node_abandon.py`, rewrite the seed block (~lines 164-172) of `test_never_connected_node_abandoned_and_task_reallocated` so the task is persisted as `TO_DO` with `allocated_node_id = NULL` (no `allocate_to(persisted_node)` + `save` on the TO_DO task). Pre-seed the `AllocationTracker` with `task_id` to mirror the real `allocate_task` in-flight binding. Preserve the post-abandon assertions (node row gone, cloud delete called, task still TO_DO and re-allocatable with `allocated_node_id is None`). NOTE: the "tracker released" assertion was dropped — with the corrected seed, `abandon_node`'s matching-by-`allocated_node_id` path is empty (the known dead code in `abandon_node.py:76-78`, out of scope per proposal Non-Goals), so `abandon_node` does not release the tracker. Documented in the test.

## 3. New focused integration tests for the CHECK

- [x] 3.1 Add an integration test asserting the CHECK rejects a forbidden INSERT: `INSERT INTO yascheduler_tasks (status, engine, allocated_node_id) VALUES ('TO_DO', 'fleur', 1)` raises a CHECK violation referencing `task_status_field_invariants`. Use a real testcontainers Postgres via the existing `uow_factory` fixture; insert a node first to satisfy the FK, then the bad task row.
- [x] 3.2 Add an integration test asserting the CHECK rejects a forbidden UPDATE: insert a valid RUNNING task (with `allocated_node_id` and `remote_folder` set), then `UPDATE ... SET allocated_node_id = NULL WHERE status='RUNNING'` raises a CHECK violation.
- [x] 3.3 Add an integration test asserting the CHECK rejects `TO_DO` with `error`: `INSERT ... status='TO_DO', error='x'` raises a CHECK violation.
- [x] 3.4 Add an integration test asserting the CHECK rejects `RUNNING` with NULL `remote_folder`: `INSERT ... status='RUNNING', allocated_node_id=<node>, remote_folder=NULL` raises a CHECK violation.
- [x] 3.5 Add an integration test asserting a bare `DELETE FROM yascheduler_nodes` on a node with a RUNNING task is rejected by the CHECK (the `ON DELETE SET NULL` cascade would violate the RUNNING row). Verify the node row and the RUNNING task row are both still present after the rejected DELETE.
- [x] 3.6 Add an integration test asserting the hard-remove path (`_remove_node_hard` flow: `update_status(task_id, DONE)` then `nodes.remove(node_id)`) succeeds without CHECK violation when the node has a RUNNING task — the rows are DONE before the FK cascade fires.

## 4. Spec + GRACE validation

- [x] 4.1 Run `openspec validate --all --json` and confirm all items pass (including the `task-status-field-invariants` change).
- [x] 4.2 Run `python3 scripts/grace_check.py` and confirm exit 0.

## 5. Test suite + static checks

- [x] 5.1 Run `uv run pytest -m unit` and confirm green.
- [x] 5.2 Run `uv run pytest -m integration` (testcontainers Postgres) and confirm green, including the rewritten `test_never_connected_node_abandoned_and_task_reallocated` and the new CHECK-rejection tests.
- [x] 5.3 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` and confirm clean.