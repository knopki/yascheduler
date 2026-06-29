# Platform Adapters

## Purpose

Provide platform-specific SSH adapters (Linux, Debian, etc.) relocated from
remote_machine/ to infra/ssh/platform/ with backward-compatible re-exports.

## Requirements

### Requirement: Platform code relocated

The system SHALL provide all platform-specific modules in
`infra/ssh/platform/` as the sole location. The `remote_machine/` package
SHALL NOT exist. The `PEngine` and `PEngineRepository` Protocols SHALL NOT
exist in `infra/ssh/platform/protocol.py`; platform modules
(`infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`,
`infra/ssh/gateway.py`) SHALL import `Engine`, `EngineRepository`, and
`Deploy*` (`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`)
from `yascheduler.domain` directly.

The `PProcessInfo` and `PNode` Protocols SHALL NOT exist in
`infra/ssh/platform/protocol.py`. The `ProcessInfo` frozen dataclass (fields
`pid: int`, `name: str`, `command: str`) SHALL be defined in
`infra/ssh/platform/protocol.py`. Platform modules
(`infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`) and the
package `infra/ssh/platform/__init__.py` SHALL import `ProcessInfo` from
`.protocol` (or the package re-export), not from `.common`.
`infra/ssh/platform/common.py` SHALL NOT define `ProcessInfo`.

#### Scenario: Adapters accessible at new location
- **WHEN** the adapters module is imported from infra.ssh.platform.adapters
- **THEN** the adapter registry is accessible

#### Scenario: Platform checks accessible
- **WHEN** check_is_linux is imported from infra.ssh.platform.checks
- **THEN** the check function is accessible

#### Scenario: OS-specific methods accessible
- **WHEN** linux_setup_node is imported from infra.ssh.platform.linux
- **THEN** the function is accessible

#### Scenario: PEngine Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PEngine`
- **THEN** the `PEngine` Protocol class is absent; consumers import `Engine` from `yascheduler.domain`

#### Scenario: PEngineRepository Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PEngineRepository`
- **THEN** the `PEngineRepository` Protocol class is absent; consumers import `EngineRepository` from `yascheduler.domain`

#### Scenario: Platform modules import Deploy types from domain
- **WHEN** `infra/ssh/platform/linux.py` or `infra/ssh/platform/windows.py` is inspected for `Deploy*` imports
- **THEN** the import is `from yascheduler.domain import LocalArchiveDeploy, LocalFilesDeploy, RemoteArchiveDeploy` (not `from yascheduler.config import ...`)

#### Scenario: PProcessInfo Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PProcessInfo`
- **THEN** the `PProcessInfo` Protocol class is absent

#### Scenario: PNode Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PNode`
- **THEN** the `PNode` Protocol class is absent

#### Scenario: ProcessInfo defined in protocol module
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `ProcessInfo`
- **THEN** a frozen dataclass `ProcessInfo` with fields `pid: int`, `name: str`, `command: str` is defined there

#### Scenario: Platform modules import ProcessInfo from protocol
- **WHEN** `infra/ssh/platform/linux.py` or `infra/ssh/platform/windows.py` is inspected for the `ProcessInfo` import
- **THEN** the import is `from .protocol import ProcessInfo` (not `from .common import ProcessInfo`)

#### Scenario: Package init imports ProcessInfo from protocol
- **WHEN** `infra/ssh/platform/__init__.py` is inspected for the `ProcessInfo` import
- **THEN** `ProcessInfo` is imported from `.protocol` and remains in `__all__`

#### Scenario: common.py does not define ProcessInfo
- **WHEN** `infra/ssh/platform/common.py` is inspected for `ProcessInfo`
- **THEN** no `ProcessInfo` class is defined there

#### Scenario: PProcessInfo and PNode absent from package re-export
- **WHEN** `infra/ssh/platform/__init__.py` is inspected for `PProcessInfo` or `PNode`
- **THEN** neither name appears in the `from .protocol import (...)` block nor in `__all__`

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

These symbols SHALL NOT be imported from `infra/ssh/helpers.py` (the
module is deleted). `infra/ssh/platform/__init__.py` SHALL re-export them
so consumers can import from the package facade.

#### Scenario: ADAPTERS imported from platform package

- **WHEN** `ADAPTERS` is needed by a consumer (e.g., `repository.py`)
- **THEN** it is imported from `yascheduler.infra.ssh.platform` (or a sub-module under `platform/`), not from `infra/ssh/helpers.py`

#### Scenario: _detect_platform imported from platform package

- **WHEN** `_detect_platform(conn, adapters)` is called from `repository.connect`
- **THEN** the function is imported from `yascheduler.infra.ssh.platform` (or `platform/detect.py`), and returns the same `(adapter, platforms)` tuple the previous `helpers.py` implementation returned

#### Scenario: _init_paths imported from platform package

- **WHEN** `_init_paths(adapter, data_dir, engines_dir, tasks_dir)` is called from `repository.connect`
- **THEN** the function is imported from `yascheduler.infra.ssh.platform` (or `platform/paths.py`), and returns the same `(data_dir, engines_dir, tasks_dir)` tuple normalized to `adapter.path`

#### Scenario: MAX_SESSIONS lives next to _detect_platform

- **WHEN** `platform/detect.py` is inspected
- **THEN** `MAX_SESSIONS` is defined in the same module as `_detect_platform` (its only consumer)

#### Scenario: helpers.py is deleted

- **WHEN** the `infra/ssh/` package is inspected for `helpers.py`
- **THEN** the file is absent; no consumer imports from `infra/ssh/helpers.py`

### Requirement: make_run_fn located in platform package

The system SHALL provide a `make_run_fn(conn: SSHClientConnection,
adapter: RemoteMachineAdapter) -> OuterRunCallable` function in
`yascheduler/infra/ssh/platform/run_fn.py`. The function is a pure
closure that binds `conn` and `adapter.quote` into an `OuterRunCallable`
suitable for passing to `adapter.get_cpu_cores` and
`adapter.setup_node`.

The function name is `make_run_fn` (public, no leading underscore) — the
leading underscore is dropped on extraction from `gateway.py:_make_run_fn`
because the function becomes a public utility of the `platform/` package
rather than a private method of the gateway class. The behavior is
unchanged: `make_run_fn(conn, adapter)` returns an
`OuterRunCallable` equivalent to the prior `gateway._make_run_fn`.

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
