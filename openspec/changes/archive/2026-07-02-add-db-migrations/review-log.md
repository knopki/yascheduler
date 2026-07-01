## proposal Round 1 — 2026-07-01
### 🔴 Fixed
- (none)
### 🟡 Addressed
- (none)
### 🔴 Outstanding
- (none)

## design Round 1 — 2026-07-01
### 🔴 Fixed
- importlib.import_module replaced with importlib.util.spec_from_file_location + module_from_spec + exec_module (loads by file path; migration filenames may start with a digit and are not valid Python module names).
- _ensure_txn_open removed; the tracker INSERT now runs in a try/except inside the runner. Normal case: INSERT + COMMIT share migrate()'s transaction (fully atomic). On "no transaction in progress" (migrate() closed its txn): open a fresh BEGIN, retry INSERT, COMMIT. Trade-off and algorithm prose updated to match.
### 🟡 Addressed
- (none)
### 🔴 Outstanding
- (none)

## design Round 2 — 2026-07-01
### 🔴 Fixed
- (none — both Round 1 fixes correctly applied)
### 🟡 Addressed
- (none)
### 🔴 Outstanding
- (none)

## specs Round 1 — 2026-07-01
### 🔴 Fixed
- Removed the "Error reporting on existing schema" requirement from the postgres-schema-apply delta (MODIFIED section). Its "Database already initialized" / DatabaseError scenario contradicted the new "Schema applies cleanly on modern database" scenario — both described existing tables but asserted conflicting outcomes. With the fully-idempotent schema.sql (CREATE TABLE IF NOT EXISTS + DO block to_regclass guards), the "already exists" DatabaseError path is unreachable. The defensive except DatabaseError stays in the implementation as harmless dead code; the spec no longer asserts the unreachable behavior. `openspec validate` still passes.
### 🟡 Addressed
- (none)
### 🔴 Outstanding
- (none)

## specs Round 2 — 2026-07-01
### 🔴 Fixed
- (none — the Round 1 fix is correctly applied: "Error reporting on existing schema" requirement and its DatabaseError/already-initialized scenario are gone from specs/postgres-schema-apply/spec.md. The remaining four requirement blocks — "Transactional schema application" (fresh/legacy/modern/partial-failure), "Connection lifecycle" (close-after-success/failure), "schema.sql begins with a bootstrap DO block", "schema.sql is the full latest snapshot with no inline ALTERs" — are present and intact. No other requirement was accidentally removed or altered.)
### 🟡 Addressed
- (none)
### 🔴 Outstanding
- (none)

## tasks Round 1 — 2026-07-01
### 🔴 Fixed
- (none)
### 🟡 Addressed
- (none)
### 🔴 Outstanding
1. **Test 7.3 description is logically contradictory** — `apply_schema` seeds `yascheduler_migrations` with `last_migration = "001"`. Inserting `"000"` afterwards doesn't change `MAX = "001"`. `apply_migrations` then finds nothing pending (since no migration has `prefix_id > "001"`). The description claims `"001"` was "applied by the runner", but it was seeded by `apply_schema`. The assertion (count = 2) is correct, but the description misstates what's being tested. Fix: either (a) manually create tables (skip `apply_schema`) and insert `"000"` to exercise the `"001" > "000"` pending path, then explicitly assert the runner applied `"001"`; or (b) if the intent is "modern DB skips everything", correct the description and keep assertions.
2. **Missing `yascheduler/infra/__init__.py` re-export for `apply_migrations`** — Task 1.12 adds `apply_migrations` to `persistence/__init__.py` only, but Task 4.1 expects `from yascheduler.infra import apply_migrations`. The top-level facade (`yascheduler/infra/__init__.py`, line 28) does `from .persistence import PostgresUnitOfWork, apply_schema` and must also import `apply_migrations`. Without this, the import in `init.py` fails at module load. Fix: add `apply_migrations` to the import chain in either Task 1.12 or 4.1.

## tasks Round 1 — 2026-07-01
### 🔴 Fixed
- Task 1.12 now also updates the top-level adapters facade yascheduler/infra/__init__.py (re-export apply_migrations from .persistence, add to __all__, bump VERSION/CHANGE_SUMMARY). The original task only touched persistence/__init__.py, but init.py imports from yascheduler.infra (the top-level facade), so the import would have failed at module load.
- Task 7.3 rewritten to avoid the logical contradiction: instead of running apply_schema (which seeds to "001") then inserting "000" (which leaves MAX="001", so nothing is pending), the test now manually creates both yascheduler_migrations and yascheduler_nodes with a "000" tracker row, THEN runs apply_schema (DO block no-op via to_regclass guard) and apply_migrations (reads MAX="000", applies "001"). The assertion (count=2) and the pending-path isolation are preserved; the description now matches what actually happens.
### 🟡 Addressed
- (none)
### 🔴 Outstanding
- (none)

## tasks Round 2 — 2026-07-01
### 🔴 Fixed
- Both Round 1 fixes correctly applied:
  1. Task 1.12 now instructs updating BOTH `yascheduler/infra/persistence/__init__.py` AND `yascheduler/infra/__init__.py` (the top-level adapters facade), matching the actual file structure — `from yascheduler.infra import apply_migrations` resolves through `infra/__init__.py` → `persistence/__init__.py` → `postgres_migrations.py`.
  2. Task 7.3 re-written with logically consistent flow: manually create `yascheduler_migrations` + `yascheduler_nodes`, insert `"000"`, THEN `apply_schema(config)` (no-op via `to_regclass` guard), `apply_migrations(config)` (reads `MAX="000"`, applies `"001"`), assert count=2. The contradictory old flow (apply_schema seeds `"001"`, insert `"000"`, nothing pending) is gone.
### 🟡 Addressed
- (none)
### 🔴 Outstanding
- (none)
