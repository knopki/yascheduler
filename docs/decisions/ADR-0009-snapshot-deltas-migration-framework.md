# ADR-0009: Snapshot + deltas migration framework

- **Status:** Accepted
- **Date:** 2026-07-02
- **Supersedes:**
- **Superseded by:**

## Context

The project had no DB migration system. Schema evolution was done by appending
`ALTER TABLE … ADD COLUMN IF NOT EXISTS` lines to the schema file, applied
idempotently at bootstrap. This left no record of what was applied when, gave no
ordering guarantee, and could not express non-idempotent operations (rename,
drop, data transformations) or operations that cannot run inside a single
transaction (`CREATE INDEX CONCURRENTLY`, `VACUUM`).

Three database cohorts must coexist: fresh installs, legacy production
databases (created before migrations existed), and modern databases that
already track their migration state.

## Decision

Adopt a **snapshot + deltas** migration model.

1. **Snapshot.** A single schema file represents the latest schema in
  full — `CREATE TABLE` statements, no inline `ALTER`s. Fresh installs
  apply the snapshot directly; no history replay.

2. **Deltas.** Each schema change lives in its own migration file with
  a sortable prefix. Migrations run forward-only, in order, on
  databases whose state is behind the snapshot. Two formats are
  supported: pure SQL, and Python (for data transformations or
  operations SQL cannot express).

3. **Multi-row tracker.** An append-only journal records each applied
  migration with a timestamp, giving an audit trail. The current
  state is the maximum applied ID.

4. **Three-case bootstrap.** On startup, the schema file detects which
  cohort a database belongs to (fresh, legacy, modern) and applies
  the right path: seed the tracker to the latest migration and create
  the snapshot; create the tracker and replay all deltas; or skip
  entirely.

## Alternatives Considered

### Pure forward-only migrations (Django-style)

No snapshot; every fresh install replays the full migration history.
Rejected — slower and more fragile as history grows. The schema is
small and the migration count is low; the snapshot's readability and
fresh-install speed win.

### Single-row version tracker (Alembic-style)

One row storing the current version token. Rejected — no audit trail
of what was applied when. A multi-row journal costs nothing extra and
gives a full history.

### Strict contract for Python migrations

Fail loudly if a Python migration closes its transaction without
reopening. Rejected — would leave the migration applied but the tracker
unrecorded, causing a wrong-state re-application next run. Best-effort
reconnect keeps the system robust.

## Consequences

- **Positive:** Fresh installs are fast (single snapshot apply, no
  history replay) and have a single-file view of the current schema.
- **Positive:** Audit trail of applied migrations with timestamps.
- **Positive:** Forward-only path for non-idempotent DDL and for
  operations that cannot run in a single transaction.
- **Positive:** All three database cohorts bootstrap without manual
  intervention.
- **Negative / trade-offs:** Three manual touch-points per migration
  (new file, snapshot version constant, snapshot DDL if the schema
  shape changes). The snapshot can drift from the migration history
  if a touch-point is missed; a unit test guards the constant.
- **Accepted risks:** Forgetting the snapshot DDL update leaves fresh
  installs missing the change. Caught by the same constant-matches
  test; non-idempotent migrations fail loudly on re-application.
