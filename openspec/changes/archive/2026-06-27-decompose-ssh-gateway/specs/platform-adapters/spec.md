## ADDED Requirements

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