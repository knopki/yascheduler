# Logging

## Purpose

The `YaLogger`/`LogFormatter`/`get_logger` logging contract for the
`yascheduler` package. Structured DEBUG tracing goes through
`YaLogger.trace(block, **fields)`; user-facing INFO/WARN/ERROR records
render as plain narrative. The static-enforcement guard tests live in the
`testing-unit` spec.

## Requirements

### Requirement: YaLogger project logger class

The project SHALL provide a `YaLogger` subclass of `logging.Logger` exposing a single new method `trace(block, /, **fields)`. `trace()` SHALL emit a DEBUG-level record carrying the block marker and the structured fields so that consumers (formatters, tests) can access them without parsing the rendered message string. The block marker and the structured fields SHALL be exposed as attributes on the `LogRecord` for direct programmatic access.

The project SHALL provide a `get_logger(name: str) -> YaLogger` factory in `yascheduler/shared/log.py`. The factory SHALL prepend the `yascheduler.` namespace prefix to `name`, obtain the logger via `logging.getLogger`, and reclass the returned instance to `YaLogger` so its static type matches its runtime class. All package modules SHALL bind their module-level logger through `get_logger(...)`; direct `logging.getLogger(...)` calls inside `yascheduler/` SHALL NOT be used for module-level logger binding.

The project SHALL NOT use `logging.setLoggerClass`. The runtime class swap performed by `setLoggerClass` is invisible to static type checkers (typeshed declares `logging.getLogger(...) -> logging.Logger`), which would render every `log.trace(...)` callsite a static type error.

`YaLogger` SHALL inherit all standard `logging.Logger` methods (`debug`, `info`, `warning`, `error`, `exception`, `critical`, `log`) unchanged. User-facing narrative logs (INFO/WARN/ERROR) SHALL be emitted via these inherited methods and SHALL NOT carry grace markers or structured fields.

`trace()` SHALL be the only sanctioned path for DEBUG-level structured tracing in the package. Raw `.debug(` calls on package loggers SHALL NOT be used; all structured DEBUG tracing SHALL go through `.trace()`.

#### Scenario: get_logger returns a YaLogger with trace

- **WHEN** `get_logger("M-APPLICATION-ALLOCATE")` is called
- **THEN** the returned logger is an instance of `YaLogger`
- **AND** the logger exposes a callable `.trace` attribute
- **AND** the logger name is `yascheduler.M-APPLICATION-ALLOCATE` (the factory applied the namespace prefix)
- **AND** the static (declared) return type of `get_logger` is `YaLogger`, so `log.trace(...)` is type-valid without `cast` or `type: ignore`

#### Scenario: get_logger is idempotent across calls

- **GIVEN** `get_logger("M-APPLICATION-ALLOCATE")` has been called once
- **WHEN** `get_logger("M-APPLICATION-ALLOCATE")` is called again
- **THEN** the same logger object is returned (cached by `logging.getLogger`)
- **AND** the object's `__class__` is `YaLogger` (the reclassing is idempotent)

#### Scenario: trace emits a DEBUG record carrying block and fields

- **GIVEN** a `YaLogger` instance obtained via `get_logger`
- **WHEN** `log.trace("ALLOCATED", task_id=7, ip="10.0.0.1")` is called
- **THEN** a DEBUG-level `LogRecord` is emitted
- **AND** the record exposes the block marker `"ALLOCATED"` as a programmatic attribute
- **AND** the record exposes the structured fields `task_id=7` and `ip="10.0.0.1"` as programmatic attributes
- **AND** the record exposes the caller function name (the function that called `trace()`) as a programmatic attribute

#### Scenario: trace with no structured fields

- **GIVEN** a `YaLogger` instance obtained via `get_logger`
- **WHEN** `log.trace("BLOCK")` is called with no keyword arguments
- **THEN** a DEBUG-level `LogRecord` is emitted carrying the block marker `"BLOCK"`
- **AND** the record's structured-fields attribute is empty (no fields)

#### Scenario: user-facing inherited methods carry no grace markers

- **GIVEN** a `YaLogger` instance obtained via `get_logger`
- **WHEN** `log.warning("webhook retry to %s", url)` is called
- **THEN** the emitted record does NOT carry a grace block marker
- **AND** the record does NOT carry structured trace fields
- **AND** the rendered output is plain narrative (level, logger name, message)

#### Scenario: trace is DEBUG-only

