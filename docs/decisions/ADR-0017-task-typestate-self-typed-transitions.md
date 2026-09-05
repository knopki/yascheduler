# ADR-0017: Task typestate — self-typed transitions

- **Status:** Accepted
- **Date:** 2026-08-02
- **Supersedes:**
- **Superseded by:**

## Context

ADR-0012 expresses the task lifecycle as atomic transition methods that validate
the source state at runtime. The prior change moved the CHECK-correlated fields
onto `Todo` / `Running` / `Done` value objects and gave `Task` a `state` field.
Two defects remained:

- **Illegal transitions caught at runtime only.** A task loaded wide
  still lets `running_task.run(...)` type-check; the call fails later with
  `TaskNotTodoError`. The type system cannot express which transition is legal
  from which state, because the state lives on a field, not on the type of the
  object itself.
- **Compatibility properties widened the narrow path.** The prior
  change added read-only properties on `Task` returning the old Optional shape,
  so a consumer could bypass the narrow state fields without the checker
  noticing.

## Decision

1. **`Task` carries its state on its type.** A covariant type parameter
   bounds `Task` to the state union. Covariance is sound because `Task` is
   frozen (ADR-0002) — a wider reference cannot mutate the state. Type aliases
   (`TodoTask`, `RunningTask`, `DoneTask`, `AnyTask`) are the public names; the
   bare `Task` type is lint-banned outside the persistence mapper and tests.

2. **Each transition declares its legal source state as its receiver
   type.** An illegal call is a static error, not a runtime raise. The runtime
   source-state checks stay as defense in depth for untyped entry points,
   preserving the `TaskNotTodoError` / `TaskNotRunningError` contract.

3. **Repository ports return the narrow type for single-status
   queries.** `get_running` / `get_todo` / `list_running` / `list_todo` return
   the state-specific task type; wide queries return the union. The narrow type
   originates at row hydration and flows through the port signature, so
   consumers receive it without manual narrowing. `get_running` returning `None`
   on wrong status collapses the post-load race-skip narrowing at every
   consumer.

4. **Compatibility properties removed.** Any-status readers (the client
   facade, mixed-status CLI) read through free helper functions that return
   Optional and must be called deliberately — not through properties that
   quietly widen the type.

## Alternatives Considered

### Invariant type parameter

Rejected — the narrow state type would not be assignable to the union, so
narrowing helpers and port signatures would be rejected by the checker.
Covariance is the right model for a frozen container.

### Protocol views over the concrete `Task`

Rejected — a Protocol→concrete downcast is forbidden by every checker, so `save`
/ `replace` over a transition result would need reverse casts at every boundary.

### Parallel classes per state (sum type)

Rejected — triples the field definitions, breaks manual sync with the DB schema,
and transitions stop being methods on `Task` (conflicts with ADR-0012).

### `TypeGuard` instead of `TypeIs`

Rejected — `TypeGuard` does not narrow the negative branch, so a chain of
narrowing checks would not reduce the else-branch to the remaining states.

## Consequences

- **Positive:** Illegal transitions are compile-time errors. The narrow
  path is the only path the checker accepts on single-status loads.
- **Positive:** `get_running` / `get_todo` collapse the race-skip
  narrowing at `consume_task`, `allocate_task`, and the hard-remove path into a
  `None`-skip.
- **Negative / trade-offs:** One unchecked retag-cast in the shared
  transition helper — the price of typestate on a frozen dataclass. Localized to
  one function; a wrong retag surfaces as a static self-type error at the call
  site.
- **Accepted risks:** Covariance soundness relies on `Task` staying
  frozen. A future change making `Task` mutable would make covariance unsound;
  ADR-0002 mandates frozen entities.
