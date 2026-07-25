## Why

The `backoff` library (v2.1.2) has not had a meaningful release since 2022. It now produces deprecation warnings on Python 3.12+ (`asyncio.iscoroutinefunction`), which are already suppressed in `pyproject.toml` via a warning filter. The original PyPI package is effectively abandoned; a community fork exists under a different package name (`python-backoff`), creating ecosystem fragmentation.

Meanwhile, the codebase uses only a tiny subset of backoff's API: the `@backoff.on_exception` decorator with `backoff.fibo` wait generator and `max_time=60`. No jitter, no callbacks, no `on_predicate`, no `max_tries`, no custom wait generators. The dependency is heavier than the value it provides, and maintaining a suppression filter for a dead library is not sustainable.

## What Changes

- **Add** `yascheduler/shared/retry.py` — a small internal async retry utility that covers exactly the patterns used in the codebase: decorator form, partial form, and direct-call form, with exponential backoff, time-based deadline, exception filtering, and optional `giveup` callback.
- **Replace** all `backoff` usages in production code with the new internal utility:
  - `webhook.py` — `@backoff.on_exception(backoff.fibo, ...)` → `@retry(on=..., ...)`
  - `vastai.py` — same, with `giveup` lambda preserved
  - `session.py` — `my_backoff_exc` partial → `my_retry` partial
  - `download.py` — `my_backoff_sftp` partial → `my_retry` partial
- **Replace** Fibonacci wait strategy (`backoff.fibo`) with exponential backoff — both produce comparable retry counts within a 60s window (~7-8 attempts), and exponential is simpler to implement and tune.
- **Remove** `backoff~=2.1.2` from `pyproject.toml` dependencies and the associated `DeprecationWarning` suppression filter.
- **Update** test files that reference `backoff` internals or check `backoff` logger level.

## Non-Goals

- No change to retry semantics: `max_time=60` preserved, exception filtering preserved, `giveup` preserved.
- No change to any other dependencies.
- No change to public API, CLI, DB schema, INI format, or operational behavior.
- The shift from Fibonacci to exponential backoff is an intentional simplification (both produce comparable retry counts within 60s), not a behavioral regression.

## Capabilities

### New Capabilities

- `shared` (new module): `retry(on, max_time, giveup, ...)` — async retry decorator with exponential backoff, time-based deadline, and exception filtering.

### Modified Capabilities

- `ssh-infrastructure` (spec): retry on SSH operations continues to work identically, backed by internal utility instead of `backoff`.
- `domain-events-and-dispatch` (spec): webhook retry continues to work identically, backed by internal utility instead of `backoff`.

## Impact

- **Code**: `yascheduler/shared/retry.py` (new, ~30 lines), `webhook.py`, `vastai.py`, `session.py`, `download.py` (import + decorator changes).
- **Config**: `pyproject.toml` — remove `backoff~=2.1.2` dependency and `DeprecationWarning` suppression filter.
- **Tests**: `test_webhook_handler.py` (replace `_fast_backoff` fixture), `test_ssh_gateway_download_outputs.py` (update `_no_sftp_backoff` fixture), `test_daemon_common.py` (remove `test_backoff_level_error`), `test_application_no_adapter_imports.py` (remove `"backoff"` from `FORBIDDEN_NAMES`).
- **Specs**: delta specs for `ssh-infrastructure` and `domain-events-and-dispatch` confirming retry behavior is unchanged.
- **Dependencies**: `backoff` removed.
