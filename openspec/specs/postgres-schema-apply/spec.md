## Purpose

Define the behavior of applying the PostgreSQL schema (`schema.sql`)
transactionally and bootstrapping the migrations tracker. The migration
framework is specified in `db-migrations`.

## Requirements

### Requirement: Schema application is transactional and idempotent

The system SHALL apply `schema.sql` inside a single transaction using
idempotent DDL: every object creation SHALL guard against the object
already existing. A guarded bootstrap SHALL seed the migrations
tracker. On failure the transaction SHALL roll back and the error
SHALL propagate.

#### Scenario: re-run on an already-initialized database

- **WHEN** the schema is applied to a database that already has it
- **THEN** existing tables are not recreated, the tracker is not re-seeded, and the call completes without error

#### Scenario: failure rolls back and propagates

- **WHEN** schema application fails mid-way
- **THEN** the transaction is rolled back and the original error is raised

### Requirement: Migrations-tracker bootstrap

`schema.sql` SHALL bootstrap the `yascheduler_migrations` tracker with
one branching rule: fresh databases get a tracker seeded to the latest
migration; legacy databases (pre-tracker) get an empty tracker; modern
databases are left untouched. The seeded value is a single edit point
in `schema.sql`, updated when a new migration is added.

#### Scenario: a fresh database starts at the latest migration

- **WHEN** the schema is applied to an empty database
- **THEN** the tracker is created and seeded to the latest migration, so subsequent migrations find nothing to apply

### Requirement: schema.sql is the full latest snapshot

`schema.sql` SHALL be the full latest snapshot of the schema: every
table definition SHALL include all current columns. Schema evolution
SHALL be expressed via migration files (see `db-migrations`).

#### Scenario: a fresh apply carries every current column

- **WHEN** the schema is applied to a fresh database and the current migration set is inspected
- **THEN** each table in the snapshot carries every column introduced by the migration set; no column is added out of band

### Requirement: Schema enforces the domain entity contract

The schema SHALL enforce the domain entity contract through table-level
`CHECK` constraints and column nullabilities. Per-status field
invariants and column nullabilities match the domain entity
definitions.

#### Scenario: a row that violates the contract is rejected

- **WHEN** a row is written that violates the per-status field contract or a column nullability rule
- **THEN** the write is rejected by the schema
