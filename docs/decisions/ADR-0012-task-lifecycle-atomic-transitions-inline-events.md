# ADR-0012: Task lifecycle expressed as atomic transitions

- **Status:** Accepted
- **Date:** 2026-07-09
- **Supersedes:**
- **Superseded by:**

## Context

A task moves through a fixed set of state transitions: submission, start,
rejection, completion, failure, abandonment. Each transition changes
several fields at once (status, timestamps, folder paths, error text)
and produces a domain event recording what happened.

Two forces shaped the decision:

- **Intermediate states.** If a transition is decomposed into smaller
  mutating steps, the entity passes through states that are technically
  valid but semantically empty (e.g. allocated but not yet running).
  Every observer then has to reason about states that no transition
  intended to produce.
- **Event/transition decoupling.** If the caller is responsible for
  constructing the matching event after a transition, callers must know
  the mapping and must keep payloads in sync with the transition
  arguments. That is a recurring source of bugs.

## Decision

1. **The Task entity exposes a fixed set of atomic transition methods**
  — one per lifecycle move. Each method validates the source state,
  sets every field that changes, constructs and appends the matching
  domain event inline, and returns a new `Task`. No partial-state
  mutators exist on `Task`.

2. **`materialize_task` is a free domain function** that attaches the
  creation event to a freshly-inserted Task. It is the sole emission
  site for that event and runs at the `NewTask → Task` conversion
  boundary owned by the repository.

## Alternatives Considered

### Decompose transitions into smaller mutators

Rejected — produces semantically-empty intermediate states that every
observer must reason about.

### Let callers construct events after a transition

Rejected — forces the caller to know which event matches which
transition and to keep payloads in sync. Event construction belongs to
the transition itself.

### `materialize_task` as a repository method, a `NewTask` method, or a class method

Rejected — a repository method leaks event types into infra; a
`NewTask` method consuming a post-persistence `Task` is an inversion;
a class method bypasses the repository as the sole
`NewTask → Task` conversion site. A free function is the narrowest
correct shape.

## Consequences

- **Positive:** Every state change is one atomic call; observers never
  see partial states.
- **Positive:** Callers never construct domain events or pass event
  payloads — the transition owns its event.
- **Positive:** Event construction stays in the domain layer; the UoW
  reads `task.events` directly.
- **Negative / trade-offs:** Transition methods take the union of all
  fields they may set, so callsites are slightly more verbose.
- **Accepted risks:** Direct callers of the Task entity break on the
  API change; acceptable because direct callers are internal and the
  public client facade is unaffected.
