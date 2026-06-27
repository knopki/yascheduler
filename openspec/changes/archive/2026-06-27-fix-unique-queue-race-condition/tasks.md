## 1. Core implementation

- [x] 1.1 Add class-level annotation `_put_lock: asyncio.Lock` and assign `self._put_lock = asyncio.Lock()` in `UniqueQueue.__init__`
- [x] 1.2 Wrap check+act in `UniqueQueue.put()` with `async with self._put_lock` — entering the lock before the dedup check, releasing after `super().put()` completes
- [x] 1.3 Update `START_CHANGE_SUMMARY LAST_CHANGE` in `queue.py` to reference this change; bump `VERSION` header (1.8.0 → 1.9.0)

## 2. Unit tests

- [x] 2.1 Write test `test_put_race_full_queue` that reproduces the race: fill queue to `maxsize=1`, launch two concurrent `put(Y)` coroutines until both suspend in `super().put()`, then drain via `get()` and verify `q.qsize() == 0` with a single successful put counter
- [x] 2.2 Update `START_MODULE_MAP` in `test_queue.py` to list `test_put_race_full_queue`; refresh `START_CHANGE_SUMMARY LAST_CHANGE`; bump `VERSION` (1.1.0 → 1.2.0)

## 3. Verification

- [x] 3.1 Run `uv run pytest -m unit tests/unit/test_queue.py` — all existing + new tests pass
- [x] 3.2 Run `uv run pytest -m unit` — no regressions in orchestrator tests
- [x] 3.3 Run `uv run ruff check .` and `uv run ruff format --check .` — no lint issues
- [x] 3.4 Run `uv run zuban check` — zero new type errors in queue.py
- [x] 3.5 Run `python3 scripts/grace_check.py` — exit 0
- [x] 3.6 Run `openspec validate --all --json` — validation passes
