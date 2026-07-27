# ADR-0015: Node.ncpus is operator-set config, not a discovery cache

- **Status:** Accepted
- **Date:** 2026-07-13
- **Supersedes:**
- **Superseded by:**

## Context

`Node.ncpus` had two conflicting interpretations. One add-path treated
it as a cache for runtime discovery (writing the discovered value back
to the row); the other never persisted discovery at all. A magic `0`
sentinel meant "unknown / discover at spawn", and the orchestrator
papered over the ambiguity with a falsy short-circuit. The discovery
call itself was uncached, so a static session deploying N tasks
performed N redundant remote CPU-count round-trips.

## Decision

1. **`Node.ncpus` is operator-set static configuration** (`int | None`),
  not a cache for runtime discovery. `None` means "no operator limit,
  discover at spawn"; `N > 0` means "explicit value, use directly".
  The magic `0` sentinel is eliminated from every layer; the cloud
  write-back of discovered values is removed.

2. **Discovery is memoized per session lifetime.** When `ncpus` is
  `None`, the SSH session discovers the CPU count on first need and
  reuses the result for the rest of the connection — at most one
  remote exec per session, instead of one per spawn.

3. **A CHECK constraint enforces the invariant** in the persistence
  layer: `ncpus IS NULL OR ncpus > 0`. Existing `0` rows are migrated
  to `NULL`.

## Alternatives Considered

### Keep the `0` sentinel and document it

Rejected — the sentinel already leaked into CLI display, orchestrator
logic, and test fixtures. A nullable type makes the "unset" state
honest and removes the implicit `0`-is-special coupling between every
reader and writer.

### Treat it as a discovery cache (write back the discovered value)

Rejected — that is the asymmetric state being removed. One semantics
for every add path is the point of the decision.

### No session cache — accept one remote exec per spawn

Rejected — that is the current behaviour being fixed. Memoising per
session makes discovery cheap without introducing a new dependency.

## Consequences

- **Positive:** `Node.ncpus` has a single, honest semantic across all
  add paths. The schema enforces it; readers no longer special-case
  `0`.
- **Positive:** Discovery costs at most one remote exec per session
  lifetime, instead of one per spawn.
- **Negative / trade-offs:** A cloud node whose stored `ncpus` is `> 0`
  is used directly, without re-discovery. If the provider changes the
  instance shape under the same identity, the stored value goes stale.
  Accepted — cloud nodes are identified by `external_id` and deleted
  on idle; long-lived shape changes under a reused identity are not a
  supported operational pattern.
- **Accepted risks:** Hot-add CPU on a live bare-metal session goes
  unobserved (CPU count is cached for the session's lifetime). An
  operator who hot-adds must set `ncpus` explicitly to affect
  scheduling. Hot-add during a live scheduler session is outside the
  operational model.
