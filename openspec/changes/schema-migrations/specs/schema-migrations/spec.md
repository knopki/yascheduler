## ADDED Requirements

### Requirement: Versioned migration files

The system SHALL store migrations as numbered SQL files in
`adapters/persistence/sql/migrations/` with the format `NNN_description.sql`.

#### Scenario: Migration file naming
- **WHEN** a new migration is needed
- **THEN** it is created as `sql/migrations/002_add_error_column.sql` (next sequential number)

#### Scenario: Migration executed in order
- **WHEN** `migrate()` is called
- **THEN** unapplied migrations are executed in numeric order (001 before 002, etc.)

### Requirement: yascheduler_migrations tracking table

The system SHALL maintain a `yascheduler_migrations` table with columns `version INTEGER

#### Scenario: Table created on first migration
- **WHEN** `migrate()` is called for the first time
- **THEN** the `yascheduler_migrations` table is created if it does not exist

#### Scenario: Applied migration recorded
- **WHEN** migration 001 is successfully applied
- **THEN** a row `(version=1, applied_at=<now>)` is inserted

### Requirement: Idempotent migration application

The system SHALL skip migrations whose version number is already present in
the `yascheduler_migrations` table.

#### Scenario: Re-running already applied migration
- **WHEN** `migrate()` is called and all migrations are already applied
- **THEN** no SQL is executed (idempotent)

#### Scenario: Apply only new migrations
- **WHEN** `migrate()` is called with versions 1,2 applied and version 3 exists
- **THEN** only version 3 is executed

### Requirement: Existing DDL moved to migrations

The system SHALL move the current `db.migrate()` ALTER TABLE statements into
`migrations/001_add_username_port.sql`.

#### Scenario: First migration file exists
- **WHEN** a fresh install runs `migrate()`
- **THEN** `001_add_username_port.sql` is applied, adding `username` and `port` columns

### Requirement: DB.migrate() delegates to migration runner

The system SHALL refactor `DB.migrate()` to call the new migration runner
instead of executing hardcoded SQL directly.

#### Scenario: old migrate() call still works
- **WHEN** existing code calls `await db.migrate()`
- **THEN** migrations are applied via the versioned system, with identical result

### Requirement: Migration runner importable

The system SHALL provide a migration runner function importable from
`yascheduler.adapters.persistence`.

#### Scenario: Run migrations from code
- **WHEN** `from yascheduler.adapters.persistence import run_migrations` and
  `await run_migrations(connection)` is called
- **THEN** all unapplied migrations execute against the given connection
