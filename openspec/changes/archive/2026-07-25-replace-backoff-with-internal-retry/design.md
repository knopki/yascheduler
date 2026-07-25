## Context

The `backoff` library (v2.1.2) has been unmaintained since 2022 and produces deprecation warnings on Python 3.12+ (`asyncio.iscoroutinefunction`), currently suppressed via a warning filter in `pyproject.toml`. The codebase uses only a tiny subset of its API: `@backoff.on_exception` with `backoff.fibo` and `max_time=60` — no jitter, callbacks, `on_predicate`, or `max_tries`. The dependency is heavier than the value it provides.

The change replaces `backoff` with a small internal async retry utility in `yascheduler/shared/retry.py`, covering exactly the patterns used: decorator, partial, and direct-call forms, with exponential backoff, time-based deadline, exception filtering, and optional `giveup` callback.

## Goals / Non-Goals

**Goals:**
- Remove `backoff` dependency and its deprecation-warning suppression filter
- Provide an internal async retry utility that covers all existing usage patterns
- Preserve retry semantics: `max_time=60`, exception filtering, `giveup` callback
- Replace Fibonacci wait strategy with exponential backoff (comparable retry counts within 60s)

**Non-Goals:**
- No change to retry behavior or operational semantics
- No change to any other dependencies
- No change to public API, CLI, DB schema, INI format
- No sync retry support, no Trio support, no jitter, no callbacks

## Decisions

### Architecture: single function in shared module

One function `retry()` in `yascheduler/shared/retry.py`. No classes, no additional abstractions. The `shared` package already exists (`shared/compat.py`, `shared/log.py`) — natural home for a cross-cutting utility.

### API surface

```python
def retry(
    *,
    on: type[Exception] | tuple[type[Exception], ...],
    max_time: float = 60,
    giveup: Callable[[Exception], bool] | None = None,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    factor: float = 1.5,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
```

Three usage forms (all confirmed by spec):

1. **Decorator** — `@retry(on=aiohttp.ClientError, max_time=60)` (webhook.py, vastai.py)
2. **Partial** — `my_retry = partial(retry, on=SSHRetryExc, max_time=60)` → `@my_retry()` (session.py, repository.py)
3. **Direct-call** — `file_get_retry = my_retry()` → `await file_get_retry(sftp.get)(remote, local)` (download.py)

### Exponential backoff parameters

| Parameter | Value | Rationale |
|---|---|---|
| `initial_delay` | 1.0s | Matches first fibo value (1s) |
| `factor` | 1.5 | Gentle exponential growth |
| `max_delay` | 30.0s | Cap to avoid multi-minute waits |

Sequence: 1, 1.5, 2.25, 3.38, 5.06, 7.59, 11.39, 17.09, 25.63, 30... — ~6-8 attempts within 60s, comparable to fibo (1, 1, 2, 3, 5, 8, 13, 21, 34, 55 → ~7-8 attempts).

Note: fibo starts with 0 (first retry is immediate), while exponential starts at `initial_delay=1.0`. This means the first retry delay changes from 0s to 1.0s — a minor behavioral difference that does not affect correctness for any current use case.

### Error handling

- `CancelledError` — not caught, propagates immediately
- Non-matching exception (not in `on`) — propagates immediately
- `giveup` returns `True` — exception propagates immediately
- `max_time` exhausted — last exception propagates
- `asyncio.sleep` interrupted by cancellation — handled correctly

### Component structure

One file: `yascheduler/shared/retry.py`. One export: `__all__ = ["retry"]`.

### Testing approach

- **Unit tests** for `shared/retry.py` — pure async, tested via `asyncio.run` with `asyncio.sleep` monkeypatched for speed
- **No integration/e2e tests** — utility has no external dependencies
- **Existing test fixtures updated** to work with new retry utility instead of `backoff` internals; `backoff` logger-level check removed; `"backoff"` removed from import-hygiene forbidden-names list

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Exponential backoff produces different retry timing than Fibonacci | Both produce ~6-8 attempts within 60s — comparable for all current use cases. Documented in spec as intentional simplification. |
| New utility has untested edge cases (cancellation during sleep, deadline boundary) | Covered by unit tests. The implementation is ~30 lines — trivial to audit. |
| Existing tests monkeypatch `backoff._async` internals — need update | Straightforward: replace with monkeypatch of `asyncio.sleep` + time tracking. |
