## ADDED Requirements

### Requirement: Transactional schema application

The system SHALL provide a synchronous function `apply_schema(config: ConfigDb)`
that reads `schema.sql` via `load_query("schema")` and executes it within a
`BEGIN/COMMIT` transaction using pg8000. On failure, the function SHALL execute
`ROLLBACK` and re-raise the exception.

#### Scenario: Schema applies cleanly on empty database
- **WHEN** `apply_schema(config)` is called with a valid `ConfigDb` pointing to an empty PostgreSQL database
- **THEN** all tables from `schema.sql` are created and the function returns without error

#### Scenario: Partial failure is rolled back
- **WHEN** `apply_schema(config)` is called and SQL execution fails mid-way
- **THEN** no tables are created (transaction is rolled back) and the exception is re-raised

### Requirement: Error reporting on existing schema

The system SHALL catch `DatabaseError` when tables already exist, print
"Database already initialized!", and re-raise the exception.

#### Scenario: Database already initialized
- **WHEN** `apply_schema(config)` is called on a database where tables already exist
- **THEN** "Database already initialized!" is printed and `DatabaseError` is raised

### Requirement: Connection lifecycle

The function SHALL open a pg8000 native connection from `ConfigDb`, execute the
schema transaction, and close the connection. No connection pooling or async is
involved.

#### Scenario: Connection is closed after success
- **WHEN** `apply_schema(config)` completes successfully
- **THEN** the pg8000 connection is closed

#### Scenario: Connection is closed after failure
- **WHEN** `apply_schema(config)` raises an exception
- **THEN** the pg8000 connection is closed
