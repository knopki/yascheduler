## Context

Phase 2.5 of the architecture migration. Occurs after `persistence-adapter`
(Phase 2) introduces `adapters/persistence/sql/`. The current migration is
a single method with hardcoded DDL. This design introduces versioned,
tracked migrations.

## Goals / Non-Goals

**Goals:**
- Versioned migration files (`migrations/001_*.sql`, `002_*.sql`, …).
- A `yascheduler_migrations` table tracking applied versions.
- Sequential application — migrations run in order, skipped if already applied.
- Replace `db.migrate()` with the new system.
- Move existing DDL to versioned files.

**Non-Goals:**
- No rollback support (migrations are forward-only).
- No migration framework dependency (e.g., Alembic) — keep it simple.
- No schema changes in this proposal — just the mechanism.

## Decisions

### D1: Forward-only, versioned SQL files

```
adapters/persistence/sql/migrations/
├── 001_add_username_port.sql    # existing ALTER TABLE from db.migrate()
├── 002_<next_change>.sql
└── ...
```

Files are numbered sequentially. Each file contains one or more SQL
statements. Migrations are forward-only — no down/rollback files. This
is acceptable for a single-service database with infrequent schema changes.

### D2: yascheduler_migrations tracking table

```sql
CREATE TABLE IF NOT EXISTS yascheduler_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Created on first `migrate()` call. Each applied migration inserts a row.
The migration runner queries `SELECT MAX(version) FROM yascheduler_migrations` and
applies all files with higher version numbers.

### D3: Idempotent migration runner

The migration runner:
1. Creates `yascheduler_migrations` table if not exists
2. Reads `MAX(version)` applied
3. Lists migration files by numeric prefix, sorted
4. For each file with version > applied: execute SQL, insert tracking row

This is idempotent — running the same set of migrations twice is a no-op.

### D4: Replace db.migrate()

The current `db.migrate()` is replaced with a call to the new runner.
The runner lives in `adapters/persistence/` (close to SQL files) and is
called from `DB.migrate()`. The `DB` method signature is unchanged.

### D5: schema.sql is the ground truth for fresh installs

`schema.sql` is the full DDL for creating all tables from scratch.
Migrations only contain incremental changes. This dual approach is simple:
- Fresh install → `schema.sql`
- Upgrade → migrations from `MAX(version)` forward

## Risks / Trade-offs

- **No down migrations**: A bad migration must be fixed with a new forward
  migration. Acceptable for a small project with infrequent schema changes.
- **Manual file ordering**: Version numbers must be sequential. A missing
  number means a gap that stops migration. Mitigation: test validates
  sequential numbering.
- **Concurrent migration**: If two instances run `migrate()` simultaneously,
  both may try to insert the same version row. Mitigation: wrap each migration
  file in a transaction; the `INSERT INTO yascheduler_migrations` with the version number
  as PK will fail on duplicate (caught and ignored).
