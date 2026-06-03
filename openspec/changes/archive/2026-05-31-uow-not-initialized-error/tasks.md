## 1. Exception class

- [x] 1.1 Create `yascheduler/adapters/persistence/exceptions.py` with GRACE-lite MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY; define `UnitOfWorkNotInitializedError(RuntimeError)`
- [x] 1.2 Re-export `UnitOfWorkNotInitializedError` from `yascheduler/adapters/persistence/__init__.py`

## 2. Replace RuntimeError in postgres_uow.py

- [x] 2.1 Import `UnitOfWorkNotInitializedError` in `postgres_uow.py`
- [x] 2.2 Replace `raise RuntimeError(...)` in `tasks` property (line ~64)
- [x] 2.3 Replace `raise RuntimeError(...)` in `nodes` property (line ~72)
- [x] 2.4 Replace `raise RuntimeError(...)` in `_require_conn` (line ~166)
- [x] 2.5 Update MODULE_MAP and CHANGE_SUMMARY in `postgres_uow.py`

## 3. Update tests

- [x] 3.1 Update `tests/unit/test_persistence_adapter.py`: change `pytest.raises(RuntimeError, ...)` to `pytest.raises(UnitOfWorkNotInitializedError, ...)` in `test_uow_commit_after_exit_raises`

## 4. Knowledge graph

- [x] 4.1 Add `M-PERSISTENCE-EXCEPTIONS` module to `docs/knowledge-graph.xml`
- [x] 4.2 Add `CrossLink` from `M-PERSISTENCE-UOW` to `M-PERSISTENCE-EXCEPTIONS`
- [x] 4.3 Update `M-PERSISTENCE` re-exports and `M-PERSISTENCE-UOW` annotations

## 5. Validation

- [x] 5.1 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`
- [x] 5.2 Run `python3 scripts/grace_check.py`
- [x] 5.3 Run `openspec validate --all --json`
- [x] 5.4 Run relevant unit tests
