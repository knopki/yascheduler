## MODIFIED Requirements

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

`LogFormatter` SHALL be wired onto both the stderr `StreamHandler` and
the file `FileHandler` configured by `configure_logger`. A single
formatter SHALL be used for both handlers.

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
