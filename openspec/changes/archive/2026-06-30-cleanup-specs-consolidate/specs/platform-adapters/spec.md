## MODIFIED Requirements

### Requirement: Platform code relocated

The system SHALL provide all platform-specific modules in
`infra/ssh/platform/` as their sole location. Platform modules
(`infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`,
`infra/ssh/gateway.py`) SHALL import `Engine`, `EngineRepository`, and the
`Deploy*` types (`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`)
from `yascheduler.domain`.

The `ProcessInfo` frozen dataclass (fields `pid: int`, `name: str`, `command: str`)
SHALL be defined in `infra/ssh/platform/protocol.py`. Platform modules
(`infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`) and the package
`infra/ssh/platform/__init__.py` SHALL import `ProcessInfo` from `.protocol`
(or the package re-export). `infra/ssh/platform/common.py` SHALL NOT define
`ProcessInfo`.

#### Scenario: Adapters accessible at new location
- **WHEN** the adapters module is imported from infra.ssh.platform.adapters
- **THEN** the adapter registry is accessible

#### Scenario: Platform checks accessible
- **WHEN** check_is_linux is imported from infra.ssh.platform.checks
- **THEN** the check function is accessible

#### Scenario: OS-specific methods accessible
- **WHEN** linux_setup_node is imported from infra.ssh.platform.linux
- **THEN** the function is accessible

#### Scenario: Platform modules import Deploy types from domain
- **WHEN** `infra/ssh/platform/linux.py` or `infra/ssh/platform/windows.py` is inspected for `Deploy*` imports
- **THEN** the import is `from yascheduler.domain import LocalArchiveDeploy, LocalFilesDeploy, RemoteArchiveDeploy`

#### Scenario: ProcessInfo defined in protocol module
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `ProcessInfo`
- **THEN** a frozen dataclass `ProcessInfo` with fields `pid: int`, `name: str`, `command: str` is defined there

#### Scenario: Platform modules import ProcessInfo from protocol
- **WHEN** `infra/ssh/platform/linux.py` or `infra/ssh/platform/windows.py` is inspected for the `ProcessInfo` import
- **THEN** the import is `from .protocol import ProcessInfo`

#### Scenario: Package init imports ProcessInfo from protocol
- **WHEN** `infra/ssh/platform/__init__.py` is inspected for the `ProcessInfo` import
- **THEN** `ProcessInfo` is imported from `.protocol` and remains in `__all__`

#### Scenario: common.py does not define ProcessInfo
- **WHEN** `infra/ssh/platform/common.py` is inspected for `ProcessInfo`
- **THEN** no `ProcessInfo` class is defined there

### Requirement: Platform detection symbols located in platform package

The system SHALL provide all platform-detection symbols in
`yascheduler/infra/ssh/platform/` as their sole location. Specifically:

- `ADAPTERS` — ordered registry of platform adapter instances (debian,
  linux, darwin, windows variants) — SHALL be importable from
  `yascheduler.infra.ssh.platform` (or a sub-module such as
  `platform/registry.py`).
- `_detect_platform(conn, adapters) -> tuple[RemoteMachineAdapter,
  Sequence[str]]` — runs adapter checks on a connected host, returns
  the first matching adapter and all matched platform names; raises
  `PlatformGuessFailedError` if no adapter matches — SHALL be importable
  from `yascheduler.infra.ssh.platform` (or `platform/detect.py`).
- `_init_paths(adapter, data_dir, engines_dir, tasks_dir) ->
  tuple[PurePath, PurePath, PurePath]` — normalizes remote
  data/engines/tasks dirs using `adapter.path` — SHALL be importable
  from `yascheduler.infra.ssh.platform` (or `platform/paths.py`).
- `MAX_SESSIONS` — default `MaxSessions` on OpenSSH server (10); used
  only by `_detect_platform` to bound concurrency — SHALL live next to
  `_detect_platform` (in `platform/detect.py`).

`infra/ssh/platform/__init__.py` SHALL re-export these symbols so consumers
can import from the package facade.

#### Scenario: ADAPTERS imported from platform package

- **WHEN** `ADAPTERS` is needed by a consumer (e.g., `repository.py`)
- **THEN** it is imported from `yascheduler.infra.ssh.platform` (or a sub-module under `platform/`)

#### Scenario: _detect_platform imported from platform package

- **WHEN** `_detect_platform(conn, adapters)` is called from `repository.connect`
- **THEN** the function is imported from `yascheduler.infra.ssh.platform` (or `platform/detect.py`), and returns the `(adapter, platforms)` tuple

#### Scenario: _init_paths imported from platform package

- **WHEN** `_init_paths(adapter, data_dir, engines_dir, tasks_dir)` is called from `repository.connect`
- **THEN** the function is imported from `yascheduler.infra.ssh.platform` (or `platform/paths.py`), and returns the `(data_dir, engines_dir, tasks_dir)` tuple normalized to `adapter.path`

#### Scenario: MAX_SESSIONS lives next to _detect_platform

- **WHEN** `platform/detect.py` is inspected
- **THEN** `MAX_SESSIONS` is defined in the same module as `_detect_platform` (its only consumer)

### Requirement: make_run_fn located in platform package

The system SHALL provide a `make_run_fn(conn: SSHClientConnection,
adapter: RemoteMachineAdapter) -> OuterRunCallable` function in
`yascheduler/infra/ssh/platform/run_fn.py`. The function is a pure
closure that binds `conn` and `adapter.quote` into an `OuterRunCallable`
suitable for passing to `adapter.get_cpu_cores` and `adapter.setup_node`.

The function SHALL NOT live in `infra/ssh/repository.py` or
`infra/ssh/operations/` — it is platform-adapter glue and belongs with
the platform layer so both `repository.connect` (which uses it to
populate `ConnectedMachine.ncpus`) and `operations.base.get_cpu_cores` /
`setup_node` can import it without creating cross-module dependencies
between `repository.py` and `operations/base.py`.

#### Scenario: make_run_fn imported from platform package

- **WHEN** `make_run_fn(conn, adapter)` is needed by `repository.connect` or `operations.base`
- **THEN** it is imported from `yascheduler.infra.ssh.platform.run_fn`

#### Scenario: make_run_fn returns a callable usable by adapter

- **WHEN** `make_run_fn(conn, adapter)` is called
- **THEN** the returned `OuterRunCallable`, when called as `run_fn("some-command")`, invokes `adapter.run(conn, adapter.quote, "some-command", ...)` and returns the awaited `SSHCompletedProcess`
