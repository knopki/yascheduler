## proposal Round 1 — 2026-07-03

### Overview

The proposal faithfully captures every D1-D6 decision from the brief, the full schema/migration/SQL-file/domain/model/app/persistence change inventory, the "read path unchanged" / "allocated_ip stays" commitments, the cross-module data flow (implicitly), and the risk window. All 5 modified capability names are real specs. No implementation leakage. Breaking change is correctly scoped as internal (single callsite). Impact lists are complete.

### 🔴 Fixed

(None — read-only review.)

### 🟡 Addressed

(None — no minor issues worth flagging.)

### 🔴 Outstanding

No outstanding serious issues — batch ready to freeze.

### Detailed notes for the record

#### Brief coverage
- **D1–D6**: All six decisions are captured verbatim or in equivalent language (`ON DELETE SET NULL`, `allocate_to(node: Node)`, backfill, read path unchanged, `allocated_ip` stays, `_find_free_machines` returns `list[(MachineSession, Node)]`).
- **Schema/migration mapping**: Both the schema-column description and migration-004 backfill intent are present; the proposal correctly drops the brief's SQL snippets (no implementation leakage).
- **SQL files**: 5 task SQL files + migration + `schema.sql` = 7; the proposal lists all 7. The brief's excluded files (`count_by_status`, `get_ids_by_ip_and_status`, `update_meta`, `update_status`) stay correctly absent — they are read-path-ip-keyed or don't touch `allocated_node_id`.
- **Domain model changes**: `NewTask.allocated_node_id`, `Task.allocated_node_id`, `allocate_to(node: Node)` — all present.
- **Application changes**: `_find_free_machines`, `_try_start_on_machine`, `_allocate_free_machine` — all present.
- **Postgres adapter**: `insert`, `save`, `_row_to_task` — all present.
- **Read path unchanged**: All 6 sites explicitly enumerated and deferred to Surface A.
- **Cross-module data flow**: The proposal does not reproduce the brief's ASCII diagram, but the write path sequence (`list_enabled → _find_free_machines → list[(MachineSession, Node)] → _try_start_on_machine(session, node) → allocate_to(node) → save`) is fully described in prose, and the FK lifecycle (`ON DELETE SET NULL`) is stated. No gap.
- **Risk window**: The proposal does not have a standalone "Risk window" heading, but the information is implicit in the additive nature and the explicit deferral of the read path. The brief's risk analysis is the design rationale; the proposal captures the resulting decisions. Acceptable — not a gap.

#### Capability correctness
- `domain-entities` ✓ (spec at `openspec/specs/domain-entities/spec.md`). `NewTask` currently has `allocated_ip: str | None`; `Task` has `allocated_ip: str | None`; `allocate_to` takes `(ip: str)`. The proposal correctly describes adding `allocated_node_id: NodeId | None` and changing the signature to `(node: Node)`.
- `use-cases` ✓ (spec at `openspec/specs/use-cases/spec.md`). AllocateTask scenario currently calls `task.allocate_to(ip)`. The proposal correctly describes the change to `_find_free_machines` return type, `_try_start_on_machine` signature, and `allocate_to(node)` call.
- `postgres-persistence` ✓ (spec at `openspec/specs/postgres-persistence/spec.md`). `insert.sql` currently `RETURNING task_id, label, ip, status, metadata`. The proposal correctly describes adding `node_id` bind and read.
- `db-migrations` ✓ (spec at `openspec/specs/db-migrations/spec.md`). Correctly adds migration 004 to the sequence.
- `postgres-schema-apply` ✓ (spec at `openspec/specs/postgres-schema-apply/spec.md`). Correctly bumps `last_migration` and adds column to `CREATE TABLE`.

No contradictions: the existing specs describe the pre-change state; the proposal describes what should be updated.

#### Scope discipline
- **Surface A (SSH rekey)**: Explicitly deferred — "read-path switch to `allocated_node_id` + SSH `_sessions` rekey (Surface A, `ssh-rekey-node-id`)".
- **Surface D (NodeRepository.get)**: Explicitly deferred — "`NodeRepository.get(ip)` rekey (Surface D)".
- **Surface C (cloud host)**: Explicitly deferred — "cloud host arg (Surface C, forever ip)".
- **`allocated_ip` stays**: Stated twice — in "What Changes" ¶4 and in the deferred surfaces list.
- **Read path unchanged**: Stated with all 6 read sites enumerated.

#### No implementation leakage
The proposal contains no SQL snippets, no code blocks, no function bodies. It describes contractual changes (field additions, signature changes, return type changes, column additions). Everything is at the WHAT level. One borderline case: `allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL` is a column type description rather than SQL code, which is acceptable — it's the schema contract at the proposal level.

