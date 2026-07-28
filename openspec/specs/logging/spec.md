# Logging

## Purpose

The `LogFormatter` logging contract for the `yascheduler` package. Module-level
loggers are bound via stdlib `logging.getLogger(__name__)`. Structured DEBUG
tracing goes through `logger.debug(msg, extra={...})` with flat user-supplied
keys; user-facing INFO/WARN/ERROR records render as plain narrative. The static
guard tests live in the `testing-unit` spec.

## Requirements

### Requirement: Module-local stdlib logger binding

The project SHALL bind every module-level logger in `yascheduler/` via
`logging.getLogger(__name__)`. Structured DEBUG tracing SHALL be emitted
via `logger.debug(msg, extra={...})` with flat user-supplied keys.

Every `extra={...}` callsite in the package SHALL use keys that do NOT
collide with native `LogRecord` attribute names. A static guard SHALL
reject any `extra={...}` literal in the package whose keys intersect the
native attribute set.

#### Scenario: module logger is bound via logging.getLogger(__name__)

- **WHEN** a module under `yascheduler/` binds its module-level logger
- **THEN** the binding is `logger = logging.getLogger(__name__)`
- **AND** no project factory or wrapper (e.g. `get_logger`) is invoked

#### Scenario: structured DEBUG trace uses flat extra keys

- **WHEN** a package module emits a structured DEBUG record
- **THEN** the call is `logger.debug(msg, extra={...})` with flat user-supplied keys
- **AND** the `extra` dict is NOT a nested sentinel container (e.g. `extra={"trace": {...}}`)
- **AND** the call is NOT routed through a project-defined wrapper function

#### Scenario: extra keys do not collide with native LogRecord attributes

- **GIVEN** the native `LogRecord` attribute set (the keys present on a freshly constructed `logging.LogRecord`)
- **WHEN** a package callsite emits `logger.debug(msg, extra={...})`
- **THEN** no key in the `extra` dict is a member of the native attribute set
- **AND** a static guard rejects any `extra={...}` literal in the package whose keys intersect the native set

#### Scenario: descendant propagation keeps the log_records fixture functional

- **GIVEN** the `log_records` e2e fixture attaches a handler to the `"yascheduler"` logger at DEBUG
- **WHEN** a module `yascheduler/application/orchestrator.py` emits a DEBUG record via its `logging.getLogger(__name__)` logger
- **THEN** the record propagates to the `"yascheduler"` parent logger and is captured by the fixture handler

### Requirement: LogFormatter renders trace and user-facing records distinctly

The project SHALL provide a `LogFormatter` that renders structured trace
records and user-facing records with distinct layouts.

A record is a trace record if and only if ALL THREE hold: (a) its level
is `DEBUG`, AND (b) it carries user-supplied attributes beyond the native
`LogRecord` attribute set, AND (c) its logger name belongs to the
project package. The package prefix used both for the shortname strip and
for the in-package gate SHALL be the top segment of the formatter
module's own `__name__`. Records failing any of the three conditions are
regular records. The native `LogRecord` attribute set used for the
extra-diff SHALL be derived once at import time from a freshly
constructed `logging.LogRecord` instance.

Trace records SHALL render as
`[<module>][<funcName>]:<lineno> <message> <sorted key=value pairs>`
where `<module>` is the logger name with the package prefix stripped,
and the `key=value` pairs are sorted alphabetically by key for
deterministic output. Regular records SHALL render as
`<LEVEL> <name>: <message>` with no markers and no structured fields.

Trace fields SHALL be exactly the record attributes that are not
members of the native `LogRecord` attribute set.

`LogFormatter` SHALL support an optional ISO 8601 timestamp prefix that,
when enabled on a given formatter instance, is prepended to BOTH the
trace layout and the regular layout of every rendered record. The
timestamp SHALL be derived from the record's emit time (the moment the
`LogRecord` was constructed, not the moment it is rendered) and rendered
in local time as `YYYY-MM-DDTHH:MM:SS,mmm` (e.g.
`2026-07-28T12:34:56,789`), followed by a single space separating the
timestamp from the layout-specific suffix. When timestamping is not
enabled on a formatter instance, the trace and regular layouts SHALL
render exactly as if the timestamp feature did not exist.

`LogFormatter` SHALL be wired onto both the stderr `StreamHandler` and
the file `FileHandler` configured by `configure_logger`. A single
formatter SHALL be used for both handlers, and the timestamp-enabled or
timestamp-disabled configuration SHALL be identical on both handlers.

#### Scenario: trace record renders with module, function, lineno, message, and sorted fields

