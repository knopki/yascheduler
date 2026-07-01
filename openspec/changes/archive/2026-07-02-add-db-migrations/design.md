## Context

yascheduler has no DB migration system. Schema evolution today means appending
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` lines to `schema.sql`, applied
idempotently by `apply_schema()` during `yainit --schema`. This is untracked
(no record of what was applied when), unordered, and gives no path for
non-idempotent DDL (rename, drop, data transformations) or operations that
cannot run inside a single transaction (`CREATE INDEX CONCURRENTLY`, `VACUUM`).
Three DB cohorts must coexist under one mechanism: fresh installs, legacy
production DBs (have `yascheduler_nodes` but lack columns added later, e.g.
`username`/`port`), and modern DBs that already track their state.

Key codebase anchors (frozen, unchanged unless noted):
- `apply_schema(config)` (`infra/persistence/postgres_schema.py:37`) opens a
  pg8000 native `Connection` from `PostgresDbConfig`, runs
  `load_query("schema")` inside `BEGIN/COMMIT`, rolls back on error, closes the
  connection. It is called by `yainit`'s `_init_schema` helper and by the
  integration/e2e `_init_schema` test fixtures.
- `schema.sql` (`infra/persistence/sql/schema.sql`) today has
  `CREATE TABLE IF NOT EXISTS yascheduler_nodes` (with `username`/`port`
  columns already in the CREATE) plus two trailing
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS username/port`.
- `PostgresDbConfig` (`infra/persistence/db_config.py:24`) is a frozen
  dataclass: `user`, `password`, `database`, `host`, `port` (all with
  defaults; `port >= 1` validated in `__post_init__`).
- `yainit` (`entrypoints/cli/init.py`) `init()` dispatches to
  `_init_schema(args.config)` → `apply_schema(config.db)`. `init()` runs schema
  when `not args.daemon or args.schema` (default and `--schema`).
- The persistence package facade `infra/persistence/__init__.py` re-exports
  `apply_schema`, `PostgresDbConfig`, `PostgresUnitOfWork`, and exceptions; a
  new `apply_migrations` export will be added here.
- AGENTS.md rule: "DB schema (`schema.sql` — schema changes MUST include
  migrations)". This change introduces the migration system that rule
  anticipates; until now it was aspirational.

## Design

### Model: snapshot + deltas

`schema.sql` is the full latest snapshot (all current columns in the
`CREATE TABLE` statements, no inline `ALTER`s). Migrations are the
evolution DDL/data that bring legacy and intermediate DBs up to the snapshot.
A fresh DB gets the snapshot directly and is seeded to the latest migration
id, so migrations are skipped; a legacy DB gets the snapshot as no-ops (via
`CREATE TABLE IF NOT EXISTS`) and then runs the migrations it missed; a modern
DB skips both the snapshot changes and already-applied migrations.

### Tracker table

```sql
CREATE TABLE yascheduler_migrations (
    migration_id TEXT PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Multi-row journal (one row per applied migration, with an audit timestamp).
`last_applied` is computed, not stored:
`SELECT MAX(migration_id) FROM yascheduler_migrations`. String sort matches
application order (the same sort used to order migration files). An empty
tracker returns `NULL` for `MAX`, which means "apply all pending".

### Bootstrap DO block in `schema.sql` (at the TOP, before any CREATE TABLE)

The bootstrap must run before `CREATE TABLE IF NOT EXISTS yascheduler_nodes`,
because the presence of `yascheduler_nodes` is the signal that distinguishes a
fresh DB (seed to latest) from a legacy DB (no seed, run all migrations). If
`CREATE TABLE IF NOT EXISTS` ran first, a fresh DB would always have
`yascheduler_nodes`, erasing the signal.

The guard is `to_regclass('yascheduler_migrations') IS NULL` (uses
`search_path`, no hardcoded schema name). The `last_migration` value is a
PL/pgSQL `CONSTANT` — the single manual edit point in `schema.sql` per added
migration. DDL inside PL/pgSQL requires `EXECUTE` (a static `CREATE TABLE` in
a DO block is not parsed).

```sql
DO $$
DECLARE
  last_migration CONSTANT TEXT := '<prefix_id_of_latest_migration>';
