## Why

`PostgresUnitOfWork` raises bare `RuntimeError` for programming-contract violations (accessing repositories or calling commit/rollback without entering the context manager). This prevents callers from distinguishing UoW misuse from other runtime errors and inconsistent with the project's move toward a typed exception hierarchy.

## What Changes

- Introduce `UnitOfWorkNotInitializedError(RuntimeError)` in `adapters/persistence/exceptions.py`
- Replace all three `raise RuntimeError(...)` in `postgres_uow.py` with `raise UnitOfWorkNotInitializedError(...)`
- Update unit tests to catch `UnitOfWorkNotInitializedError` instead of `RuntimeError`

## Capabilities

### New Capabilities

- `uow-not-initialized-error`: Named exception for UoW state-contract violations, replacing bare `RuntimeError`

### Modified Capabilities

- `postgres-uow`: Raises `UnitOfWorkNotInitializedError` instead of `RuntimeError`
- `testing-unit`: Unit tests updated to catch `UnitOfWorkNotInitializedError`

## Impact

- `yascheduler/adapters/persistence/postgres_uow.py` — 3 raise sites changed
- `yascheduler/adapters/persistence/exceptions.py` — new file (1 class)
- `tests/unit/test_persistence_adapter.py` — 1 `pytest.raises` updated
- `docs/knowledge-graph.xml` — new M-PERSISTENCE-EXCEPTIONS module, updated M-PERSISTENCE-UOW annotations
- Backward compatible: `UnitOfWorkNotInitializedError` inherits from `RuntimeError`, so existing `except RuntimeError` still works
