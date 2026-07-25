## ADDED Requirements

### Requirement: Internal async retry utility

The system SHALL provide an internal async retry utility in `yascheduler/shared/retry.py` that covers the patterns currently served by the `backoff` library: decorator form, partial form, and direct-call form. The utility SHALL support exponential backoff, time-based deadline (`max_time`), exception filtering (`on`), and optional `giveup` callback.

The utility SHALL be async-only (no sync variant). It SHALL NOT depend on any third-party library.

#### Scenario: Decorator retries on matching exception

- **WHEN** a function decorated with `@retry(on=ValueError, max_time=10)` raises `ValueError` and the deadline has not expired
- **THEN** the function is retried with exponential backoff until it succeeds or the deadline expires

#### Scenario: Non-matching exception propagates immediately

- **WHEN** a function decorated with `@retry(on=ValueError, max_time=10)` raises `TypeError`
- **THEN** the `TypeError` propagates immediately without retry

#### Scenario: giveup stops retry

- **WHEN** a function decorated with `@retry(on=ValueError, max_time=60, giveup=lambda e: True)` raises `ValueError`
- **THEN** the exception propagates immediately (giveup returns True, no retry)

#### Scenario: max_time deadline is honored

- **WHEN** a function decorated with `@retry(on=ValueError, max_time=1)` keeps raising `ValueError`
- **THEN** the last `ValueError` propagates after approximately `max_time` seconds

#### Scenario: Successful call returns result

- **WHEN** a function decorated with `@retry(on=ValueError, max_time=10)` raises `ValueError` once then succeeds
- **THEN** the return value of the successful call is returned

#### Scenario: Partial form works

- **WHEN** `my_retry = partial(retry, on=ValueError, max_time=10)` is used as a decorator `@my_retry()`
- **THEN** it behaves identically to `@retry(on=ValueError, max_time=10)`

#### Scenario: Direct-call form works

- **WHEN** `file_get_retry = my_retry()` is called and the result is used as `await file_get_retry(some_fn)(arg)`
- **THEN** `some_fn(arg)` is retried with the same backoff policy
