## Why

The yascheduler codebase is being migrated from ip-as-identity to NodeId-as-identity because duplicate IPs are now a real, supported configuration (the same IP reachable through different jump hosts / ports / usernames — the original motivation for the whole renovation). Migration 003 dropped the `UNIQUE` constraint on `yascheduler_nodes.ip`; the subsequent changes (`node-id-keyed-mutators`, `deallocate-node-id-identity`) rekeyed the NodeRepository mutators and the deallocate flow. The remaining ip-as-identity surface with the widest blast radius is `Task.allocated_ip` — the schema field binding a Task to the Node it runs on. Its read path (`_task_consumer`'s `get_session(task.allocated_ip)`) is the exact site that blocks rekeying the SSH `_sessions` dict to NodeId (Surface A). This change adds `allocated_node_id` alongside `allocated_ip` and writes it at the single bind site, so Surface A can later switch the read path off ip without a schema change in the same step.

## What Changes

- `yascheduler_tasks` gets a new nullable column `allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL` (migration 004 + `schema.sql`). Deleting a node nulls the task's `allocated_node_id`; the task row and `allocated_ip` are preserved.
- Migration 004 backfills `allocated_node_id` for all existing tasks by joining on `ip` (assumes ip is unique-or-NULL at migration time — the dup-IP feature is not yet in production use).
- `Task` and `NewTask` gain `allocated_node_id: NodeId | None = None`.
- `Task.allocate_to(ip: str)` becomes `Task.allocate_to(node: Node)` — binds both `allocated_ip = node.ip` and `allocated_node_id = node.node_id` in one call. The single callsite (`_try_start_on_machine`) is updated.
- `_find_free_machines` returns `list[(MachineSession, Node)]` instead of `list[MachineSession]`, carrying the `Node` forward so the bind site has `node.node_id`. Session↔Node matching stays by ip (same ambiguity as today; full disambiguation lands with Surface A when sessions carry `node_id`).
- The 5 task SQL files (`insert`, `update_by_id`, `get_by_id`, `list_by_status`, `list_by_jobs`) add `node_id` to their INSERT/SET/SELECT/RETURNING lists. `_row_to_task` reads `node_id` → `NodeId`.
- The read path is **unchanged** in this change: all 6 read sites (`_task_consumer get_session`, `busy_ips`, `busy_node_ips`, `abandon_node matching`, `show_nodes`, `check_status`) keep using `allocated_ip`. They switch to `allocated_node_id` in Surface A (`ssh-rekey-node-id`).
- `allocated_ip` stays on the schema, on `Task`/`NewTask`, in `client.py`'s response, in logging, and as the cloud-host argument (Surface C, forever ip). This change is additive; it does not remove `allocated_ip`.
- No public API change (`Yascheduler` facade, CLI commands, INI config, AiiDA plugin untouched). `client.py`'s `ip` field is unchanged.

## Capabilities

### New Capabilities

(None.)

### Modified Capabilities

- `domain-entities`: `NewTask` and `Task` gain `allocated_node_id: NodeId | None`; `Task.allocate_to` signature changes from `(ip: str)` to `(node: Node)` and sets both `allocated_ip` and `allocated_node_id`. Scenarios for `allocate_to` and `NewTask`/`Task` field sets are updated.
- `use-cases`: `AllocateTask use case` requirement changes — `_find_free_machines` returns `list[(MachineSession, Node)]`; `_try_start_on_machine` takes `(session, node)` and calls `allocate_to(node)`. Scenario "Allocate to free machine" is updated.
- `postgres-persistence`: `TaskRepository.insert`/`save` bind `allocated_node_id`; `_row_to_task` reads `node_id`; the 5 task SQL files include `node_id`. Scenarios for insert/save/`_row_to_task` are updated.
- `db-migrations`: migration 004 (`add-allocated-node-id`) is added to the migration sequence. Scenario for migration 004 backfill is added.
- `postgres-schema-apply`: `schema.sql` `last_migration` constant bumped `'003'`→`'004'`; `yascheduler_tasks` CREATE TABLE includes `allocated_node_id`. Scenario for fresh-DB seed-to-004 is updated.

## Impact

- **Code**: `yascheduler/domain/model.py` (`NewTask`, `Task`, `allocate_to`), `yascheduler/application/allocate_task.py` (`_find_free_machines`, `_try_start_on_machine`, `_allocate_free_machine`), `yascheduler/infra/persistence/postgres.py` (`insert`, `save`, `_row_to_task`).
- **SQL**: `yascheduler/infra/persistence/sql/schema.sql` (column + `last_migration` bump), `migrations/004_add_allocated_node_id.sql` (new), 5 `task/*.sql` files (add `node_id`).
- **Tests**: `tests/unit/test_domain_model.py` (`Task.allocate_to(node)` + `allocated_node_id` field), `tests/unit/test_application_use_cases.py` (`AllocateTask` — `_find_free_machines` returns pairs, `_try_start_on_machine` takes pair), `tests/unit/test_persistence_postgres.py` or equivalent (`_row_to_task` reads `node_id`, `insert`/`save` bind it), `tests/integration/` (migration 004 backfill, schema apply with new column).
- **Specs**: `openspec/specs/domain-entities/spec.md`, `openspec/specs/use-cases/spec.md`, `openspec/specs/postgres-persistence/spec.md`, `openspec/specs/db-migrations/spec.md`, `openspec/specs/postgres-schema-apply/spec.md`.
- **GRACE-lite**: `docs/knowledge-graph.xml` (`M-DOMAIN-MODEL`, `M-APPLICATION-ALLOCATE`, `M-PERSISTENCE-POSTGRES` annotations updated); `MODULE_CONTRACT`/`MODULE_MAP`/`CHANGE_SUMMARY` in the edited source files.
- **No public API change**. **No new dependencies**. **Schema migration required** (migration 004 — additive, backfilling, non-destructive).
- **Surfaces deliberately deferred**: read-path switch to `allocated_node_id` + SSH `_sessions` rekey (Surface A, `ssh-rekey-node-id`); `NodeRepository.get(ip)` rekey (Surface D); cloud host arg (Surface C, forever ip).