- **GIVEN** a `YaLogger` instance obtained via `get_logger` and configured at INFO level
- **WHEN** `log.trace("BLOCK", k=v)` is called
- **THEN** no record is propagated to handlers (the DEBUG record is suppressed by the INFO threshold)

#### Scenario: setLoggerClass is not used

- **WHEN** the package source is inspected
- **THEN** no `logging.setLoggerClass(...)` call exists in `yascheduler/`
- **AND** no import-time side effect in `yascheduler/__init__.py` mutates the process-global logger class

### Requirement: M-ID namespaced logger names

The project SHALL canonicalize logger names to namespaced M-IDs of the form `yascheduler.<M-ID>` where `<M-ID>` is a real `<M-*>` tag name from `docs/knowledge-graph.xml`. The namespace prefix SHALL be applied centrally by the `get_logger(name)` factory, not repeated at each callsite.

Every `get_logger("<M-ID>")` call in the package SHALL pass a `<M-ID>` that is a real `<M-*>` tag name in `docs/knowledge-graph.xml`. The namespacing (`yascheduler.` prefix) SHALL be preserved so that logger propagation delivers records to the parent `"yascheduler"` logger, keeping the existing `log_records` capture fixture functional without rewriting its handler attachment. The static guard tests enforcing M-ID validity and factory-only binding live in the `testing-unit` spec.

#### Scenario: logger names are namespaced M-IDs

- **WHEN** a module under `yascheduler/application/allocate_task.py` binds its logger via `get_logger("M-APPLICATION-ALLOCATE")`
- **THEN** the resulting logger name is `yascheduler.M-APPLICATION-ALLOCATE` (a real M-ID from the knowledge graph)
- **AND** the logger is a descendant of the `"yascheduler"` logger in the logging hierarchy

#### Scenario: log_records fixture remains functional via propagation

- **GIVEN** the `log_records` e2e fixture attaches a handler to the `"yascheduler"` logger at DEBUG
- **WHEN** a descendant `yascheduler.M-APPLICATION-ALLOCATE` logger emits a trace record
- **THEN** the record propagates to the `"yascheduler"` parent logger and is captured by the fixture handler

### Requirement: LogFormatter renders trace and user-facing records distinctly

The project SHALL provide a `LogFormatter` that renders grace trace records and user-facing records with distinct layouts. Trace records (records carrying the trace block marker and structured fields) SHALL render with the M-ID, the auto-captured function name, the block marker, and the structured `key=value` fields. User-facing records (INFO/WARN/ERROR emitted via inherited methods) SHALL render as plain narrative (timestamp, level, logger name, message) with no markers and no structured fields.

`LogFormatter` SHALL be wired onto both the stderr `StreamHandler` and the file `FileHandler` configured by `configure_logger`. A single formatter SHALL be used for both handlers; the project SHALL NOT maintain per-handler format variants.

The structured `key=value` rendering SHALL be deterministic so that log-driven tests can rely on stable field ordering. Fields SHALL be drawn exclusively from the trace record's structured-fields attribute; the formatter SHALL NOT scan the `LogRecord.__dict__` for arbitrary non-reserved attributes.

#### Scenario: trace record renders with M-ID, function, block, and fields

- **GIVEN** a `LogFormatter` is attached to a handler and a `YaLogger` emits `log.trace("ALLOCATED", ip="10.0.0.1", task_id=7)`
- **WHEN** the handler renders the record
- **THEN** the output line contains the M-ID portion of the logger name (e.g. `M-APPLICATION-ALLOCATE`), the auto-captured function name, the block marker `[ALLOCATED]`, and the structured fields rendered as deterministic `key=value` pairs
- **AND** the output line is grep-friendly for the block marker

#### Scenario: user-facing record renders as plain narrative

- **GIVEN** a `LogFormatter` is attached to a handler and a `YaLogger` emits `log.warning("webhook retry to %s", url)`
- **WHEN** the handler renders the record
- **THEN** the output line contains timestamp, level, logger name, and the message only
- **AND** the output line does NOT contain a grace block marker
- **AND** the output line does NOT contain structured `key=value` trace fields

#### Scenario: single formatter serves both handlers

- **WHEN** `configure_logger` is invoked with a file path
- **THEN** both the `StreamHandler(sys.stderr)` and the `FileHandler` are configured with the same `LogFormatter` instance or equivalent configuration