#### Breaking change clarity
- `allocate_to(ip) → allocate_to(node)` is described as internal (single callsite), which is accurate. No public API breaks.
- Schema migration is explicitly called "additive, backfilling, non-destructive".
- "No public API change" is stated plainly.

#### Impact completeness
All affected files are listed:
- Code: `model.py`, `allocate_task.py`, `postgres.py` ✓
- SQL: `schema.sql`, `migrations/004_add_allocated_node_id.sql`, 5 task SQL files ✓
- Tests: unit tests for domain model, application use cases, postgres persistence; integration tests ✓
- Specs: all 5 modified specs ✓
- GRACE-lite: `knowledge-graph.xml` + `MODULE_CONTRACT`/`MODULE_MAP`/`CHANGE_SUMMARY` ✓
- "No new dependencies", "No public API change" ✓

### Recommendation

APPROVE

## design+specs Round 1 — 2026-07-03

### Overview

All 6 decisions D1–D6 from the explore-brief are faithfully captured in design.md with rationale, alternatives-considered, risk window, and migration plan. The 5 delta specs are broadly consistent with the proposal and cover the correct scope. One serious naming inconsistency between specs must be resolved before freezing.

### 🔴 Fixed
- (none — read-only review)

### 🟡 Addressed
- **Missed preservation of unchanged content in MODIFIED block** (`postgres-persistence`: SQL file layout and lazy loading). The MODIFIED requirement drops two items from the original spec that are unchanged by this feature:
  - The `:param_name` syntax specification: `SQL files SHALL use `:param_name` syntax for pg8000 named-parameter binding.`
  - The scenario "load_query reads then caches" — verifies `load_query` reads from disk once then returns the cached string.
  
  MODIFIED blocks MUST include the FULL updated content per review criteria §3. Add these back unmodified.

  *Location*: `openspec/changes/task-allocated-node-id/specs/postgres-persistence/spec.md` — requirement "SQL file layout and lazy loading"

- **Minor wording inconsistency in domain-entities "with_context" scenario**: The "with_context replaces context wholesale" scenario correctly adds `allocated_node_id` to the preserved-fields list, but the "with_context chains with with_event" and "with_context preserves events" scenarios do not enumerate preserved fields (they describe behavior in terms of `_events` only). This is not a bug — the scenarios focus on event behavior and the field enumeration is not needed there. No action required. Flagging for awareness.

### 🔴 Outstanding

1. **Naming inconsistency: column `allocated_node_id` vs `node_id` in SQL layout**. The migration spec (ADDED) defines the column as `allocated_node_id`:
   ```
   ALTER TABLE yascheduler_tasks ADD COLUMN allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL
   ```
   But the postgres-persistence spec (MODIFIED) uses `node_id` as the column name throughout the SQL file layout:
   - INSERT cols: `(label, metadata, ip, status, node_id)` — would fail if actual column is `allocated_node_id`
   - UPDATE SET: `SET ... node_id = :node_id` — same
   - SELECT column lists: `task_id, label, ip, status, metadata, node_id` — same
   - RETURNING clauses: `... RETURNING task_id, label, ip, status, metadata, node_id` — same
   - `_row_to_task`: reads `row["node_id"]` — KeyError if pg8000 returns `"allocated_node_id"`

  The postgres-schema-apply spec consistently uses `allocated_node_id` (matching the migration). All specs must agree on the column name.

  **Fix**: Either:
  - (a) Change all SQL column references in postgres-persistence spec to `allocated_node_id` and `_row_to_task` to `row["allocated_node_id"]`, OR
  - (b) Change the migration DDL to `ADD COLUMN node_id` and adjust the design.md/explore-brief column name.

  The domain attribute name `allocated_node_id` is fine either way — only the SQL column name must match.

  *Locations*:
  - `openspec/changes/task-allocated-node-id/specs/db-migrations/spec.md:12-13` — `ADD COLUMN allocated_node_id`
  - `openspec/changes/task-allocated-node-id/specs/postgres-persistence/spec.md:18-20` — `SET node_id = :node_id`
  - `openspec/changes/task-allocated-node-id/specs/postgres-persistence/spec.md:23` — `RETURNING task_id, label, ip, status, metadata, node_id`
  - `openspec/changes/task-allocated-node-id/specs/postgres-persistence/spec.md:31-33` — `row["node_id"]`
  - `openspec/changes/task-allocated-node-id/specs/postgres-persistence/spec.md:88-100` — task SQL file templates
  - `openspec/changes/task-allocated-node-id/specs/postgres-schema-apply/spec.md:17-20,27` — uses `allocated_node_id` (consistent with migration)

