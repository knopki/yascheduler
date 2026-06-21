# Explore Brief — remove-scheduler-wrapper

## Context

`yascheduler/scheduler.py` (192 LOC) is a thin backward-compat wrapper that
predates the clean-architecture migration. It carries `# FIXME: remove this
module` at line 22. Three distinct concerns live in it, each with a different
fate.

## Consumer audit (verified by grep + codegraph)

| Symbol              | Production consumers                                | Test consumers                                                 |
| ------------------- | --------------------------------------------------- | -------------------------------------------------------------- |
| `class Scheduler`   | **none** (client.py uses `make_cli_deps`; daemonize.py uses `make_daemon` directly) | `tests/fixtures/mock_scheduler.py`, `tests/unit/test_scheduler.py`, `tests/unit/test_characterization.py` (3 of 4 classes) |
| `def get_logger`    | `yascheduler/adapters/cli/daemonize.py` (lazy import inside `daemonize()`) | none                                                           |
| `WebhookPayload` re-export | **none** (canonical home is `yascheduler/webhook.py`; `adapters/notifier/webhook.py` imports from there) | `tests/unit/test_scheduler.py` line 33 (one `TestWebhookPayload` class) |

## Rejected alternatives

1. **Keep `Scheduler` as a thin orchestrator facade for external scripts** —
   rejected: `Scheduler` is not in `yascheduler/__init__.py` exports, not in
   `[project.scripts]`, not referenced by AiiDA plugin (`aiida_plugin.py`
   uses `Yascheduler` client). Documented public API is `class Yascheduler`.
2. **Deprecation cycle (warn now, remove later)** — rejected: no production
   consumer exists; deprecation warning would fire only in test runs.
3. **Extract `get_logger` to a new `yascheduler/log.py` module** — rejected
   (YAGNI): single consumer, ~25 lines, daemon-only.
4. **Move `get_logger` to `di.py`** — rejected: `di.py` is the composition
   root for wiring, not logging setup; mixing concerns.

## Final approach

- **Delete** `yascheduler/scheduler.py` entirely.
- **Inline** `get_logger` into `yascheduler/adapters/cli/daemonize.py` (the
  sole consumer), demoted to a module-private `_get_logger` (no other
  consumers, no re-export).
- **Delete** all `Scheduler`-specific tests:
  - `tests/unit/test_scheduler.py` (entire file)
  - `tests/unit/test_characterization.py` — drop `TestSchedulerCreateNewTask`,
    `TestSchedulerStart`, `TestSchedulerStop`; keep
    `TestClientQueueSubmitTaskAsync` (it tests `client.py`, not `Scheduler`).
  - `tests/fixtures/mock_scheduler.py` — drop `make_scheduler`; relocate
    `create_test_config` to `tests/fixtures/config.py` (still useful for
    remaining client tests).
- **Move** the two `WebhookPayload` construction tests from the deleted
  `test_scheduler.py` into `tests/unit/test_webhook_handler.py` (already
  imports from `yascheduler.webhook`).
- **Update docs and specs** (see mapping below).

## Documentation / spec delta map

```
docs/ARCHITECTURE.md
├── §1 ASCII diagram box "scheduler.py"               → remove
├── §2 Component Reference table row                 → remove
├── §2.9 "Public API & Legacy Wrappers" — Scheduler bullet → remove
├── §3.7 "Public API Stability" — Scheduler bullet   → remove
├── §4 Project Structure tree — scheduler.py line    → remove
└── §2.2 last paragraph ("scheduler.py ... consume it") → drop scheduler.py

docs/knowledge-graph.xml
├── <M-SCHEDULER> element                             → remove
└── 2 CrossLink entries referencing M-SCHEDULER       → remove

openspec/specs/package-facades/spec.md
├── "Outside-layer-set exemptions" list               → drop yascheduler.scheduler
├── R2 "Composition root imports use layer facades" scenario → drop scheduler mention
├── "Extended facade contents" (CloudProvisionerImpl, CloudAdapter, Orchestrator, submit_task) → drop scheduler as consumer in prose; keep yascheduler.di
└── "Documented private-symbol carve-outs" — scheduler.py mention → reduce to di.py only
```

## Cross-module data flow after change

```
daemonize CLI entry
   │
   ├── _get_logger()       ← inlined, was scheduler.get_logger
   ├── Config.from_config_parser()
   └── make_daemon(config, logger)  ← composition root
            │
            └── Orchestrator.start()
```

No new cross-module edges. The `daemonize → scheduler` edge is removed; the
inlined logger setup is local to `daemonize.py`.

## Open questions

None remaining after decisions:
1. `get_logger` → inline in `daemonize.py` as `_get_logger`. **DECIDED.**
2. `Scheduler` not public API. **DECIDED.**
