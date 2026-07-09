## Context

The `yascheduler_tasks` table persists a three-state lifecycle (`TO_DO`, `RUNNING`, `DONE`) with three companion fields (`allocated_node_id`, `error`, `remote_folder`) whose permissibility depends on the status. The contract is currently enforced only by the domain model (`Task.allocate_to`, `mark_running`, `complete`, `fail`, `reject` in `yascheduler/domain/model.py`). A full audit of every production `uow.tasks.save()` and `uow.tasks.update_status()` call site confirmed that no production path violates the intended contract — but nothing at the DB layer catches a regression, a manual edit, or a future bug.

The `allocated_node_id` column carries a foreign key to `yascheduler_nodes.node_id` with `ON DELETE SET NULL`, which is deliberate: nodes may be removed, and DONE tasks keep their row with the binding nulled. Soft delete disables a node with RUNNING tasks (no FK action); hard delete flips RUNNING→DONE first, then removes the node (FK SET NULL on the now-DONE rows).

## Goals / Non-Goals

**Goals:**
- Enforce the exhaustive per-status field contract at the PostgreSQL layer via a single `CHECK` constraint, as defense-in-depth behind the existing Python-level enforcement.
- Ship the constraint via the established forward-only migration system (migration `011`) and keep `schema.sql` as the full latest snapshot.
- Fix the one integration test that fabricates a forbidden state (`test_never_connected_node_abandon.py`) so the constraint does not break the test suite.
- Strengthen protection against deleting a node that still has RUNNING tasks: the `ON DELETE SET NULL` cascade would NULL a RUNNING row's `allocated_node_id`, which the `CHECK` rejects — so a bare `DELETE` is now refused at the DB. Existing `_remove_node_hard` already flips RUNNING→DONE first and is unaffected.

**Non-Goals:**
- Removing the dead code in `abandon_node.py:76-78` (the always-empty `matching` list). Separate cleanup.
- Changing any application code path. The audit confirmed no production site violates the contract.
- Introducing a fourth status (e.g. `ALLOCATING`) for the cloud-allocation mid-flight state. The audit confirmed that state is never persisted; the in-memory `AllocationTracker` is the sole binding during cloud allocation.
- Adding CHECK constraints to `yascheduler_nodes` (out of scope; this change is task-table only).
- Changing the `ON DELETE SET NULL` FK behavior.

## Decisions

### Decision 1: Exhaustive three-branch CHECK over compact forbid-only form

The constraint is written as an exhaustive disjunction over the three enum values:

```sql
ALTER TABLE yascheduler_tasks ADD CONSTRAINT task_status_field_invariants CHECK (
    (status = 'TO_DO'   AND allocated_node_id IS NULL     AND error IS NULL)
 OR (status = 'RUNNING' AND allocated_node_id IS NOT NULL AND error IS NULL AND remote_folder IS NOT NULL)
 OR (status = 'DONE')
);
```

**Alternatives considered:**
- *Compact forbid-only form* (`NOT (status='TO_DO' AND allocated_node_id IS NOT NULL) AND NOT (status='TO_DO' AND error IS NOT NULL) AND NOT (status='RUNNING' AND allocated_node_id IS NULL) AND ...`): looser, less self-documenting, and silently permits states not enumerated. Rejected — the exhaustive form documents the full contract in place and is stricter (it forbids any status-field combination not explicitly listed, future-proofing against enum drift).
- *Per-field separate CHECKs*: harder to read, no single source of truth for the contract. Rejected.

**Rationale:** The exhaustive form is the single declarative source of truth for the persisted-state contract. A reader sees exactly the three legal states. The `DONE` branch is a no-op tautology (it imposes nothing on the three companion fields), which correctly encodes "DONE is free on all three."

### Decision 2: No defensive pre-clean UPDATE in the migration

The migration is `ALTER TABLE yascheduler_tasks ADD CONSTRAINT ... CHECK (...)` with no preceding `UPDATE`.

