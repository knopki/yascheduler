## MODIFIED Requirements

### Requirement: Logging discipline guard tests

The project SHALL provide two guard unit tests in `tests/unit/` that
statically enforce the logging contract across the package:

1. **No injected logger in collaborator constructors**: none of the seven
   collaborator classes (`Orchestrator`, `SSHMachineRepository`,
   `SSHMachineSession`, `TaskDeployer`, `OutputDownloader`,
   `OccupancyChecker`, `CloudProvisionerImpl`) SHALL accept a parameter
   named `log` in their `__init__` method. The test SHALL statically
   verify the seven collaborator modules and fail if any `__init__`
   method (or the class definition for frozen dataclasses) declares a
   parameter named `log`.
2. **No extra-key collision with native LogRecord attributes**: every
   `extra={...}` literal callsite in `yascheduler/` SHALL use keys that
   do NOT collide with the native `LogRecord` attribute set (the keys
   present on a freshly constructed `logging.LogRecord`). The test
   SHALL statically verify the package source and fail on any
   `extra={...}` literal whose key set intersects the native attribute
   set, because stdlib merges `extra` into the record via
   `__dict__.update` and silently overwrites reserved keys
   (e.g. `name`, `msg`, `funcName`, `levelname`, `lineno`, `module`).

The project SHALL NOT retain the former "trace-only DEBUG discipline"
guard (raw `.debug(` calls are now the sanctioned trace path via
`debug(msg, extra=...)`), the "M-ID validity and factory-only binding"
guard (the `get_logger` factory and M-ID logger names are removed), or
any synthetic-violation meta-tests specific to those removed guards.

The guard tests SHALL run under the `unit` pytest marker without
external resources.

#### Scenario: guard test fails on an injected logger parameter

- **GIVEN** the no-injected-logger guard test is run
- **WHEN** a `log` parameter appears in the `__init__` method of any of the seven collaborator classes (`Orchestrator`, `SSHMachineRepository`, `SSHMachineSession`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`, `CloudProvisionerImpl`)
- **THEN** the guard test fails, naming the class and the file
- **AND** no such `log` parameter exists in the committed package

#### Scenario: guard test fails on an extra-key collision with a native LogRecord attribute

- **GIVEN** the extra-key-collision guard test is run
- **WHEN** a `logger.debug(msg, extra={...})` callsite in `yascheduler/` uses a key that is a native `LogRecord` attribute name (e.g. `funcName`, `levelname`, `msg`, `name`)
- **THEN** the guard test fails, naming the file, the offending key, and the call
- **AND** no such colliding `extra` key exists in the committed package

#### Scenario: guard tests run under the unit marker without external resources

- **WHEN** the two guard tests are run via `uv run pytest -m unit`
- **THEN** both pass without a database, SSH container, or cloud credentials

#### Scenario: guard tests pass on the committed package

- **GIVEN** the committed `yascheduler/` package
- **WHEN** the two guard tests are run via `uv run pytest -m unit`
- **THEN** both pass (no `log` parameters in collaborator `__init__` methods and no `extra`-key collisions with native `LogRecord` attributes exist in the committed package)
