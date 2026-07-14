## ADDED Requirements

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

The project SHALL canonicalize logger names to namespaced M-IDs of the form `yascheduler.<M-ID>` where `<M-ID>` is a real `<M-*>` tag name from `docs/knowledge-graph.xml`. The six ad-hoc `[Module]` ontologies (class name, use-case name, module path, platform, provider, ad-hoc label) SHALL be replaced by canonical M-IDs. The namespace prefix SHALL be applied centrally by the `get_logger(name)` factory (Decision: factory in `yascheduler/shared/log.py`), not repeated at each callsite.

Every `get_logger("<M-ID>")` call in the package SHALL pass a `<M-ID>` that is a real `<M-*>` tag name in `docs/knowledge-graph.xml`. A guard unit test SHALL verify this by parsing the knowledge graph and asserting every `get_logger(...)` string-literal argument in `yascheduler/` matches a real `<M-*>` tag name.

The namespacing (`yascheduler.` prefix) SHALL be preserved so that logger propagation delivers records to the parent `"yascheduler"` logger, keeping the existing `log_records` capture fixture functional without rewriting its handler attachment.

#### Scenario: logger names are namespaced M-IDs

- **WHEN** a module under `yascheduler/application/allocate_task.py` binds its logger via `get_logger("M-APPLICATION-ALLOCATE")`
- **THEN** the resulting logger name is `yascheduler.M-APPLICATION-ALLOCATE` (a real M-ID from the knowledge graph)
- **AND** the logger is a descendant of the `"yascheduler"` logger in the logging hierarchy

#### Scenario: guard test rejects a fabricated M-ID

- **GIVEN** the guard unit test for M-ID validity is run
- **WHEN** a `get_logger("M-FABRICATED-NONEXISTENT")` call appears in `yascheduler/`
- **THEN** the guard test fails, naming the call and the file
- **AND** no such fabricated call exists in the committed package

#### Scenario: guard test rejects a direct logging.getLogger binding

- **GIVEN** the guard unit test for M-ID validity is run
- **WHEN** a `logging.getLogger("yascheduler.M-...")` call used for module-level logger binding appears in `yascheduler/`
- **THEN** the guard test fails, naming the call and the file
- **AND** no such direct binding exists in the committed package outside `yascheduler/shared/log.py`

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

### Requirement: Guard tests enforce trace discipline and M-ID validity

The project SHALL provide two guard unit tests in `tests/unit/` that statically enforce the logging contract across the package:

1. **Trace-only DEBUG discipline**: no raw `.debug(` calls on loggers exist in `yascheduler/`. All structured DEBUG tracing SHALL go through `YaLogger.trace()`. The test SHALL walk the package source (AST or equivalent) and fail on any `.debug(` attribute call on a logger-like object.
2. **M-ID validity and factory-only binding**: every `get_logger("<M-ID>")` call in `yascheduler/` passes a string literal that matches a real `<M-*>` tag name in `docs/knowledge-graph.xml`. The test SHALL parse the knowledge graph and assert every `get_logger(...)` string-literal argument matches an existing M-ID. The test SHALL additionally assert that no `logging.getLogger(...)` call inside `yascheduler/` (outside `yascheduler/shared/log.py`) is used for module-level logger binding — the factory is the only sanctioned path.

The guard tests SHALL run under the `unit` pytest marker and SHALL NOT require external resources (no DB, no SSH, no cloud).

#### Scenario: guard test fails on a raw debug call

- **GIVEN** the trace-only DEBUG discipline guard test is run
- **WHEN** a `log.debug("...")` call appears in `yascheduler/` (not via `.trace()`)
- **THEN** the guard test fails, naming the file and the offending call
- **AND** no such raw `.debug(` call exists in the committed package

#### Scenario: guard test fails on a fabricated M-ID literal

- **GIVEN** the M-ID validity guard test is run
- **WHEN** a `get_logger("M-FABRICATED-NONEXISTENT")` call references an M-ID absent from `docs/knowledge-graph.xml`
- **THEN** the guard test fails, naming the call and the file
- **AND** no such fabricated call exists in the committed package

#### Scenario: guard test fails on a direct logging.getLogger binding