**Rationale:** The audit (see proposal "Impact" and explore-brief) confirmed zero production paths create the forbidden states. A defensive `UPDATE ... SET allocated_node_id = NULL WHERE status = 'TO_DO'` would silently mask real data corruption if it ever existed, and would be dead code in the common case. If the assumption ever breaks, `ADD CONSTRAINT` fails fast at migration time with a clear violation message pointing at the offending row — which is the desired behavior (surface corruption, don't hide it).

### Decision 3: The CHECK interacts with ON DELETE SET NULL to refuse bare node DELETEs with RUNNING tasks

This is a deliberate side effect, not a bug. With the CHECK in place, a `DELETE FROM yascheduler_nodes` on a node that still has a RUNNING task triggers the FK `ON DELETE SET NULL` cascade, which sets `allocated_node_id = NULL` on the RUNNING row, which violates the RUNNING branch (`allocated_node_id IS NOT NULL`). The DELETE is rejected.

**Rationale:** This is exactly the invariant we want enforced. The existing `_remove_node_hard` in `manage_node.py` already does the right thing — it flips RUNNING tasks to DONE via `update_status(task_id, DONE)` *before* calling `nodes.remove(node_id)`, so the rows are DONE by the time the FK cascade fires (DONE allows NULL `allocated_node_id`). The new behavior only catches paths that skip that step — i.e. bugs, manual edits, or a future regression. No existing code path is broken.

The `ON DELETE SET NULL` FK clause is **kept as-is**. It still serves DONE rows (freeing their `allocated_node_id` when a node is removed), which is the intended "разрывается связь с done tasks" behavior.

### Decision 4: Test fix rewrites the seed, not the assertion

`tests/integration/test_never_connected_node_abandon.py:166-171` currently does:
```python
inserted_task = await uow.tasks.insert(NewTask(label="stuck", engine="test_engine"))
inserted_task = inserted_task.allocate_to(persisted_node)   # TO_DO + allocated_node_id
await uow.tasks.save(inserted_task)                          # persists forbidden state
```

This fabricates a state that never occurs in production. The real cloud-allocation flow does `allocate_to(node).mark_running()` together and saves as RUNNING; the in-memory `AllocationTracker` holds the binding during the in-flight cloud allocation, and the DB never sees TO_DO+allocated_node_id.

**Fix approach:** The test's intent is to verify the abandon path: dead node row removed, cloud delete called, tracker released, task re-allocatable. The seed is rewritten so the task is persisted as `TO_DO` with `allocated_node_id = NULL` (the real persisted shape), and the `AllocationTracker` is pre-seeded with the task_id (mirroring what `allocate_task` does in production before cloud provisioning). The assertions on post-abandon state (node row gone, tracker released, task still TO_DO and re-allocatable) are preserved. The `abandon_node` matching-by-allocated_node_id branch remains dead in this test too — but that dead code is out of scope (see Non-Goals).

**Alternative rejected:** rewriting the assertions to match the fabricated state instead of rewriting the seed. Rejected because that would test an impossible state and lock in the dead-code path as if it were live behavior.

### Decision 5: Constraint name `task_status_field_invariants`

Chosen for clarity. The name states the contract domain (status-driven field invariants) and is unique within the table.

## Risks / Trade-offs

- **[Risk] A legacy or manually-edited DB has a forbidden row → migration fails.**
  → Mitigation: the audit confirmed no production path creates forbidden rows. If a deployment hits this, the `ADD CONSTRAINT` error names the violating row and the operator can fix it manually before re-running. No silent masking.

- **[Risk] The CHECK rejects a future legitimate state not in the three-branch enumeration.**
  → Mitigation: adding a fourth status (e.g. `ALLOCATING`) would require a migration that drops and recreates the CHECK with the new branch — the same cost as the enum-change migration that would accompany the new status anyway. The exhaustive form makes this explicit rather than implicit.

- **[Risk] The CHECK + `ON DELETE SET NULL` interaction surprises an operator who runs a raw `DELETE FROM yascheduler_nodes` on a node with RUNNING tasks.**
  → Mitigation: the error message from PostgreSQL identifies the violating CHECK and the RUNNING row. The operator is guided toward `_remove_node_hard` (the `yasetnode --remove-hard` path) which already handles the transition correctly. This is the desired defense-in-depth.

- **[Trade-off] The exhaustive form is slightly more verbose than a forbid-only form.**
  → Accepted: readability and strictness outweigh brevity.

- **[Trade-off] The test fix changes the seed of an integration test but preserves its assertions.**
  → Accepted: the new seed matches production reality; the old seed tested an impossible state.

## Migration Plan

1. **Add migration file** `yascheduler/infra/persistence/sql/migrations/011_task_status_field_check.sql` containing the `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)`.
2. **Update `schema.sql`**: bump `last_migration` CONSTANT from `'010'` to `'011'`; add the same `CHECK` to the `CREATE TABLE yascheduler_tasks` statement.
3. **Fix the integration test** `tests/integration/test_never_connected_node_abandon.py` seed block.
4. **Verify**:
   - `openspec validate --all --json` passes.
   - `python3 scripts/grace_check.py` passes.
   - `uv run pytest -m unit`, `uv run pytest -m integration` (with testcontainers Postgres) pass.
   - A focused integration test asserts the CHECK rejects forbidden states (insert TO_DO+allocated_node_id → violation; insert RUNNING+NULL allocated_node_id → violation; insert RUNNING+NULL remote_folder → violation; insert TO_DO+error → violation).
   - A focused integration test asserts a bare `DELETE FROM yascheduler_nodes` on a node with a RUNNING task is rejected by the CHECK.
5. **Rollback**: forward-only migration system — no automatic rollback. If rollback is required, an operator manually runs `ALTER TABLE yascheduler_tasks DROP CONSTRAINT task_status_field_invariants;` and removes the migration row from `yascheduler_migrations`. This is documented policy, not a runner feature.

## Open Questions

None remaining. The four open questions from `explore-brief.md` are resolved:
1. Defensive pre-clean UPDATE → **no** (Decision 2).
2. `abandon_node` dead-code cleanup scope → **separate change** (Non-Goals).
3. Test fix in this change → **yes** (Decision 4).
4. Constraint name → `task_status_field_invariants` (Decision 5).