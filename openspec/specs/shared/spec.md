## Purpose

Cross-cutting utilities shared across layers. Holds the internal
async retry utility that replaces the former `backoff` dependency.

## Requirements

### Requirement: Internal async retry utility

The system SHALL provide an internal async retry utility. The utility
SHALL retry a failing async operation on a matching exception, with
exponential backoff, up to a time-based deadline. A non-matching
exception SHALL propagate immediately. An optional giveup callback
SHALL stop retry early.

The utility SHALL be async-only and SHALL NOT depend on any
third-party library. The decision to keep retries internal is recorded
in ADR-0014.

The utility SHALL be invokable as a function wrapper, with partial
configuration, and as a direct call.

#### Scenario: matching exception is retried until success or deadline

- **WHEN** a retried operation raises a matching exception and the deadline has not expired
- **THEN** the operation is retried with exponential backoff until it succeeds or the deadline expires

#### Scenario: non-matching exception propagates immediately

- **WHEN** a retried operation raises an exception that does not match the filter
- **THEN** the exception propagates immediately, with no retry

#### Scenario: deadline expires and the last exception propagates

- **WHEN** a retried operation keeps raising a matching exception until the deadline expires
- **THEN** the last exception propagates

#### Scenario: giveup callback stops retry early

- **WHEN** a retried operation raises a matching exception and the giveup callback returns true
- **THEN** the exception propagates immediately, with no retry
