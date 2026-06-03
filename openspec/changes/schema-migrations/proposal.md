## Why

The current `db.migrate()` runs hardcoded `ALTER TABLE ADD COLUMN IF NOT EXISTS`
statements — no versioning, no tracking of which migrations have been applied.
As the architecture migration progresses (new domain model, new features),
schema changes will be needed. Managed migrations allow evolving the schema
without waiting for the full architecture migration to complete (Phase 5).

## What Changes

- Add a lightweight migration system: versioned SQL files in
  `adapters/persistence/sql/migrations/`, a `yascheduler_migrations` tracking table,
  and sequential application of unapplied migrations.
- Replace the current ad-hoc `db.migrate()` with the new system.
- Move the existing `ALTER TABLE` statements to `migrations/001_add_username_port.sql`.
- The initial schema DDL (`schema.sql`) remains the ground truth for fresh
  installations.

## Capabilities

### New Capabilities
- `schema-migrations`: Versioned, sequential SQL migrations with tracking
  table and idempotent application.

### Modified Capabilities
<!-- No existing specs affected. -->

## Impact

- New directory: `adapters/persistence/sql/migrations/`
- Modified file: `yascheduler/db.py` — `migrate()` replaced with new system
- New SQL table: `yascheduler_migrations` (version: int, applied_at: timestamp)
- No breaking changes — all existing callers of `db.migrate()` continue to work
