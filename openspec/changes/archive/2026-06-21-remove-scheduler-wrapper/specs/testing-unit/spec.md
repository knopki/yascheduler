## MODIFIED Requirements

### Requirement: Client queue-submit characterization

Tests SHALL verify that `Yascheduler.queue_submit_task_async` (in
`yascheduler/client.py`) submits a task through the composition root's
`make_cli_deps()` factory and does not instantiate the daemon graph.
Specifically, `queue_submit_task_async` MUST call
`make_cli_deps(config).submit(label, metadata, engine_name)` and return
its result.

#### Scenario: Yascheduler.queue_submit_task_async uses make_cli_deps
- **WHEN** `Yascheduler().queue_submit_task_async(label="t", metadata={"k": "v"}, engine_name="fleur")` is called with `make_cli_deps` patched to return a mock `CLIDeps` whose `submit` is an `AsyncMock`
- **THEN** `make_cli_deps` is called once with the client's `config`, `deps.submit` is awaited once with `("t", {"k": "v"}, "fleur")`, and the awaited return value is returned to the caller
