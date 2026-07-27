# ADR-0014: Internal retry utility replacing backoff dependency

- **Status:** Accepted
- **Date:** 2026-07-25
- **Supersedes:**
- **Superseded by:**

## Context

The `backoff` library (v2.1.2) has been unmaintained since 2022 and produces
deprecation warnings on Python 3.12+ (`asyncio.iscoroutinefunction`), suppressed
via a warning filter in `pyproject.toml`. The codebase uses only a tiny subset
of the library — `@backoff.on_exception` with `backoff.fibo` and `max_time=60` —
no jitter, callbacks, `on_predicate`, or `max_tries`. Maintaining a suppression
filter for a dead library is not sustainable, and a community fork
(`python-backoff`) creates ecosystem fragmentation risk. Alternatives were: (a)
keep backoff with warning suppression, (b) migrate to a maintained fork, (c)
write an internal utility covering exactly the patterns used.

## Decision

Replace the `backoff` library with an internal async retry utility that covers
decorator, partial, and direct-call forms with exponential backoff, time-based
deadline, exception filtering, and optional `giveup` callback. Remove
`backoff~=2.1.2` from `pyproject.toml` dependencies and its `DeprecationWarning`
suppression filter.

### Backoff strategy

Exponential backoff replaces the prior Fibonacci schedule: `initial_delay=1.0`,
`factor=1.5`, `max_delay=30.0` — producing \~6-8 attempts within 60s, comparable
to Fibonacci. The first retry delay changes from 0s (Fibonacci) to 1.0s
(exponential).

## Alternatives Considered

### Keep backoff with warning suppression

Trivial effort, but accumulates technical debt on an abandoned dependency. Also
requires users of newer Python to tolerate a suppressed warning from a dead
library.

### Migrate to `python-backoff` community fork

Replaces one third-party dependency with another that has no clear long-term
maintenance guarantee. Same API surface, same bloat for the tiny subset used.

## Consequences

- **Positive:** Removes a deprecated, unmaintained dependency. Eliminates
  `DeprecationWarning` suppression filter. \~30 LOC of self-contained, auditable
  utility code replaces a full library. Single point of control for retry
  semantics across the project.
- **Negative / trade-offs:** Internal utility must be maintained in-house.
  Exponential backoff produces a slightly different retry timing profile than
  Fibonacci (first retry at 1.0s instead of immediate) — does not affect
  correctness for any current use case.
- **Accepted risks:** The utility is async-only — no sync retry path. If a sync
  retry need arises, a sync variant would need to be added. Minimal risk given
  the small surface (\~30 LOC).