- **GIVEN** the M-ID validity guard test is run
- **WHEN** a `logging.getLogger("yascheduler.M-...")` call (used for module-level logger binding) appears in `yascheduler/` outside `yascheduler/shared/log.py`
- **THEN** the guard test fails, naming the call and the file
- **AND** no such direct binding exists in the committed package

#### Scenario: guard tests run under the unit marker without external resources

- **WHEN** the two guard tests are run via `uv run pytest -m unit`
- **THEN** both pass without a database, SSH container, or cloud credentials

#### Scenario: guard tests pass on the committed package

- **GIVEN** the committed `yascheduler/` package and `docs/knowledge-graph.xml`
- **WHEN** the two guard tests are run via `uv run pytest -m unit`
- **THEN** both pass (no raw `.debug(` calls and no fabricated M-ID literals exist in the committed package)

#### Scenario: trace with no structured fields

- **GIVEN** a `YaLogger` instance obtained via `get_logger`
- **WHEN** `log.trace("BLOCK")` is called with no keyword arguments
- **THEN** a DEBUG-level `LogRecord` is emitted carrying the block marker `"BLOCK"`
- **AND** the record's structured-fields attribute is empty (no fields)

### Requirement: Split of test-targeted user-facing emits into trace plus narrative

The user-facing emits (INFO/WARN/ERROR) that are simultaneously test-targeted SHALL be split into two records: a `trace()` DEBUG record (the test target, carrying the block marker and structured fields) and a clean narrative record (the user target, carrying plain prose). The split points correspond to the markers currently asserted by unit or e2e tests via substring matching: webhook `RETRY`, `abandon_node` `CLOUD_DELETE_FAILED`, `abandon_node` `AMBIGUOUS_TRACKER`, orchestrator `CONNECT_RETRY_STATIC`, orchestrator `CONNECT_RETRY`, orchestrator `CONNECT_ABANDON`, orchestrator `ABANDON_FAILED`, orchestrator `CONSUMER_ERROR`, orchestrator `PRODUCER_ERROR`, orchestrator `_print_stats` `ERROR`, `SSHRepository` `CPUs`.

The test SHALL assert on the trace record's `block` attribute and `fields` attribute, not on substring matching against the narrative record's rendered message.

#### Scenario: webhook RETRY splits into trace plus warning narrative

- **GIVEN** the webhook send path hits a retryable client error
- **WHEN** the retry is logged
- **THEN** a `trace("RETRY", url=...)` DEBUG record is emitted (test target)
- **AND** a separate `warning("webhook retry to %s", url)` narrative record is emitted (user target)
- **AND** the warning narrative does NOT contain a grace block marker

#### Scenario: abandon_node CLOUD_DELETE_FAILED splits into trace plus error narrative

- **GIVEN** `clouds.deallocate` raises an exception during abandon
- **WHEN** the failure is logged
- **THEN** a `trace("CLOUD_DELETE_FAILED", node_id=..., hostname=..., cloud=..., err=...)` DEBUG record is emitted (test target)
- **AND** a separate `error(...)` narrative record is emitted (user target)
- **AND** the error narrative does NOT contain a grace block marker

#### Scenario: abandon_node AMBIGUOUS_TRACKER splits into trace plus warning narrative

- **GIVEN** `tracker.discard_by_node` returns a count greater than 1
- **WHEN** the ambiguity is logged
- **THEN** a `trace("AMBIGUOUS_TRACKER", node_id=..., hostname=..., count=...)` DEBUG record is emitted (test target)
- **AND** a separate `warning(...)` narrative record is emitted (user target)
- **AND** the warning narrative does NOT contain a grace block marker

#### Scenario: orchestrator CONNECT_RETRY_STATIC splits into trace plus warning narrative

- **GIVEN** a static node (`cloud is None`) raises `MachineConnectionError`
- **WHEN** the connect-machine producer handles the failure
- **THEN** a `trace("CONNECT_RETRY_STATIC", ...)` DEBUG record is emitted (test target)
- **AND** a separate `warning(...)` narrative record is emitted (user target)
- **AND** the warning narrative does NOT contain a grace block marker

#### Scenario: orchestrator CONNECT_RETRY splits into trace plus warning narrative