### Detailed notes for the record

#### design.md — brief coverage
- **D1–D6**: All 6 are present with rationale and alternatives-considered. ✓
- **Risk window**: 3 risks + 2 trade-offs listed (lines 100-108). The dup-IP allocation window and backfill-best-effort scenarios are explicitly analyzed. ✓
- **Migration plan**: Deploy and rollback steps, forward-only migration, no config/public-API change, in-flight tasks unaffected. ✓
- **Open questions**: All resolved — section explicitly says "No outstanding open questions". ✓
- **Constraints**: `client.py` ip stays, cloud-host stays, `MachineSession` no `node_id`, `allocated_ip` stays — all stated in "Context" section. ✓

#### Consistency with proposal
- Additive column ✓, `allocate_to(node: Node)` ✓, backfill ✓, read path unchanged ✓, `_find_free_machines` returns pairs ✓, `allocated_ip` stays ✓. Zero contradictions.

#### Modified requirement completeness

| Delta spec | Original scenarios | Preserved | Modified | New | Missing |
|---|---|---|---|---|---|
| domain-entities — NewTask | 3 | 3 | 0 | 1 | 0 |
| domain-entities — Task | 16 | 14 | 2 (allocate_to, with_context) | 0 | 0 |
| use-cases — AllocateTask | 9 | 9 | 1 (allocate to free machine) | 2 | 0 |
| postgres-persistence — PostgresTaskRepository | 6 | 5 | 1 (insert returns) | 4 | 0 |
| postgres-persistence — SQL file layout | 4 | 3 | 0 | 4 | 1 (load_query reads then caches) |
| postgres-schema-apply — snapshot | 2 | 1 | 1 (CREATE TABLE includes) | 1 | 0 |

#### ADDED requirement correctness (db-migrations)
- Migration 004 has 8 scenarios in WHEN/THEN format with 4 `#` each. ✓
- SQL semantics match design: ALTER + UPDATE backfill + ON DELETE SET NULL + prefix_id 004 + tracker recording. ✓
- All 4 scenario types present: normal apply, NULL unallocated, FK lifecycle (ON DELETE SET NULL), rollback, fresh DB skip, unique-ip backfill, dup-ip best-effort. ✓

#### Scenario format
- All delta specs use exactly `####` (4 hashtags) for every scenario. ✓

#### No implementation leakage
- No python code, no function bodies, no runtime implementation detail in any spec. SQL snippets in db-migrations spec (migration DDL) are acceptable per criteria §6. ✓

#### Scope discipline
- Read-path switch (Surface A) deferred across all 5 specs. ✓
- SSH rekey / MachineSession.node_id not referenced anywhere. ✓
- NodeRepository.get rekey not referenced. ✓
- `allocated_ip` removal not proposed. ✓

#### Cross-spec consistency (excluding naming issue above)
- domain-entities: `allocate_to(node: Node)` binds both fields. use-cases: "Allocate to free machine" calls `task.allocate_to(node)` binding both. Consistent. ✓
- postgres-schema-apply CREATE TABLE includes `allocated_node_id` column matching migration DDL (column name consistent). ✓
- migration FK: `REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL`. schema-apply FK: same. Consistent. ✓

### Recommendation

**REQUEST CHANGES** — the naming inconsistency between migration (`allocated_node_id`) and SQL layout (`node_id`) must be resolved before freeze. This is a concrete integration issue: the SQL files would reference a column name that doesn't match the migration, causing runtime failures.

## design+specs Round 2 — 2026-07-03

### 🔴 Fixed
1. Naming consistency: column is `allocated_node_id` everywhere; pg8000 param is `:node_id`; `_row_to_task` reads `row["allocated_node_id"]`. Consistent across all 5 specs.
2. `:param_name` syntax paragraph restored in postgres-persistence SQL layout MODIFIED block.
3. `load_query reads then caches` scenario restored.

### 🟡 Addressed
(none)

### 🔴 Outstanding
No outstanding serious issues — batch ready to freeze.

## tasks Round 1 — 2026-07-03

### 🔴 Fixed
(none)

### 🟡 Addressed
1. Spec scenario imprecision: "Task SELECTs include allocated_node_id" listed `update_by_id`'s RETURNING, but `update_by_id` returns `task_id` only (used for row-existence check, not fed to `_row_to_task`). Declarative fix to the frozen spec scenario: exclude `update_by_id`'s RETURNING from the range.
2. No explicit test for "Migration 004 failure rolls back" — acceptable; tests generic migration runner infrastructure, not migration-004-specific logic.

### 🔴 Outstanding
No outstanding serious issues — batch ready to freeze.
