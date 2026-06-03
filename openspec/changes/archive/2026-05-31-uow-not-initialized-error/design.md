## Context

`PostgresUnitOfWork` (adapter layer) raises `RuntimeError` in three places when its API contract is violated — accessing `tasks`/`nodes` properties or calling `commit()`/`rollback()` without entering the `async with` block. The project already has a domain exception hierarchy (`DomainError` in `domain/exceptions.py`) but UoW errors are adapter-layer programming mistakes, not domain business errors. ARCHITECTURE.md §4.2 plans a future `ApplicationError → InfrastructureError → PersistenceError` tree, but that tree doesn't exist yet.

## Goals / Non-Goals

**Goals:**
- Replace bare `RuntimeError` with a named, catchable exception
- Place the exception in the adapter layer where it belongs
- Maintain backward compatibility (`except RuntimeError` still works)

**Non-Goals:**
- Implementing the full `ApplicationError` / `InfrastructureError` hierarchy from §4.2
- Creating exceptions for cloud or SSH adapter layers
- Changing the UoW Protocol (`AbstractUnitOfWork`) or its contract

## Decisions

### 1. Inherit from `RuntimeError`

**Choice:** `UnitOfWorkNotInitializedError(RuntimeError)`

**Alternatives considered:**
- `UnitOfWorkNotInitializedError(Exception)` — breaks `except RuntimeError` silently; no semantic gain
- `UnitOfWorkNotInitializedError(InfrastructureError)` — root class doesn't exist yet; premature coupling

**Rationale:** `RuntimeError` is the stdlib's exception for "API used in wrong state" (no event loop, reentrant lock, coroutine already awaited). Our case matches this pattern exactly. Inheriting from `RuntimeError` preserves backward compatibility and is semantically correct.

### 2. File location: `adapters/persistence/exceptions.py`

**Choice:** New file in the persistence adapter package.

**Rationale:** This is an adapter-layer concern. Domain exceptions (`domain/exceptions.py`) are for business rules. The UoW state contract is a persistence implementation detail. When the `ApplicationError` tree is built, this class can be rebased without moving files.

### 3. Single class for all three raise sites

**Choice:** One `UnitOfWorkNotInitializedError` class with different messages.

**Rationale:** All three sites (`tasks`, `nodes`, `_require_conn`) represent the same state: "UoW was not entered." Different messages are enough to distinguish the exact call site. No need for three separate subclasses.

## Risks / Trade-offs

- **Future rebasing** — When `ApplicationError` tree is implemented, parent class changes from `RuntimeError` to something under `ProgrammingError`. Simple find-and-replace; no behavioral change.
- **Import surface** — Adds one import to `postgres_uow.py`. Negligible.
