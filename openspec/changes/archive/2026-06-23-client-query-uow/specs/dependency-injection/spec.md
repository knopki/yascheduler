## ADDED Requirements

### Requirement: Yascheduler deps_factory test seam

The `Yascheduler.__init__` constructor SHALL accept an optional
keyword-only `deps_factory: Callable[[Config], CLIDeps]` parameter. When
`deps_factory is None`, the constructor SHALL lazily default to
`make_cli_deps` (invoked per query call, not cached). The factory passed
via `deps_factory` SHALL be invoked as `<factory>(self.config)` exactly
once per `queue_get_tasks_async` call to obtain a fresh `CLIDeps`,
mirroring the per-call construction pattern already used by
`queue_submit_task_async`.

The factory invocation SHALL be synchronous (not awaited).

#### Scenario: deps_factory defaults to make_cli_deps
- **WHEN** `Yascheduler()` is constructed without `deps_factory`
- **THEN** the first `queue_get_tasks_async` call invokes `make_cli_deps(self.config)` to obtain `CLIDeps`

#### Scenario: deps_factory injects a test double
- **WHEN** `Yascheduler(deps_factory=lambda cfg: fake_deps)` is constructed with a `fake_deps` whose `uow_factory` returns a `FakeUnitOfWork`
- **THEN** `queue_get_tasks_async` uses the injected `fake_deps.uow_factory` and does not call `make_cli_deps`

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, lambda cfg: fake_deps)` is called with the factory positionally
- **THEN** `TypeError` is raised

#### Scenario: Factory is invoked once per query call
- **WHEN** `queue_get_tasks_async` is called twice on the same `Yascheduler` instance with `deps_factory` set to a counting spy
- **THEN** the factory callable is invoked twice (no caching; a fresh `CLIDeps` is produced each time)

#### Scenario: Factory invocation is synchronous
- **WHEN** `queue_get_tasks_async` invokes the configured `deps_factory`
- **THEN** the factory callable returns `CLIDeps` directly (it is NOT awaited; `deps_factory` is not declared `async` and the result is used synchronously)
