## ADDED Requirements

### Requirement: PgPool manages connection lifecycle

The system SHALL provide a PgPool class that creates and manages a fixed-size
pool of pg8000 connections.

#### Scenario: Acquire and release
- **WHEN** a UoW acquires a connection via pool.acquire() and later releases it
- **THEN** the same connection can be reused by another UoW

#### Scenario: Pool exhaustion blocks
- **WHEN** all connections are acquired and a new acquire() is called
- **THEN** the caller awaits until a connection is released

### Requirement: UoW uses pool

The system SHALL update PostgresUnitOfWork to acquire a connection from
PgPool on enter and release it on exit.

#### Scenario: Pool with size 1 is backward compatible
- **WHEN** PgPool is created with size=1
- **THEN** behavior is identical to current ThreadPoolExecutor(max_workers=1)

### Requirement: Configurable pool size

The system SHALL support configuring the pool size via config.local.db_pool_size.

#### Scenario: Default pool size
- **WHEN** db_pool_size is not configured
- **THEN** pool size defaults to 1
