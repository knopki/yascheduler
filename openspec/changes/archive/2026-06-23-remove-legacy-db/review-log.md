# review-log — remove-legacy-db

## proposal Round 1 — 2026-06-23
### 🟡 Addressed (fixed in round 2)
- `PostgresUnitOfWork.__init__` requires `bus: MessageBus` — added migration bullet noting conftest constructs a bare `MessageBus()`.
- `test_persistence_adapter.py` builds repos via `PostgresTaskRepository(db.conn, db.executor)` — added note that the new fixture must also expose a raw `(connection, executor)` pair; `db.add_node(ip_addr=...)` → `uow.nodes.add(Node(ip=...))`.
### 🔴 Fixed
- `e2e-testing` spec references `db.get_task(task_id)` (spec.md:39) — was missing from Modified Capabilities; added `e2e-testing` to the modified list and to the "Update OpenSpec specs" bullet.
### 🔴 Outstanding
- (none after round 2)

## proposal Round 2 — 2026-06-23
### 🔴 Outstanding
- (none — PASS, frozen)

## design Round 1 — 2026-06-23
### 🟡 Addressed (fixed before freezing)
- D4: added explicit non-obvious renames for test_full_cycle (`task.ip`→`allocated_ip`, `task.metadata.get`→`task.context.local_folder`, `db.remove_node`→`uow.nodes.remove`).
- D3: tightened `test_migrate_idempotency` deletion rationale (apply_schema covered by test_postgres_schema; "call migrate twice" concept gone).
- D7: named `M-CLI-COMMANDS` (L118) explicitly as a confirmed `M-DB` dependent instead of generic "M-CLIENT and others".
- Grep guard: switched to `grep -F` fixed-string form to avoid regex-wildcard surprises.
### 🔴 Outstanding
- (none — APPROVE, frozen)

## specs Round 1 — 2026-06-23
### 🟡 Addressed (fixed before freezing)
- testing-unit MODIFIED "Shared test fixtures": reworded opening to "The project SHALL provide…" to satisfy the openspec validator's SHALL/MUST requirement for MODIFIED blocks.
### 🔴 Outstanding
- (none — APPROVE, frozen)

## tasks Round 1 — 2026-06-23
### 🟡 Addressed (fixed before freezing)
- Added task 6.2: permanent CI grep guard step in `.github/workflows/lint.yml` (design Risks committed to both a tasks.md step and a CI assertion; the original task 6.1 only had the manual step).
### 🔴 Outstanding
- (none — APPROVE, frozen)

## unfreeze — 2026-06-23 (user feedback)
### 🔴 Removed (decision-level, applied across proposal/design/tasks)
- Grep regression guard removed entirely. Rationale (user): once `db.py` is
  deleted, `import yascheduler.db` is a broken import caught by the existing
  ruff/zuban/import-linter/mypy CI workflow — a bespoke grep guard is
  redundant (YAGNI).
- Edits: proposal Impact line (removed "grep guard" clause); design Goal line
  + "Grep guard drift" risk + Migration Plan tail; tasks Section 6 deleted
  and Sections 7–9 renumbered → 6–8. Specs deltas untouched (no spec encoded a
  grep guard). Re-frozen after edits.