- **GIVEN** a `LogFormatter` is attached to a handler and a package module emits `logger.debug("ALLOCATED", extra={"ip": "10.0.0.1", "task_id": 7})`
- **WHEN** the handler renders the record
- **THEN** the output line contains the logger name with the package prefix stripped (e.g. `application.allocate_task`), the auto-captured function name, the source line number, the message `ALLOCATED`, and the structured fields rendered as deterministic sorted `key=value` pairs (alphabetically by key)
- **AND** the output line is grep-friendly for the message

#### Scenario: trace fields are sorted alphabetically for deterministic output

- **GIVEN** a `LogFormatter` is attached to a handler and a package module emits `logger.debug("B", extra={"zebra": 1, "alpha": 2})`
- **WHEN** the handler renders the record
- **THEN** the `key=value` pairs appear with `alpha` before `zebra`

#### Scenario: DEBUG record without extra renders as regular narrative

- **GIVEN** a `LogFormatter` is attached to a handler and a package module emits `logger.debug("progress: ok")` with no `extra`
- **WHEN** the handler renders the record
- **THEN** the output line is `<LEVEL> <name>: <message>` (regular layout)
- **AND** the output line does NOT contain the trace markers (`[module][funcName]:lineno` form) or `key=value` pairs

#### Scenario: out-of-package DEBUG record with extra renders as regular narrative

- **GIVEN** a `LogFormatter` is attached to the root handler and a third-party logger (e.g. `asyncssh` or `backoff`) emits a DEBUG record carrying extra attributes
- **WHEN** the handler renders the record
- **THEN** the output line is `<LEVEL> <name>: <message>` (regular layout), because the in-package gate excludes third-party loggers
- **AND** the output line does NOT contain trace markers or `key=value` pairs

#### Scenario: INFO/WARN/ERROR record renders as regular narrative

- **GIVEN** a `LogFormatter` is attached to a handler and a package module emits `logger.warning("webhook retry to %s", url)`
- **WHEN** the handler renders the record
- **THEN** the output line is `<LEVEL> <name>: <message>` with no trace markers
- **AND** the output line does NOT contain structured `key=value` fields

#### Scenario: single formatter serves both handlers

- **WHEN** `configure_logger` is invoked with a file path
- **THEN** both the `StreamHandler(sys.stderr)` and the `FileHandler` are configured with the same `LogFormatter` instance or equivalent configuration

#### Scenario: timestamp-enabled trace record prepends ISO 8601 prefix

- **GIVEN** a timestamp-enabled `LogFormatter` is attached to a handler and a package module emits `logger.debug("ALLOCATED", extra={"task_id": 7})`
- **WHEN** the handler renders the record
- **THEN** the output line begins with a `YYYY-MM-DDTHH:MM:SS,mmm` timestamp in local time, followed by a single space, followed by the trace layout `[<module>][<funcName>]:<lineno> <message> <sorted key=value pairs>`

#### Scenario: timestamp-enabled regular record prepends ISO 8601 prefix

- **GIVEN** a timestamp-enabled `LogFormatter` is attached to a handler and a package module emits `logger.warning("webhook retry to %s", url)`
- **WHEN** the handler renders the record
- **THEN** the output line begins with a `YYYY-MM-DDTHH:MM:SS,mmm` timestamp in local time, followed by a single space, followed by the regular layout `<LEVEL> <name>: <message>`

#### Scenario: timestamp-disabled formatter renders identically to a formatter with no timestamp feature

- **GIVEN** a timestamp-disabled `LogFormatter` is attached to a handler
- **WHEN** a trace record and a regular record are rendered
- **THEN** both output lines contain NO leading timestamp
- **AND** the trace line is `[<module>][<funcName>]:<lineno> <message> <sorted key=value pairs>` exactly
- **AND** the regular line is `<LEVEL> <name>: <message>` exactly

#### Scenario: timestamp reflects the record emit time, not the render time

- **GIVEN** a timestamp-enabled `LogFormatter` and a record whose emit time is `T_emit` (the instant the `LogRecord` was constructed)
- **WHEN** the record is rendered at a later instant `T_render > T_emit`
- **THEN** the leading timestamp corresponds to `T_emit` (local time, millisecond precision), NOT to `T_render`

#### Scenario: timestamp prefix is identical on stderr and file handlers

- **GIVEN** `configure_logger` is invoked with a file path and timestamping enabled
- **WHEN** a record is rendered by both the `StreamHandler(sys.stderr)` and the `FileHandler`
- **THEN** both output lines carry the same leading ISO 8601 timestamp for the same record
