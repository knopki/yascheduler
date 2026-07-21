## ADDED Requirements

### Requirement: Logging discipline guard tests

The project SHALL provide three guard unit tests in `tests/unit/` that
statically enforce the logging contract across the package:

1. **Trace-only DEBUG discipline**: no raw `.debug(` calls on loggers exist in
   `yascheduler/`. All structured DEBUG tracing SHALL go through
   `YaLogger.trace()`. The test SHALL walk the package source (AST or
   equivalent) and fail on any `.debug(` attribute call on a logger-like
   object. The shared logging module (`yascheduler/shared/log.py`) is exempt.
2. **M-ID validity and factory-only binding**: every `get_logger("<M-ID>")`
   call in `yascheduler/` passes a string literal that matches a real `<M-*>`
   tag name in `docs/knowledge-graph.xml`. The test SHALL parse the knowledge
   graph and assert every `get_logger(...)` string-literal argument matches an
   existing M-ID. The test SHALL additionally assert that no
   `logging.getLogger(...)` call inside `yascheduler/` (outside
   `yascheduler/shared/log.py`) is used for module-level logger binding — the
   factory is the only sanctioned path.
3. **No injected logger in collaborator constructors**: none of the seven
   collaborator classes (`Orchestrator`, `SSHMachineRepository`,
   `SSHMachineSession`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`,
   `CloudProvisionerImpl`) SHALL accept a parameter named `log` in their
   `__init__` method. The test SHALL AST-walk the seven collaborator modules
   and fail if any `__init__` method (or the class definition for frozen
   dataclasses) declares a parameter named `log`.

The guard tests SHALL run under the `unit` pytest marker and SHALL NOT
require external resources (no DB, no SSH, no cloud).

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
- **AND** no such direct binding exists in the committed package outside `yascheduler/shared/log.py`

#### Scenario: guard test fails on an injected logger parameter

- **GIVEN** the no-injected-logger guard test is run
- **WHEN** a `log` parameter appears in the `__init__` method of any of the seven collaborator classes (`Orchestrator`, `SSHMachineRepository`, `SSHMachineSession`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`, `CloudProvisionerImpl`)
- **THEN** the guard test fails, naming the class and the file
- **AND** no such `log` parameter exists in the committed package

#### Scenario: guard tests run under the unit marker without external resources

- **WHEN** the three guard tests are run via `uv run pytest -m unit`
- **THEN** all three pass without a database, SSH container, or cloud credentials

#### Scenario: guard tests pass on the committed package

- **GIVEN** the committed `yascheduler/` package and `docs/knowledge-graph.xml`
- **WHEN** the three guard tests are run via `uv run pytest -m unit`
- **THEN** all three pass (no raw `.debug(` calls, no fabricated M-ID literals, no direct `logging.getLogger` bindings, and no `log` parameters in collaborator `__init__` methods exist in the committed package)
