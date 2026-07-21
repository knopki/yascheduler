## Why

GRACE-lite's `[Module][function][BLOCK] kv` markers were intended for DEBUG-only trace logs consumed by log-driven tests. They have leaked into user-facing INFO/WARN/ERROR output, making daemon logs ugly and noisy for operators. The markers also frequently diverge from the real code location because `[Module]` and `[function]` are hand-written ad-hoc strings (six different ontologies coexist: class name, use-case name, module path, platform, provider, ad-hoc label) and are never validated against the knowledge graph. Finally, the structured `key=value` payload is hand-assembled at every callsite via positional `%s` templates, which is cumbersome, error-prone, and inconsistent.

## What Changes

- Introduce a `YaLogger(logging.Logger)` subclass exposing a single new `trace(block, /, **fields)` method that emits a DEBUG record carrying structured fields, and a `get_logger(name) -> YaLogger` factory in `yascheduler/shared/log.py` that all package modules SHALL use for logger binding. The factory applies the `yascheduler.` namespace prefix and reclasses the cached logger instance to `YaLogger` so static type checkers see the correct type without `cast` or `type: ignore`. The project SHALL NOT use `logging.setLoggerClass`: it mutates process-global state (third-party loggers) and, because typeshed declares `logging.getLogger(...) -> logging.Logger`, leaves every `log.trace(...)` callsite a static type error. **BREAKING** for any consumer parsing current `[Module][function][BLOCK] kv` DEBUG strings.
- Canonicalize logger names to namespaced M-IDs (`yascheduler.M-APPLICATION-ALLOCATE`, produced by `get_logger("M-APPLICATION-ALLOCATE")`), replacing the six ad-hoc `[Module]` ontologies. **BREAKING**: logger names change; downstream grep/parse patterns keyed on old names break.
- Introduce a formatter that renders grace trace records with the M-ID, the auto-captured function name, the block marker, and the structured fields — and renders user-facing records as plain narrative (level, logger, message) with no markers. Wire it into `configure_logger` for both stderr and file handlers. **BREAKING**: runtime log output format changes for both trace and user-facing streams.
- Split the WARN/ERROR emits that are simultaneously user-facing and test-targeted into a `trace()` DEBUG record (test target) plus a clean narrative WARN/ERROR record (user target). These are the 5 emits currently asserted by unit/e2e tests via substring matching on the marker.
- Clean up the remaining non-test-targeted WARN/ERROR emits to pure narrative without markers. No `trace()` double is added for these.
- Convert the DEBUG-only marker emits across `application/` and `infra/` from hand-assembled `[Module][function][BLOCK] kv` strings to `log.trace("BLOCK", **fields)` calls.
- Migrate the log-driven test assertions from `marker in record.getMessage()` substring matching to structured field access on the captured records.
- Add guard unit tests enforcing trace-only DEBUG emits (no raw `.debug(` calls in the package) and M-ID validity (every namespaced M-ID logger literal references a real `<M-*>` tag in the knowledge graph).
- Update the GRACE-lite Logging & Verification contract in `AGENTS.md` to mandate `log.trace("BLOCK", **fields)` instead of hand-assembled `logging.debug("[Module][function][BLOCK] msg", extra={...})`.
- Register the new logging module in `docs/knowledge-graph.xml`.

## Capabilities

### New Capabilities
- `grace-logging`: the `YaLogger` subclass with `trace(block, /, **fields)`, the `get_logger(name) -> YaLogger` factory (namespace prefixing plus `YaLogger` reclassing, replacing `setLoggerClass`), the formatter contract (trace records carry M-ID + auto-captured function name + block marker + structured fields; user-facing records are plain narrative), the M-ID-namespaced logger name convention, and the guard-test discipline enforcing trace-only DEBUG emits, M-ID validity, and factory-only logger binding.

### Modified Capabilities
- `e2e-testing`: the `log_records` fixture and log-driven assertions shift from substring matching on `record.getMessage()` to structured field access on the captured records. Scenarios referencing `[AllocateTask][allocate_task][CLOUD_DONE]` and `[deallocate_node][CLOUD_DELETE]` are rewritten to assert on the block marker and payload fields exposed by trace records.
- `cli`: `configure_logger` gains the `LogFormatter` wired onto both stderr and file handlers; the function's observable output format changes.
- `orchestrator`: requirements referencing `CONNECT_RETRY_STATIC`, `_print_stats/ERROR`, `CONSUMER_ERROR`, and `PRODUCER_ERROR` logs are updated to reflect the split into a `trace()` DEBUG record (test target) and a narrative WARN/ERROR record (user target).

## Impact

- **New code**: a new shared logging module (`YaLogger`, `LogFormatter`, `get_logger`).
- **Wiring**: `yascheduler/shared/log.py` (factory), `configure_logger` in `daemon_common.py` (formatter wiring). The package `__init__.py` no longer performs any logger-class registration side effect.
- **Callsite rewrites**: marker-bearing emits across `yascheduler/application/` and `yascheduler/infra/` (allocate_task, orchestrator, webhook, cloud/manager, ssh/session, ssh/repository, ssh/platform, persistence/postgres_schema, persistence/postgres_migrations, cloud/provider_selection, ssh/operations/occupancy).
- **Test updates**: the e2e and unit tests that currently grep `getMessage()` for marker substrings (`test_full_cycle.py`, `test_hetzner_live.py`, `test_allocate_task_node_pairing.py`, `test_orchestrator_consumer_resilience.py`, `test_orchestrator_producer_resilience.py`), plus the new guard tests in `tests/unit/`.
- **Contract docs**: `AGENTS.md` (GRACE-lite Logging & Verification block), `docs/knowledge-graph.xml` (new module entry; M-ID logger names must match existing `<path>` mappings).
- **OpenSpec specs**: `openspec/specs/e2e-testing/spec.md`, `openspec/specs/cli/spec.md`, `openspec/specs/orchestrator/spec.md`.
- **No new runtime dependencies.** No DB schema changes. No CLI surface changes (the six entry points and `Yascheduler` public API are untouched).

### Non-Goals

- Does not introduce JSON/structlog/loguru or any third-party structured-logging library.
- Does not add per-handler format variants (stderr vs file use the same formatter).
- Does not introduce a whitelist of permitted structured-field names.
- Does not add `trace()` doubles for WARN/ERROR logs that are not test-targeted.
- Does not change the set of emitted severities (no new log levels, no routing/filtering).
- Does not alter the knowledge-graph M-ID scheme beyond requiring logger names to reference existing M-IDs.
- Does not phase or stage the migration — single big-bang change.