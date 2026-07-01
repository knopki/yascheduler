## Why

yascheduler has no database migration system. Schema evolution today is done by
appending `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` lines to `schema.sql`, applied
idempotently by `apply_schema()` during `yainit --schema`. This has three problems:

1. **Untracked** — there is no record of which schema changes were applied to a given
   database, when, or in what order. Operators cannot tell what state a legacy DB is in.
2. **Unordered** — there is no sequencing of schema changes; ordering relies on the
   developer remembering to append in order, with no enforcement.
3. **No path for non-idempotent or non-transactional operations** — column renames,
   drops, and data transformations cannot be expressed as `ADD COLUMN IF NOT EXISTS`;
   `CREATE INDEX CONCURRENTLY` and `VACUUM` cannot run inside the single
   `BEGIN/COMMIT` that `apply_schema` uses.

Legacy production databases exist (they have `yascheduler_nodes` but lack columns added
later, e.g. `username` and `port`), and they coexist with fresh installs and modern
databases. The current `ALTER ... IF NOT EXISTS` inline approach only works for additive
column changes and silently does nothing for everything else.

## What Changes

- **Add a migration runner** (`infra/persistence/postgres_migrations.py`) that:
  - Scans `infra/persistence/sql/migrations/` for `*.sql` and `*.py` files named
    `{prefix_id}_{rest}.{sql,py}`, where `prefix_id` is the token before the first `_`
    and is unique across all migration files (enforced by a unit test, not by the runner).
  - Reads the last applied migration from
    `SELECT MAX(migration_id) FROM yascheduler_migrations` (`NULL` → apply all).
  - Applies pending migrations in string-sorted `prefix_id` order, each in its own
    transaction, recording each in `yascheduler_migrations` after success.
  - `.sql` migrations: `BEGIN → conn.run(sql_text) → INSERT tracker → COMMIT`;
    multi-statement SQL works via pg8000 native Simple Query.
  - `.py` migrations: imports the module, discovers exactly one subclass of `Migration`
    via `inspect` (fails on 0 or >1), instantiates it with
    `(config, conn, log)`, runs `BEGIN → migration.migrate() → check-txn-open →
    INSERT tracker → COMMIT`. If `migrate()` closed the transaction, the runner reopens
    a `BEGIN` before the tracker INSERT (best-effort reopen).
  - On any error: `ROLLBACK` (best-effort), re-raise; do not record the tracker for the
    failed migration.
- **Add a `Migration` base class** (`infra/persistence/sql/migrations/__init__.py` or a
  dedicated module in `infra/persistence/`) with
  `__init__(self, config: PostgresDbConfig, conn: pg8000.native.Connection, log: logging.Logger)`,
  instance attributes for all three, `migrate(self) -> None` (raises
  `NotImplementedError`), and `begin()`/`commit()` helpers that delegate to
  `conn.run("BEGIN"/"COMMIT")` for migrations needing non-transactional operations
  (`CREATE INDEX CONCURRENTLY`, `VACUUM`): the pattern is `self.commit()` → run the
  command → `self.begin()`.
- **Update `schema.sql`**:
  - Add a DO block at the TOP (before any `CREATE TABLE`) that bootstraps the
    `yascheduler_migrations` tracker using three-case logic:
    `IF to_regclass('yascheduler_migrations') IS NULL THEN CREATE TABLE ... ; IF
    to_regclass('yascheduler_nodes') IS NULL THEN INSERT seed (last_migration) END IF;
    END IF;`. The `last_migration` value is a PL/pgSQL CONSTANT (single edit point).
  - Remove the two `ALTER TABLE ... ADD COLUMN IF NOT EXISTS username/port` statements
    (they become the first migration).
  - Keep `CREATE TABLE IF NOT EXISTS yascheduler_nodes` with the `username` and `port`
    columns included (latest snapshot).
- **Add the first migration** `migrations/<prefix_id>_add_username_port.sql`:
  ```sql
  ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS username VARCHAR(255) DEFAULT 'root';
  ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS port INTEGER DEFAULT 22;
  ```
  This runs on legacy DBs (no tracker, no columns); fresh DBs skip it (seeded to
  `last_migration`); modern DBs already have it recorded.
- **Wire `yainit`** to call `apply_migrations(config.db)` after `apply_schema(config.db)`
  in both the default invocation and `--schema`. The `_init_schema` helper in
  `entrypoints/cli/init.py` gains a follow-up `apply_migrations` call.
- **Update test fixtures** (`tests/integration/conftest.py`, `tests/e2e/conftest.py`)
  `_init_schema` to also call `apply_migrations` after `apply_schema`, so test Postgres
  containers reach the latest version.
- **Add a unit test** that scans `migrations/` and asserts `prefix_id` uniqueness across
  all `.sql` and `.py` files (the runner does NOT perform this check).
- **Update OpenSpec specs**:
  - New spec `db-migrations` (runner contract, file format, tracker schema, bootstrap
    DO block, `.py` class discovery, transaction contract).
  - Modified `postgres-schema-apply` (add the DO block / three-case bootstrap; remove
    the inline ALTER requirement; `schema.sql` is the latest snapshot).
  - Modified `cli-commands` (`yainit` calls `apply_migrations` after `apply_schema`).

No **BREAKING** changes to public APIs. The DB schema gains the
`yascheduler_migrations` table (additive). The INI config format is unchanged. CLI
flags are unchanged. The `Yascheduler` public API is unchanged.

## Capabilities

### New Capabilities
- `db-migrations` — the migration runner, file format, tracker table, bootstrap
  semantics, and the `Migration` base class contract.

### Modified Capabilities
- `postgres-schema-apply` — `schema.sql` gains the bootstrap DO block at the top;
  inline `ALTER ... IF NOT EXISTS` statements are removed (they become migrations);
  `schema.sql` remains the full latest snapshot.
- `cli-commands` — `yainit` (default and `--schema`) calls `apply_migrations` after
  `apply_schema`; the `_init_schema` helper is updated.