- **GIVEN** a cloud node raises `MachineConnectionError` within the grace window
- **WHEN** the connect-machine producer handles the failure
- **THEN** a `trace("CONNECT_RETRY", ...)` DEBUG record is emitted (test target)
- **AND** a separate `warning(...)` narrative record is emitted (user target)
- **AND** the warning narrative does NOT contain a grace block marker

#### Scenario: orchestrator CONNECT_ABANDON splits into trace plus error narrative

- **GIVEN** a cloud node's connect-failure age exceeds `connect_grace`
- **WHEN** the abandon path fires
- **THEN** a `trace("CONNECT_ABANDON", ...)` DEBUG record is emitted (test target)
- **AND** a separate `error(...)` narrative record is emitted (user target)
- **AND** the error narrative does NOT contain a grace block marker

#### Scenario: orchestrator ABANDON_FAILED splits into trace plus error narrative

- **GIVEN** the `abandon_node` use case raises an exception
- **WHEN** the failure is logged
- **THEN** a `trace("ABANDON_FAILED", node_id=..., err=...)` DEBUG record is emitted (test target)
- **AND** a separate `error(...)` narrative record is emitted (user target)
- **AND** the error narrative does NOT contain a grace block marker

#### Scenario: orchestrator CONSUMER_ERROR splits into trace plus error narrative

- **GIVEN** a consumer coroutine raises a non-CancelledError exception
- **WHEN** the error is logged
- **THEN** a `trace("CONSUMER_ERROR", ...)` DEBUG record is emitted (test target)
- **AND** a separate `error(...)` narrative record is emitted (user target)

#### Scenario: orchestrator PRODUCER_ERROR splits into trace plus error narrative

- **GIVEN** a producer coroutine raises a non-CancelledError exception
- **WHEN** the error is logged
- **THEN** a `trace("PRODUCER_ERROR", ...)` DEBUG record is emitted (test target)
- **AND** a separate `error(...)` narrative record is emitted (user target)

#### Scenario: orchestrator _print_stats error splits into trace plus error narrative

- **GIVEN** the stats background job raises a non-CancelledError exception
- **WHEN** the error is logged
- **THEN** a `trace("ERROR", ...)` DEBUG record carrying the stats context is emitted (test target)
- **AND** a separate `error(...)` narrative record is emitted (user target)

#### Scenario: SSHRepository CPUs splits into trace plus info narrative

- **GIVEN** a machine is connected and its CPU count is detected
- **WHEN** the CPU count is logged
- **THEN** a `trace("CPUS", hostname=..., ncpus=...)` DEBUG record is emitted (test target)
- **AND** a separate `info("connected to %s (%d CPUs)", hostname, ncpus)` narrative record is emitted (user target)
- **AND** the info narrative does NOT contain a grace block marker

### Requirement: Cleanup of non-test-targeted WARN/ERROR emits to pure narrative

The remaining WARN/ERROR emits that are NOT test-targeted SHALL be cleaned to pure narrative without grace block markers and without an accompanying `trace()` DEBUG double. No `trace()` double SHALL be added for these emits; the cleanup is limited to removing the marker and rendering the message as readable prose.

#### Scenario: non-test-targeted warning renders as pure narrative

- **GIVEN** a cleanup-path warning that is not asserted by any test (e.g. cloud stop failure, disconnect-all failure, http close failure)
- **WHEN** the warning is logged
- **THEN** the record is a plain `warning(...)` narrative with no grace block marker
- **AND** no accompanying `trace(...)` DEBUG double is emitted for this warning

#### Scenario: cloud CREATE_FAILED renders as pure narrative

- **GIVEN** the cloud provisioner fails to create a VM
- **WHEN** the creation failure is logged
- **THEN** the record is a plain `error(...)` narrative with no grace block marker
- **AND** no accompanying `trace(...)` DEBUG double is emitted for this failure

#### Scenario: webhook GIVEUP renders as pure narrative

- **GIVEN** the webhook handler gives up after exhausting retries
- **WHEN** the giveup is logged
- **THEN** the record is a plain `exception(...)` narrative with no grace block marker
- **AND** no accompanying `trace(...)` DEBUG double is emitted for this giveup