BEGIN
  IF to_regclass('yascheduler_migrations') IS NULL THEN
    EXECUTE 'CREATE TABLE yascheduler_migrations (
      migration_id TEXT PRIMARY KEY,
      created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )';
    IF to_regclass('yascheduler_nodes') IS NULL THEN
      INSERT INTO yascheduler_migrations (migration_id) VALUES (last_migration);
    END IF;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS yascheduler_nodes (
    ip VARCHAR(15) UNIQUE,
    port INTEGER DEFAULT 22,
    username VARCHAR(255) DEFAULT 'root',
    ncpus SMALLINT DEFAULT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    cloud VARCHAR(32) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS yascheduler_tasks (
    task_id SERIAL PRIMARY KEY,
    label VARCHAR(256),
    metadata JSONB,
    ip VARCHAR(15),
    status SMALLINT
);
```

The two `ALTER TABLE ... ADD COLUMN IF NOT EXISTS username/port` statements are
removed from `schema.sql` (they become the first migration).

Three cases:

| Case | `yascheduler_migrations` | `yascheduler_nodes` | DO block | After: migrations |
|---|---|---|---|---|
| Fresh DB | absent | absent | CREATE tracker + seed `last_migration` | skipped (MAX = last) |
| Legacy DB | absent | present | CREATE tracker, NO seed | run all (MAX = NULL) |
| Modern DB | present | present | skip entirely | run pending only (MAX = last applied) |

### Migration files

`infra/persistence/sql/migrations/{prefix_id}_{rest}.sql` or `.py`.

- `prefix_id` is the token before the first `_` in the filename. It is unique
  across all migration files (`.sql` and `.py` combined) and determines order
  by string sort.
- The spec does NOT fix a format for `prefix_id` (e.g. `001`, timestamp). It
  only requires: unique, token-before-first-`_`, string-sortable.
- Duplicate `prefix_id` detection is a unit test, NOT a runner responsibility.
  The runner applies; the test scans `migrations/` and asserts uniqueness.

### `Migration` base class

Lives in `infra/persistence/migration_base.py` (sibling of
`postgres_schema.py`, not under `sql/migrations/` — `migrations/` holds only
migration files, not the base class; this keeps the runner's discovery scan
trivial: every `.py` in `migrations/` is a migration module).

```python
# infra/persistence/migration_base.py
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pg8000.native import Connection
    from .db_config import PostgresDbConfig


class Migration:
    """Base class for .py database migrations.

    The runner instantiates a subclass with (config, conn, log) and calls
    migrate() inside an open transaction. Subclasses use self.config,
    self.conn, self.log directly. For migrations needing non-transactional
    operations (CREATE INDEX CONCURRENTLY, VACUUM), use self.commit() to close
    the runner's transaction, run the command, then self.begin() to reopen one.
    Migrations are NOT required to be idempotent.
    """

    def __init__(
        self,
        config: "PostgresDbConfig",
        conn: "Connection",
        log: logging.Logger,
    ) -> None:
        self.config = config
        self.conn = conn
        self.log = log

    def begin(self) -> None:
        self.conn.run("BEGIN")

    def commit(self) -> None:
        self.conn.run("COMMIT")

    def migrate(self) -> None:
        raise NotImplementedError
```

### `Migration` class discovery (`.py` migrations)

The runner imports the `.py` migration module, then uses `inspect` to find
exactly one subclass of `Migration` (excluding `Migration` itself). On 0 or
>1 subclasses, it raises a clear error naming the file. No module-level marker
variable, no fixed class name — the convention is "exactly one subclass per
file".

### `apply_migrations` runner algorithm

`infra/persistence/postgres_migrations.py`:

```
apply_migrations(config: PostgresDbConfig) -> None:
    conn = Connection(user=..., host=..., database=..., port=..., password=...)
    log = logging.getLogger("yascheduler.infra.persistence.postgres_migrations")
    try:
        # last applied; NULL if tracker empty (covers legacy DB after bootstrap)
        last = conn.run("SELECT MAX(migration_id) FROM yascheduler_migrations")
        last = last[0][0] if last and last[0] else None   # None -> run all

        files = sorted(glob(migrations/*), key=lambda f: f.name)  # string sort by filename
        # NB: sort by full filename; prefix_id uniqueness (unit-tested) guarantees
        #     the sort is stable w.r.t. prefix_id order.
        pending = [f for f in files if prefix_id(f) > last] if last is not None
                   else files                                  # NULL -> all

        for f in pending:
            pid = prefix_id(f)
            if f.suffix == ".sql":
                conn.run("BEGIN")
                try:
                    conn.run(f.read_text())                    # multi-statement OK (Simple Query)
                    conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)", p=pid)
                    conn.run("COMMIT")
                except Exception:
                    _rollback(conn); raise
            else:  # ".py"
                conn.run("BEGIN")
                try:
                    # load by file path: migration filenames often start with a digit
                    # (e.g. "001_..."), which is NOT a valid Python module name, so
                    # importlib.import_module would raise ModuleNotFoundError.
                    spec = importlib.util.spec_from_file_location(pid, f)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    klass = _one_migration_subclass(module)    # inspect, fail on 0 or >1
                    migration = klass(config, conn, log)
                    migration.migrate()
                    # try to record tracker in the SAME transaction as migrate() (atomic
                    # normal case); if migrate() closed the txn (via self.commit() for a
                    # non-transactional op), the INSERT raises "no transaction in progress"
                    # → reopen a fresh transaction for the tracker record.
                    try:
                        conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)", p=pid)
                        conn.run("COMMIT")
                    except <no-transaction-in-progress-error>:
                        conn.run("BEGIN")
                        conn.run("INSERT INTO yascheduler_migrations (migration_id) VALUES (:p)", p=pid)
                        conn.run("COMMIT")
                except Exception:
                    _rollback(conn); raise
    finally:
        conn.close()
```

The tracker-recording block uses a try/except around the INSERT rather than a
separate probe function. In the normal case (migrate() did NOT close the
transaction), the INSERT and the runner's COMMIT run in the SAME transaction
as migrate()'s work — fully atomic: migrate() applied ⇔ tracker recorded.
If migrate() closed the transaction (called `self.commit()` for a
non-transactional op and forgot to `self.begin()`), the INSERT raises
"no transaction in progress"; the runner catches that, opens a fresh `BEGIN`,
retries the INSERT, and `COMMIT`s. The migration's data is already committed
(by the migration's own `self.commit()`), so the tracker record goes into a
new transaction — best-effort reopen. The contract is: migrate() either
returns with an open transaction (normal) or with no transaction (after
`self.commit()`); both cases record the tracker. A migration that leaves the
connection in a half-open state (e.g. called `self.begin()` then errored) is
caught by the outer `except Exception → ROLLBACK`.

`_rollback(conn)` wraps `conn.run("ROLLBACK")` in `try/except` (best-effort;
the connection may be in a bad state).

Multi-statement `.sql` works via pg8000 native Simple Query (libpq
`PQexec`), which executes a `;`-separated string in one `conn.run` call. No
special handling needed.

### First migration

`infra/persistence/sql/migrations/<prefix_id>_add_username_port.sql`:
```sql
ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS username VARCHAR(255) DEFAULT 'root';
ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS port INTEGER DEFAULT 22;
```
These two statements are idempotent (`IF NOT EXISTS`) because they were
originally written as inline `ALTER`s in `schema.sql` and must not fail on a
DB that somehow already has one column but not the other; idempotency here is
a property of these specific statements, NOT a general requirement on
migrations. The `last_migration` CONSTANT in the DO block is set to this
migration's `prefix_id`.

### `yainit` wiring

`entrypoints/cli/init.py` `_init_schema(config_path)` calls `apply_schema(config.db)`
then `apply_migrations(config.db)`. Both are imported from
`yascheduler.infra` (the persistence facade re-exports `apply_migrations`).
This runs in the default invocation and `--schema` (whenever `run_schema` is
true). `--daemon` is unaffected. The exit-code contract (0/1/2) is unchanged;
`apply_migrations` raising `DatabaseError` is caught by the existing
`except DatabaseError` block in `_init_schema` and exits 1.

### Test fixtures

`tests/integration/conftest.py` and `tests/e2e/conftest.py` `_init_schema`
fixtures currently call only `apply_schema(_db_config)`. They are updated to
also call `apply_migrations(_db_config)` after. On a fresh testcontainer
Postgres, `apply_schema` runs the DO block: no `yascheduler_nodes` → tracker
created + seeded to `last_migration` → `apply_migrations` finds nothing
pending. The call is still made for consistency and to exercise the runner on
every test run.

### Three edit points when adding a migration `<prefix_id>_...`

1. Create the migration file under `migrations/`.
2. Update the `last_migration` CONSTANT in the `schema.sql` DO block to the
   new `prefix_id`.
3. If the migration changes the schema, update the snapshot DDL in
   `schema.sql` (e.g. add the new column to the `CREATE TABLE`).

Forgetting step 2 means a fresh DB gets the snapshot at the new version but
the tracker says the previous version → the new migration is re-applied on
next `yainit`; if the migration is idempotent this is harmless, if not it
fails loudly. Forgetting step 3 means a fresh DB is missing the change. These
are documented in the spec as mandatory steps; a unit test cannot enforce
step 2 (it requires a running DB to detect the drift), so it remains a
documented procedure.

### Non-goals

- No migration *rollback* / "down" migrations. The system is forward-only.
- No migration *generation* tool. Migrations are hand-written.
- No `schema.sql` *generation* from migrations. The snapshot is hand-maintained.
- No parallel-migration conflict resolution beyond the unit-tested `prefix_id`
  uniqueness.
- No runner-side duplicate-`prefix_id` check (that is a unit test's job).
- No requirement that migrations be idempotent (non-transactional ops make it
  impossible; the tracker guards against re-application instead).

## Trade-offs

- **Snapshot + deltas vs pure migrations**: snapshot keeps fresh installs fast
  (no history replay) and gives a readable single-file view of the current
  schema; the cost is the three manual edit points and the DO-block
  complexity. Pure migrations (Django-style) avoid the snapshot drift problem
  but replay the full history on every fresh install — slower and more
  fragile as history grows. The project has few migrations and a small
  schema, so the snapshot's readability wins.
- **Multi-row tracker vs single-row**: the journal gives an audit trail
  (`created_at`) at trivial extra cost; a single-row `last_applied` gives no
  history. The journal is chosen.
- **Best-effort reopen vs strict contract**: best-effort reopen (try the
  tracker INSERT in the same txn; on "no transaction in progress", open a new
  txn for the tracker) tolerates a `.py` migration that closed its txn and
  forgot to reopen, while keeping the normal case fully atomic (migrate() and
  tracker record in one COMMIT). A strict contract would fail loudly on the
  same mistake but would leave the migration applied and the tracker unrecorded
  (re-applied next run, likely failing). Best-effort keeps the system robust;
  the `self.begin()`/`self.commit()` helpers are documented for the intended
  non-transactional pattern.
- **`inspect` discovery vs explicit marker**: `inspect` avoids per-file
  ceremony (no `MIGRATION = ...` line) at the cost of a small amount of
  magic; the "exactly one subclass" guard makes failures explicit.

## Risks

- **Forgetting step 2 (update `last_migration` CONSTANT)** on a fresh install
  leads to re-application of the latest migration. Mitigated by: idempotent
  migrations being harmless; non-idempotent ones failing loudly; documented
  procedure. A unit test could assert the CONSTANT matches the latest file's
  `prefix_id` by scanning `schema.sql` — feasible and worth adding.
- **Legacy DB detection via `yascheduler_nodes`** assumes the only way a DB
  has `yascheduler_nodes` is via a prior `apply_schema`. A manually-created
  `yascheduler_nodes` (without `yascheduler_migrations`) would be treated as
  legacy and have all migrations run — which is the correct behavior (it
  needs them).
- **`.py` migrations importing application code** could create circular
  imports (migrations under `infra/persistence/` importing
  `infra/persistence/` modules). Mitigated by: the `Migration` base class
  living in `migration_base.py` (not in `migrations/`); migration files
  import only the base class, not the runner.
- **DO block portability**: `to_regclass` and PL/pgSQL `DO` are standard
  PostgreSQL (9.1+ for `DO`, 9.3+ for `to_regclass`). yascheduler targets
  modern Postgres; no portability concern.