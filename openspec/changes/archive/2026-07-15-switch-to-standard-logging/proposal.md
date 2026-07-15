## Why

The `reform-grace-logging` change introduced a `YaLogger(logging.Logger)`
subclass with a custom `.trace(block, /, **fields)` method, plus a
`get_logger(name)` factory that reclasses the cached `Logger` instance's
`__class__` to `YaLogger` so static type checkers accept `.trace(...)` callsites.
This machinery exists to emit a DEBUG record carrying a block marker and
structured fields — something the stdlib already supports directly via
`logger.debug(msg, extra={...})`.

The abstraction is not earning its keep:

1. **Custom class for a stdlib capability.** `logging.Logger.debug(msg,
   extra=...)` already merges `extra` keys into the `LogRecord`. The `YaLogger`
   subclass, the `.trace()` method, and the `get_logger` factory exist only to
   repackage this as a project-specific call shape.

2. **The `__class__` reclass is a type-checker workaround.** Because
   `logging.getLogger` is statically typed to return `logging.Logger`,
   `get_logger` reclasses the returned object to `YaLogger` at runtime so
   `log.trace(...)` type-checks. The project then maintains an AST guard
   (`test_no_setloggerclass_in_yascheduler`) forbidding the stdlib
   `setLoggerClass` alternative — guard machinery exists to defend a workaround.

3. **Raw `.debug()` is forbidden by a guard.** `test_no_raw_debug_calls_in_yascheduler`
   rejects every `logger.debug(...)` callsite in the package, forcing all DEBUG
   emission through `.trace()`. With stdlib `debug(..., extra=...)` as the
   trace path, this guard and its friction disappear.

4. **M-ID logger names decouple logs from module paths.** Loggers are bound as
   `get_logger("M-APPLICATION-ORCHESTRATOR")`, producing the runtime name
   `yascheduler.M-APPLICATION-ORCHESTRATOR`. The M-ID is a knowledge-graph
   coordinate, not the module's import path; an operator reading logs cannot
   map a line back to a source file without the graph. stdlib
   `logging.getLogger(__name__)` gives this provenance for free and stays
   correct through module renames.

## What Changes

- Remove the `YaLogger` class and the `get_logger` factory from
  `yascheduler/shared/log.py`. The module SHALL export only `LogFormatter`.

- `LogFormatter` SHALL discriminate trace records from regular records by:
  (a) level is `DEBUG`, AND (b) the record carries user-supplied attributes
  beyond the native `LogRecord` attribute set, AND (c) the record's logger
  name belongs to this package. The native attribute set SHALL be derived once
  at import time from a reference `LogRecord` instance (auto-adapting to the
  Python version, e.g. `taskName` in 3.12). The package prefix used both for
  the shortname strip and the in-package gate SHALL be derived from this
  module's own `__name__` top segment — no hardcoded `"yascheduler"` literal.

- Trace records SHALL render as `[module][funcName]:lineno msg k=v k=v`
  (fields sorted alphabetically for deterministic output; `module` is the
  logger name minus the package prefix). Regular records SHALL render
  unchanged as `LEVEL name: message`.

- All package modules SHALL bind `logger = logging.getLogger(__name__)`. Every
  existing `get_logger("M-...")` callsite SHALL be replaced. M-ID-based logger
  names are retired from the runtime.

- All structured DEBUG tracing SHALL migrate from `logger.trace("BLOCK", k=v)`
  to `logger.debug("BLOCK", extra={"k": v})`. The former block marker becomes
  the debug message text.

- `yascheduler/shared/__init__.py` SHALL stop re-exporting `YaLogger` and
  `get_logger`.

- The injected `log: logging.Logger | None` parameter is removed from every
  `infra/ssh/platform/{linux,windows}.py` platform function and from the
  `SetupNodeCallable` protocol; each platform module binds its own
  `logger = logging.getLogger(__name__)` and emits directly. Vestigial DEBUG
  traces that carry no `extra` fields and are not asserted in any test are
  dropped (the former block markers rendered as opaque regular DEBUG lines
  under the new discriminator); where logging becomes unused the module logger
  binding/import is removed too.

- Rewrite `tests/unit/test_log.py` around `LogFormatter` and the extra-diff
  discriminator (no `YaLogger`-specific tests).

