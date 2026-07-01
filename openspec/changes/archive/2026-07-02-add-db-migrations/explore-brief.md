# Explore Brief — add-db-migrations

## Problem
yascheduler has no DB migration system. Schema evolution today is done by appending
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` lines to `schema.sql`, applied by
`apply_schema()` during `yainit --schema`. This is untracked (no record of what was
applied when), non-sequential (no ordering of migrations), and gives no path for
non-idempotent DDL (rename, drop, data transformations) or operations that cannot run
inside a single transaction (`CREATE INDEX CONCURRENTLY`, `VACUUM`). Legacy production
databases exist (have `yascheduler_nodes` but lack columns added later, e.g. `username`,
`port`); fresh installs and modern databases also need to coexist under one mechanism.

## Rejected alternatives
- **Pure migrations, no snapshot (Django-style forward-only)** — fresh DBs would replay
  the entire history on every install; slow and fragile as history grows. Rejected.
- **Snapshot-only, keep ALTERs inline in `schema.sql`** — current approach; gives no
  tracking, no ordering, no path for non-idempotent or non-transactional operations.
  Rejected.
- **Seed `last_migration` only when `yascheduler_migrations` table is absent, using a
  single `CREATE TABLE IF NOT EXISTS` guard** — wrong: `IF NOT EXISTS` is false once the
  table is created by the same statement, so the seed INSERT never runs on a fresh DB.
  Rejected (the DO block must guard both CREATE and seed together inside one
  `IF to_regclass(...) IS NULL` check).
- **Single-row `last_applied` tracker (alembic_version-style)** — no audit trail of
  what was applied when. Rejected in favor of multi-row journal.
- **Best-effort COMMIT that silently drops the tracker record when a `.py` migration
  closed its transaction and did not reopen** — silently loses the tracker record, causing
  re-application on next run. Rejected in favor of explicit reopen-for-tracker.
- **Runner validates duplicate `prefix_id` at startup** — runner should apply, not
  validate; validation belongs in unit tests. Rejected.
- **Require migrations to be idempotent** — impossible for non-transactional operations
  (`CONCURRENTLY`, `VACUUM`) and unnecessary under the snapshot+tracker model. Rejected.
- **Fix a specific `prefix_id` format (e.g. `00N` or timestamp)** — over-constrains; the
  spec only needs "token before the first `_`, unique, string-sort order". Rejected.
- **Discovery of `.py` migration class via a module-level marker variable or a fixed
  class name** — explicit marker is ceremony; fixed name shadows the base class. Use
  `inspect` to find exactly one subclass of `Migration` per file, fail on 0 or >1.

## Final approach (decisions locked with user)
| Axis | Decision |
|---|---|
| Model | Snapshot + deltas: `schema.sql` = full latest snapshot (CREATE TABLE with all current columns, NO inline ALTERs); migrations = the evolution DDL/data for legacy and intermediate DBs |
| Tracker table | `yascheduler_migrations(migration_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`; `last_applied` = `SELECT MAX(migration_id) FROM yascheduler_migrations` (string sort); `NULL` (empty table) → run all pending |
| Bootstrap (in `schema.sql`, DO block at the top, before any CREATE TABLE) | `IF to_regclass('yascheduler_migrations') IS NULL THEN CREATE TABLE ... ; IF to_regclass('yascheduler_nodes') IS NULL THEN INSERT seed (last_migration) END IF; END IF;`. Three cases: (a) fresh DB (no nodes, no tracker) → CREATE tracker + seed `last_migration`; (b) legacy DB (nodes exists, no tracker) → CREATE tracker, NO seed → migrations run all; (c) modern DB (tracker exists) → skip entirely. `last_migration` declared as a PL/pgSQL CONSTANT in the DO block (single point of edit). |
| `last_migration` value | A CONSTANT TEXT in the DO block; updated by hand when a new migration is added. This is the only manual edit point in `schema.sql` per migration. |
| ALTERs (username/port) | Moved out of `schema.sql` into `migrations/<prefix_id>_add_username_port.sql` (the first migration). `schema.sql` CREATE TABLE statements already include `username` and `port` columns (latest snapshot). Legacy DBs get the columns via the migration; fresh DBs already have them (skip the migration via seed). |
| Migration files | `infra/persistence/sql/migrations/{prefix_id}_{rest}.sql` or `.py`. `prefix_id` = token before the first `_`, unique across all migration files, determines order by string sort. Format not fixed by spec. |
| Application order | Sequential, sorted by `prefix_id` as a string. Each migration in its own transaction. |
| `.sql` runner | `BEGIN → conn.run(sql_text) → INSERT INTO yascheduler_migrations(migration_id) VALUES (?) → COMMIT`. ROLLBACK (best-effort) on error; do not record tracker; re-raise. Multi-statement `.sql` works via pg8000 native Simple Query (no special handling). |
| `.py` runner | `BEGIN → migration.migrate() → check-txn-open → INSERT tracker → COMMIT`. If `migrate()` closed the transaction (called `self.commit()` without `self.begin()`), the runner OPENS a new `BEGIN` before the tracker INSERT (best-effort reopen). ROLLBACK (best-effort) on error; re-raise. |
| `Migration` base class | `__init__(self, config: PostgresDbConfig, conn: pg8000.native.Connection, log: logging.Logger)`; stores all three as instance attributes; `migrate(self) -> None` raises `NotImplementedError`; helpers `begin() -> conn.run("BEGIN")` and `commit() -> conn.run("COMMIT")` for migrations needing non-transactional operations (`CONCURRENTLY`/`VACUUM`): `self.commit()` → run command → `self.begin()`. |
| `.py` class discovery | `inspect` the imported module; find exactly one subclass of `Migration` (excluding `Migration` itself); fail with a clear error on 0 or >1 subclasses. |
| Transaction contract for `.py` | Runner wraps `migrate()` in `BEGIN`. Documented: a migration runs inside an open transaction by default; helpers `self.begin()`/`self.commit()` split it for non-transactional ops; if the migration closes the txn, the runner reopens one for the tracker INSERT (best-effort). Migrations are NOT required to be idempotent (non-transactional ops make it impossible). |
| Duplicate `prefix_id` detection | Unit test (a test that scans `migrations/` and asserts uniqueness), NOT a runner responsibility. |
| Entrypoint | `yainit` (default and `--schema`) calls `apply_schema(config.db)` then `apply_migrations(config.db)`. `apply_schema` remains idempotent (CREATE TABLE IF NOT EXISTS + DO block); `apply_migrations` reads the tracker and applies pending. |
| Idempotency of migrations | NOT required. Snapshot + tracker model means each migration runs at most once per DB (guarded by tracker). Non-transactional ops make idempotency impossible anyway. |
| Three edit points when adding migration `<prefix_id>_...` | (1) Create the migration file; (2) update the `last_migration` CONSTANT in `schema.sql` DO block; (3) update the snapshot DDL in `schema.sql` if the migration changes the schema. |

## Cross-module data flows
- `yainit` (`entrypoints/cli/init.py`) `init()` → `apply_schema(config.db)` (existing,
  updated `schema.sql` with DO block) → `apply_migrations(config.db)` (NEW, in
  `infra/persistence/postgres_migrations.py`).
- `apply_migrations(config: PostgresDbConfig)` → open pg8000 native Connection →
  `SELECT MAX(migration_id) FROM yascheduler_migrations` (NULL if empty) → scan
  `infra/persistence/sql/migrations/` → filter `prefix_id > last` (or all if last is
  NULL) → for each: `.sql` → `BEGIN → run(sql) → INSERT tracker → COMMIT`; `.py` →
  import module, `inspect` one `Migration` subclass, instantiate with
  `(config, conn, log)`, `BEGIN → migrate() → check-txn → INSERT tracker → COMMIT`.
- Tests: `tests/integration/conftest.py` and `tests/e2e/conftest.py` `_init_schema`
  fixtures call `apply_schema`; they MUST also call `apply_migrations` after, so test
  DBs reach the latest version (fresh Postgres container = no `yascheduler_nodes` →
  seed fires → migrations skipped, but the call is still made for consistency).

## Open questions
All resolved (see Decisions). None outstanding.