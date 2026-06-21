## Why

`yascheduler/scheduler.py` is a 192-LOC backward-compat wrapper that predates
the clean-architecture migration. It carries an explicit `# FIXME: remove this
module` (line 22). A consumer audit shows its `class Scheduler` has **zero
production consumers** — `client.py` submits via `make_cli_deps()`, the
`daemonize` CLI starts the daemon via `make_daemon()` directly, and the AiiDA
plugin uses the `Yascheduler` client. The only production reference to the
module is `get_logger` (one lazy import in `daemonize.py`). Keeping the file
forces every architectural-spec update to keep listing `scheduler.py` as a
composition-root member and obscures the real composition root (`di.py`).

## What Changes

- **Remove** `yascheduler/scheduler.py` in its entirety.
- **Inline** `get_logger` into `yascheduler/adapters/cli/daemonize.py` as the
  module-private `_get_logger` (sole consumer, ~25 LOC, daemon-only).
- **BREAKING (internal API)**: `class Scheduler`, `Scheduler.create()`,
  `Scheduler.create_new_task()`, `Scheduler.start()`, `Scheduler.stop()`, and
  the module-level `get_logger` and `WebhookPayload` re-export are removed.
  These symbols were never in `yascheduler/__init__.py`, never in
  `[project.scripts]`, and never imported by the AiiDA entry point; the
  documented public API is `class Yascheduler` and is unchanged.
- **Remove** scheduler-specific tests:
  - `tests/unit/test_scheduler.py` (whole file).
  - `tests/unit/test_characterization.py`: drop `TestSchedulerCreateNewTask`,
    `TestSchedulerStart`, `TestSchedulerStop`; keep
    `TestClientQueueSubmitTaskAsync`.
  - `tests/fixtures/mock_scheduler.py` (whole file): both `make_scheduler`
    and `create_test_config` have no surviving consumers once
    `test_scheduler.py` is deleted; relocating `create_test_config` would be
    speculative (YAGNI).
- **Move** the two `WebhookPayload` construction tests from the deleted
  `test_scheduler.py` into `tests/unit/test_webhook_handler.py`.
- **Remove** `test_utils_import_does_not_import_scheduler` from
  `tests/unit/test_cli_smoke.py` — its target module no longer exists, so
  the assertion becomes a stale tautology.
- **Update** documentation and specs to remove all references to
  `yascheduler/scheduler.py` as a composition-root member (see Impact).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `package-facades`: remove `yascheduler.scheduler` from the
  "outside-layer-set exemptions" composition-root list, from the R2
  "composition root imports use layer facades" scenario, from the "Extended
  facade contents" prose where `yascheduler.scheduler` is listed as a consumer
  of `CloudProvisionerImpl`, `CloudAdapter`, `Orchestrator`, and `submit_task`,
  and from the "Documented private-symbol carve-outs" (the `_resolve_adapter`
  carve-out stays for `yascheduler.di` only).
- `testing-unit`: rewrite the "Scheduler characterization tests" requirement
  at `openspec/specs/testing-unit/spec.md:188-196` into a
  "Client queue-submit characterization" requirement that retains the
  surviving `Yascheduler.queue_submit_task_async` scenario (the only spec
  mention of this behavior — no other requirement covers it; deletion would
  leave both the kept test and the production behavior without a spec
  mandate). Scheduler-specific scenarios are removed.
- `db-wrapper`: rewrite the "Existing scheduler code compiles unchanged"
  scenario (`openspec/specs/db-wrapper/spec.md:26-28`) so its caller
  reference no longer names `scheduler.py`. The surviving
  `get_tasks_by_status` consumer is `yascheduler/client.py`; the scenario
  is updated to reflect that.

## Impact

- **Code removed**: `yascheduler/scheduler.py` (192 LOC).
- **Code modified**:
  - `yascheduler/adapters/cli/daemonize.py` — replace
    `from yascheduler.scheduler import get_logger` with an inlined
    module-private `_get_logger`.
- **Tests removed**: `tests/unit/test_scheduler.py` (whole file),
  `tests/fixtures/mock_scheduler.py` (whole file), three classes from
  `tests/unit/test_characterization.py`, and
  `test_utils_import_does_not_import_scheduler` from
  `tests/unit/test_cli_smoke.py`.
- **Tests added/moved**:
  - Two `WebhookPayload` construction tests → `tests/unit/test_webhook_handler.py`.
- **Documentation**:
  - `docs/ARCHITECTURE.md` — remove `scheduler.py` from §1 diagram, §2
    component table, §2.2 last paragraph, §2.9, §3.7, §4 tree.
  - `docs/knowledge-graph.xml` — remove `<M-SCHEDULER>` element and its four
    `<CrossLink>` edges (lines 882, 909, 910, 934). No other `<depends>` list
    references M-SCHEDULER (verified); the defensive "update depends" phrasing
    is therefore a no-op but kept as a safety net.
- **Specs**: `openspec/specs/package-facades/spec.md`,
  `openspec/specs/testing-unit/spec.md`, and
  `openspec/specs/db-wrapper/spec.md` updated per the Capabilities section.
- **GRACE-lite validation**: `grace_check.py` must pass after graph update.
- **Public API**: `yascheduler/__init__.py` exports
  (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `__version__`)
  unchanged. AiiDA entry point unchanged. CLI commands unchanged.
- **No new dependencies**, no DB schema change, no config-format change.