- Rewrite `tests/unit/test_log_scope_discipline.py`: remove
  `test_logger_names_are_real_m_ids`,
  `test_no_raw_debug_calls_in_yascheduler`, and
  `test_no_setloggerclass_in_yascheduler` (and their synthetic-violation
  meta-tests). Keep `test_no_injected_logger_in_collaborator_constructors`.
  Add a guard that every `extra={...}` literal in the package uses keys that
  do NOT collide with native `LogRecord` attribute names (stdlib silently
  overwrites reserved keys via `__dict__.update`).

- E2E and unit log-assertion helpers (`_assert_allocation_logs`,
  `_assert_cloud_done_log`, `_assert_cloud_delete_log`, node-pairing trace
  assertions) SHALL migrate from `record.block` / `record.fields` structured
  attributes to `record.getMessage()` plus the extra-diff against native keys.

- Update `openspec/specs/logging/spec.md` to the new contract.

- Update `docs/knowledge-graph.xml` `M-LOGGING` annotations: drop `fn-trace`,
  `class-YaLogger`, `export-get_logger`; keep `class-LogFormatter`.

- Update `AGENTS.md` GRACE-lite logging subsections (logger binding and record
  contract for tests) to the stdlib binding and the extra-diff discriminator.

## Capabilities

### Modified Capabilities

- `logging`: the project SHALL use stdlib `logging.getLogger(__name__)` for
  module-level logger binding. The `YaLogger` subclass and `get_logger`
  factory are removed. `LogFormatter` discriminates trace records by DEBUG
  level plus user-supplied extra attributes (diffed against a dynamically
  derived native key set) plus an in-package logger-name gate. Trace records
  render `[module][funcName]:lineno msg k=v`; regular records render as before.

- `testing-unit`: the logging-discipline guard set is reduced and refocused.
  The M-ID-validity, raw-`.debug()`, and `setLoggerClass` guards are removed.
  The collaborator-constructor injection guard is retained. A new guard
  forbids `extra={...}` keys that collide with native `LogRecord` attributes.

## Impact

- **BREAKING (internal)**: `YaLogger` and `get_logger` are removed from the
  `yascheduler.shared` public surface. No external public-API impact: the
  `Yascheduler` class, the six CLI entry points, the INI config format, the DB
  schema, and the AiiDA scheduler entrypoint are untouched.

- **Source files**: `yascheduler/shared/log.py`, `yascheduler/shared/__init__.py`,
  and the ~18 package modules that currently bind via `get_logger("M-...")`.

- **Callsite volume**: ~48 `get_logger(...)` bindings and ~90 `.trace(...)`
  callsites are mechanically migrated.

- **Tests**: `tests/unit/test_log.py` (full rewrite),
  `tests/unit/test_log_scope_discipline.py` (guard set reduced + one guard
  added), e2e log-assertion helpers in `tests/e2e/test_full_cycle.py`,
  `tests/e2e/test_hetzner_live.py`, and
  `tests/unit/test_allocate_task_node_pairing.py`.

- **Docs/spec**: `openspec/specs/logging/spec.md`,
  `docs/knowledge-graph.xml`, `AGENTS.md`.

- No new runtime dependencies. No DB schema changes. No CLI surface changes.

### Non-Goals

- Does NOT change the rendering of regular INFO/WARN/ERROR logs
  (`LEVEL name: message` stays).

- Does NOT add a wrapper function (e.g. `trace(logger, msg, **kw)`); callsites
  use `logger.debug(msg, extra={...})` directly.

- Does NOT introduce a nested sentinel dict in `extra` (e.g.
  `extra={"trace": {...}}`); `extra` keys are flat user fields.

- Does NOT change the `log_records` e2e fixture mechanism (handler attached to
  the `"yascheduler"` parent logger at DEBUG; descendant propagation remains
  functional because `logging.getLogger(__name__)` still produces
  `yascheduler.*` names).

- Does NOT change the set of emitted log messages or their levels; only the
  binding/emission mechanism and the trace discriminator change.

- Does NOT remove `log` from the `Migration` base class
  (`infra/persistence/migration_base.py`); that is the migration-author API
  contract, a separate concern carried forward from
  `switch-to-module-local-loggers`.

- Does NOT phase or stage the migration — single big-bang change, consistent
  with the prior `reform-grace-logging` and `switch-to-module-local-loggers`
  approach.
