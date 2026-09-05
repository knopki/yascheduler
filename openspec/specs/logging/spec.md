## Purpose

The `yascheduler` logging contract: module-local stdlib loggers, two
render layouts (trace and regular), an optional ISO 8601 timestamp
prefix, and routing of warnings through logging. The mechanism for
module-local binding, structured trace emission, and trace-record
discrimination is fixed in ADR-0011; this spec states only the
observable outcomes. The static logging-discipline guard tests live
in the `testing-unit` spec.

## Requirements

### Requirement: Module-local logger binding

The project SHALL bind every module-level logger by stdlib with the
module's own dotted name, so a record's logger name identifies its
source module without any mapping artifact. Structured trace records
SHALL be emitted at the DEBUG level with a flat set of user-supplied
fields. The emission mechanism and the trace-record discriminator
live in ADR-0011.

#### Scenario: a record carries the source module of its emitter

- **WHEN** any module under the project package emits a log record
- **THEN** the record's logger name identifies that module as a dotted path rooted at the project package

### Requirement: Two render layouts

A rendered line SHALL use one of two layouts. A trace record — a
structured DEBUG record from an in-package module — SHALL render with
the source module, the function name, the source line, the message,
and the structured fields sorted alphabetically by key. Any other
record SHALL render as the level, the logger name, and the message,
with no structured fields.

#### Scenario: a trace record renders with module, function, line, message, and sorted fields

- **WHEN** a structured DEBUG record that carries one or more user-supplied fields is rendered
- **THEN** the output line contains the source module, the function name, the source line, the message, and the structured fields in alphabetical order by key

#### Scenario: a regular record renders with level, name, and message

- **WHEN** any record that is not a trace record is rendered
- **THEN** the output line contains the level, the logger name, and the message, and no structured fields

### Requirement: Optional ISO 8601 timestamp prefix

The formatter SHALL support an ISO 8601 timestamp prefix derived from
the record's emit time and prepended to both layouts. The prefix is
optional and is configured per launcher; the launcher table that sets
it lives in the `cli` spec.

#### Scenario: a timestamp-enabled line carries the emit time at the front

- **WHEN** a record is rendered on a timestamp-enabled formatter
- **THEN** the output line begins with an ISO 8601 timestamp derived from the record's emit time, followed by the layout-specific suffix

### Requirement: Warnings routed through logging

The logger setup SHALL route Python warnings through the logging
system, so a warning is rendered by the formatter instead of being
written directly to stderr.

#### Scenario: a warning is rendered as a log record

- **WHEN** a warning is raised after the logger setup has run
- **THEN** the warning is rendered through the logging formatter like any other record

### Requirement: Exception details are rendered

A rendered record that carries exception information SHALL include the exception type, message, and traceback after its trace or regular message layout. Rendering exception details SHALL preserve the timestamp policy and SHALL NOT change the ordering or layout of structured DEBUG fields. Error messages produced by yascheduler SHALL NOT include database passwords, DSNs, or configuration objects containing credentials.

#### Scenario: regular SQL error retains traceback

- **WHEN** a regular error record is emitted with a SQL exception attached
- **THEN** the rendered output contains the regular error layout followed by the SQL exception type, message, and traceback

#### Scenario: structured trace error retains traceback

- **WHEN** an in-package structured DEBUG record is emitted with exception information attached
- **THEN** the rendered output contains the trace layout with its sorted structured fields followed by the exception type, message, and traceback
