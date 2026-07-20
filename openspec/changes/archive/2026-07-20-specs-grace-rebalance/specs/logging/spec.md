## MODIFIED Requirements

### Requirement: Module-local stdlib logger binding

The project SHALL bind every module-level logger in `yascheduler/` via
`logging.getLogger(__name__)`. Structured DEBUG tracing SHALL be emitted
via `logger.debug(msg, extra={...})` with flat user-supplied keys.

Every `extra={...}` callsite in the package SHALL use keys that do NOT
collide with native `LogRecord` attribute names. A static guard SHALL
reject any `extra={...}` literal in the package whose keys intersect the
native attribute set. The static guard tests are specified by the
`testing-unit` capability ("Logging discipline guard tests (reference)").

The contract text below is the authoritative source; `testing-unit` keeps
only a reference scenario to avoid duplication.

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

#### Scenario: descendant propagation keeps the log_records fixture functional

- **GIVEN** the `log_records` e2e fixture attaches a handler to the `"yascheduler"` logger at DEBUG
- **WHEN** a module `yascheduler.application.orchestrator` emits a DEBUG record via its `logging.getLogger(__name__)` logger
- **THEN** the record propagates to the `"yascheduler"` parent logger and is captured by the fixture handler
