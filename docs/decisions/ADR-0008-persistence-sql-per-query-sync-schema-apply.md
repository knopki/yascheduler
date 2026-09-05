# ADR-0008: Persistence adapter — SQL file-per-query and transactional schema apply

- **Status:** Accepted
- **Date:** 2026-06-03
- **Supersedes:**
- **Superseded by:**

## Context

The original database wrapper mixed connection management, query text,
schema creation, and business-level CRUD in one component. SQL lived
inside Python methods, the schema was applied in autocommit mode with no
rollback on partial failure, and the bootstrap entry point was wrapped
in an async shim to stay uniform with the rest of the adapter.

The forces at play:

- **SQL reviewability.** Embedded SQL is invisible to DBA tooling and
  to focused review. Queries that are reused across the bootstrap path
  and test fixtures get duplicated.
- **DDL atomicity.** PostgreSQL supports transactional DDL. Autocommit
  schema application can leave a database half-initialised on failure,
  with no rollback.
- **Bootstrap complexity.** Schema application is a one-shot operation.
  The async/executor machinery around it added complexity without a
  concurrency benefit.

## Decision

1. **One SQL file per query.** SQL lives in version-controlled files,
  loaded through a single cached loader. The cache ensures at most one
  disk read per distinct query per process lifetime.

2. **Schema application is a plain synchronous function.** No async,
  no thread-pool executor. The bootstrap entry point (`yainit`) is a
  regular CLI command.

3. **Schema application is transactional.** DDL runs inside
  `BEGIN/COMMIT`. On failure, `ROLLBACK` is issued and the error
  re-raised. Partial-schema results are impossible.

## Alternatives Considered

### Inline SQL strings in Python

Rejected — hides SQL from review and DBA tooling; duplicates query text
across consumers.

### Async schema application via `run_in_executor`

Rejected — schema apply is one-shot with no concurrency requirement;
the async shim adds complexity without a benefit.

### Autocommit DDL (per-statement transactions)

Rejected — leaves the database in a partial state on failure.
Transactional DDL is the core atomicity guarantee.

## Consequences

- **Positive:** SQL is reviewable and lintable in isolation, and
  reusable across the bootstrap path and test fixtures via a single
  loader.
- **Positive:** Bootstrap is a simple synchronous CLI command; no async
  imports, no executor lifecycle.
- **Positive:** Schema application is atomic — a fresh database either
  has the full schema or none of it.
- **Negative / trade-offs:** Schema application is not idempotent;
  running it on an existing database raises an error. By design — the
  target is fresh databases; incremental changes go through the
  migration framework (ADR-0009).
- **Accepted risks:** The SQL loader resolves files by a path relative
  to its module. A package layout change would break it; covered by
  integration tests.
