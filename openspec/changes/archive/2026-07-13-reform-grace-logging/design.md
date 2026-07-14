## Context

The project follows GRACE-lite, a code methodology that uses semantic markup (anchors, contracts) plus structured logging for log-driven testing. Today the logging contract lives entirely in prose inside `AGENTS.md` and is implemented ad-hoc at every callsite: each debug-trace callsite hand-assembles a string of the form `[Module][function][BLOCK] key=value` and emits it via `logging.debug(...)`.

This produced three concrete problems, validated against the codebase:

1. **Marker leakage into user-facing output.** The `[Module][function][BLOCK]` triple was intended for DEBUG-only trace logs consumed by tests. It has leaked into INFO/WARN/ERROR emits (7 callsites in `orchestrator.py`, `webhook.py`, `cloud/manager.py`), so daemon operators see ugly, noisy lines instead of readable prose.
2. **Divergent `[Module]` identifiers.** Six different ontologies coexist for the `[Module]` slot — class name (`CloudProvisionerImpl`), use-case name (`AllocateTask`), module path (`postgres_migrations`), platform (`Linux`), provider (`Azure`), ad-hoc labels. None is validated against the knowledge graph, so the identifiers drift from the real code location.
3. **Hand-assembled `key=value` payload.** Every callsite writes its own positional `%s` template and matches it with positional args. This is verbose, error-prone, and inconsistent; renaming a field means hunting across many callsites.

The trace surface today spans ~30 callsites across `yascheduler/application/` and `yascheduler/infra/`, and 9 unit/e2e test files assert on trace markers via substring matching on `record.getMessage()` or `record.message`. The existing `log_records` e2e fixture attaches a handler to the `"yascheduler"` logger and relies on dot-hierarchy propagation from descendant loggers.

## Goals / Non-Goals

**Goals:**
- Cleanly separate grace-debug traces (for log-driven tests) from user-facing narrative (INFO/WARN/ERROR), so operators see readable prose and tests assert on structured fields.
- Centralize the trace-emit mechanism in one logger method (`trace`) so callsites stop hand-assembling marker strings and `key=value` payloads.
- Canonicalize logger names to namespaced M-IDs (`yascheduler.M-...`) drawn from `docs/knowledge-graph.xml`, eliminating the six ad-hoc ontologies and making divergence fail a guard test.
- Render trace records with the canonical `[M-ID][funcName][BLOCK] kv` layout (auto-captured `funcName`) and user-facing records as plain narrative, via a single `LogFormatter` wired in `configure_logger`.
- Keep the existing `log_records` fixture functional without rewriting its handler attachment (propagation through the `yascheduler.` namespace prefix).
- Enforce the contract statically via two guard unit tests: no raw `.debug(` calls in the package, and every M-ID logger literal references a real `<M-*>` tag.

**Non-Goals:**
- No third-party structured-logging library (no JSON/structlog/loguru). stdlib `logging` only.
- No per-handler format variants (stderr and file share one `LogFormatter`).
- No whitelist of permitted structured-field names; collisions with reserved `LogRecord` attributes surface as Python `KeyError` at emit time and are the caller's responsibility.
- No `trace()` doubles for WARN/ERROR logs that are not test-targeted (only the 5 test-targeted ones split).
- No new log severities, no routing/filtering, no color handling.
- No changes to the knowledge-graph M-ID scheme beyond requiring logger names to reference existing M-IDs.
- No phased rollout — single big-bang change.

## Decisions

### Decision 1: `YaLogger(logging.Logger)` subclass with a single `trace` method

**Choice.** Define `YaLogger` as a subclass of `logging.Logger` adding one method:

```
trace(block: str, /, **fields) -> None
```

that emits a DEBUG record carrying the block marker and the structured fields as a dedicated attribute on the `LogRecord` (not as a hand-assembled message string). The block marker and the structured-fields dict are exposed as programmatic attributes so consumers (formatter, tests) read them directly without parsing rendered text.

Inherited methods (`debug`, `info`, `warning`, `error`, `exception`, `critical`) stay unchanged and are the only path for user-facing narrative — they carry no markers and no structured fields.

**Rationale.** The standard Python convention is `log = logging.getLogger(name)` at module top. A logger subclass preserves that convention: `trace` becomes a method on the logger, no extra import or wrapper object at every callsite. This beats two alternatives considered:

- *LogScope wrapper class* — holds a `logging.Logger` and re-exposes methods. Rejected: not a logger (breaks `isinstance` checks, propagates differently under `logging`), and most methods are pure delegation boilerplate existing only to host one new method. "So primitive it begs the question of why it exists."
- *Free function `trace(log, block, **fields)`* — modules still call `logging.getLogger(...)` and pass it positionally to `trace(...)`. Rejected: loses the "each module binds a named logger with the method on it" property; `trace(log, ...)` is more verbose than `log.trace(...)` and pushes the logger as a positional argument at every callsite.

The subclass keeps the trace mechanism *on the logger itself*, which is where the project convention already places module-level logger binding.

### Decision 2: `get_logger(name) -> YaLogger` factory in `yascheduler/shared/log.py`

**Choice.** Provide a single factory function in the shared logging module:

```
def get_logger(name: str) -> YaLogger:
    logger = logging.getLogger(f"yascheduler.{name}")
    logger.__class__ = YaLogger
    return logger
```

All package modules SHALL bind their module-level logger via `from yascheduler.shared import get_logger` → `log = get_logger("M-APPLICATION-ALLOCATE")`. Direct `logging.getLogger(...)` calls inside `yascheduler/` SHALL NOT be used for module-level logger binding; the guard test (Decision 7) enforces this.

**Rationale — why a factory, not `setLoggerClass`.** An earlier draft of this decision chose `logging.setLoggerClass(YaLogger)` executed in `yascheduler/__init__.py`. That approach is rejected because typeshed declares `logging.getLogger(name) -> logging.Logger`, so every static type checker (zuban, mypy, pyright) reports `"Logger" has no attribute "trace"` at each of the ~76 `log.trace(...)` callsites. The runtime class swap is invisible to the type system. Workarounds (`cast(YaLogger, ...)`, per-callsite `# type: ignore[attr-defined]`) either reintroduce unchecked lies or scatter 76 ignores across the package, defeating static analysis.

The factory sidesteps the problem at the source: its return type is `YaLogger`, so `log.trace(...)` is statically valid with no casts and no ignores. The `logger.__class__ = YaLogger` mutation inside the factory is the mechanism that makes the *runtime* class match the *static* type — without it, the returned logger would still be a plain `logging.Logger` at runtime and `trace()` would raise `AttributeError`.

**Rationale — `__class__` reclassing is safe and idempotent.** `logging.getLogger(name)` caches instances in `Logger.manager.loggerDict` by name and wires the parent hierarchy before returning. The first call for a given name constructs a plain `logging.Logger`; the factory then reclasses that same cached object to `YaLogger`. Subsequent `getLogger(name)` calls (from the factory or from anywhere else in the process) return the same object — already a `YaLogger` — so the `__class__` assignment is idempotent. Reclassing after construction is safe because `YaLogger` adds one method and no new instance state; the `logging.Logger.__init__` layout is preserved.

**Rationale — namespace prefix centralized.** The `yascheduler.` prefix lives in the factory, not at each callsite. This serves two purposes: (a) it guarantees propagation to the `"yascheduler"` parent logger that the `log_records` e2e fixture attaches to (Decision 3), and (b) a future namespace change is a one-line edit in the factory rather than a sweep across ~20 callsites.

**Tradeoffs accepted.**
- The factory adds one import (`from yascheduler.shared import get_logger`) at each module top, replacing `import logging` + `logging.getLogger(...)`. Modules that use `logging` constants (`logging.INFO`, `logging.ERROR`) keep the `import logging` line alongside.
- `__class__` mutation is unusual and would be a code smell in most contexts. Here it is localized to one function, idempotent, and the cheapest mechanism that satisfies both the static type contract and the runtime requirement. The alternative — manually registering a `YaLogger` in `Logger.manager.loggerDict` and replicating `getLogger`'s parent-wiring and `PlaceHolder` logic — duplicates stdlib internals for no benefit.
- The factory does NOT mutate third-party loggers. `asyncssh`, `aiohttp`, `backoff` loggers remain plain `logging.Logger` instances regardless of import order, because only `get_logger(...)` callers are reclassed.

### Decision 3: Namespaced M-ID logger names (`yascheduler.<M-ID>`)

**Choice.** Every package logger is created via `get_logger("M-APPLICATION-ALLOCATE")` — the factory prepends the `yascheduler.` prefix (Decision 2), producing the canonical name `yascheduler.M-APPLICATION-ALLOCATE`. The `[Module]` slot in trace output renders the M-ID portion (e.g. `M-APPLICATION-ALLOCATE`).

**Rationale.** Two requirements converge here:

- *Propagation.* The `log_records` e2e fixture attaches its handler to the `"yascheduler"` logger. Capturing descendant records requires the descendant logger name to start with `yascheduler.` so Python's dot-hierarchy propagation delivers records upward. The factory guarantees this prefix centrally; a callsite cannot accidentally drop it. Dropping the prefix (bare `M-APPLICATION-ALLOCATE`) would orphan the logger from the fixture and force a fixture rewrite (handler on root + filter by name prefix) — extra complexity for no semantic gain.
- *Canonical identity.* The six ad-hoc `[Module]` ontologies are replaced by a single source of truth: the M-ID. The guard test (Decision 7) validates every `get_logger(...)` argument against the knowledge graph, so fabricated identifiers fail CI rather than drifting silently.

`funcName` is *not* taken from the logger name — it is auto-captured by `trace()` via `stacklevel` (Decision 4) and rendered by the formatter (Decision 5). The M-ID is the *module* coordinate; `funcName` is the *function* coordinate; they are independent.

### Decision 4: `trace()` carries block and fields via `extra`, auto-captures `funcName` via `stacklevel`

**Choice.** `trace()` calls `self.debug(block, extra={"block": block, "fields": fields}, stacklevel=2)`. The block marker is exposed two ways: as `record.msg` (so `record.getMessage()` returns it) and as `record.block` (a dedicated attribute for direct programmatic test access). The structured fields live under a single dedicated key `"fields"` on `record.__dict__` (i.e. `record.fields`), not spread across the record namespace.

The `extra` dict therefore carries exactly two reserved-for-trace keys: `"block"` and `"fields"`. The caller never writes these — `trace()` injects them. Caller-provided keyword arguments go into the `fields` dict, never directly into `extra`.

**Rationale — fields under one key.** An earlier sketch put each field directly into `extra` (e.g. `extra={"block": block, "task_id": tid, "ip": ip}`). This forced the formatter to distinguish caller-provided fields from the many reserved `LogRecord` attributes (`name`, `module`, `funcName`, `lineno`, `created`, `thread`, ...) by maintaining a `_RESERVED` frozenset and filtering `record.__dict__`. That is a maintenance hazard: every Python version that adds a new `LogRecord` attribute silently leaks it into the rendered kv output unless the frozenset is updated.

Putting fields under one key (`record.fields`) eliminates the filtering: the formatter reads `record.fields` and nothing else. Collisions with `LogRecord` attributes become impossible because the caller never writes to the record's top-level namespace — only `"fields"` does, and `"fields"` is not a reserved attribute.

**Rationale — `stacklevel=2`.** `logging.Logger.debug` uses `findCaller` to populate `funcName`/`lineno`/`pathname`. With `stacklevel=1` (the default) the caller would be `trace()` itself; with `stacklevel=2`, `findCaller` skips `trace` and reports the callsite that invoked `log.trace(...)`. This makes `funcName` in trace output reflect the real function without any hand-written `[function]` string.

**Tradeoff accepted.** `trace()` is the only sanctioned DEBUG path (Decision 7 enforces this), so the `stacklevel=2` assumption holds. If someone calls `trace` through an additional wrapper, `funcName` would point at the wrapper — but the guard test forbids raw `.debug(` calls, and a wrapper around `trace` would itself need to pass a deeper `stacklevel`, which is a localized concern, not a contract issue.

### Decision 5: `LogFormatter` with two rendering branches keyed on `record.fields` presence

**Choice.** A single `LogFormatter(logging.Formatter)` renders two layouts:

- *Trace records* (those carrying `record.fields`): render the M-ID portion of `record.name` (stripped of the `yascheduler.` prefix), the auto-captured `record.funcName`, the block marker (`record.getMessage()` returns the block), and the structured fields rendered as deterministic `key=value` pairs. Field ordering is sorted alphabetically so log-driven tests can rely on stable rendering.
- *User-facing records* (no `record.fields`): render timestamp, level, logger name (shortened to the M-ID portion for grace loggers, full for others), and the message. No markers, no kv.

`LogFormatter` is wired onto both the `StreamHandler(sys.stderr)` and the `FileHandler` configured by `configure_logger`. One formatter instance, no per-handler variants.

**Rationale — single formatter.** A second formatter for the file handler would let the file carry richer context (e.g. `lineno`, `threadName`) while stderr stays compact. There is no present requirement for that — YAGNI. If a verbose file format is ever needed, a later change can introduce it; the single-formatter decision does not foreclose it.

**Rationale — deterministic kv ordering.** Tests assert on `record.fields` directly (Decision 6), not on rendered text, so kv ordering does not affect assertions. But human readers and `grep` benefit from stable ordering, and `sorted(fields.items())` is the cheapest deterministic choice.

### Decision 6: Tests assert on `record.fields` and the block, not on `getMessage()` substrings

**Choice.** The existing log-driven tests (9 files) switch from substring matching on `record.getMessage()` to structured access:

- *Block marker* — read via `r.getMessage()` (the block is passed as `msg` to `debug()`, so `getMessage()` returns it verbatim) or via a dedicated `record.block` attribute if the implementation exposes one. The contract is: the block is exposed as a programmatic attribute named `block` on the `LogRecord` (Decision 4 puts it into `extra` alongside `fields`), so tests read `r.block`.
- *Structured payload* — read via `r.fields` (the dedicated dict attribute from Decision 4).
- *Logger identity* — read via `r.name` (the M-ID-namespaced logger name).

Tests select records by `r.name == "yascheduler.M-..."` and assert on `r.block` and `r.fields`, not on rendered message substrings.

**Rationale.** Substring matching on rendered messages couples tests to the formatter's exact output — any reformatting breaks tests silently. Structured access decouples tests from rendering: the formatter can change layout, add timestamps, reorder kv, and tests stay green because they read attributes, not strings.

**Note.** The split points (Decision 8) are exactly the test-targeted user-facing markers, so the split produces a trace record the tests can switch onto without losing coverage. The DEBUG-only markers (ALLOCATED, CLOUD_DONE, CLOUD_DELETE) migrate to `trace()` and tests switch onto `r.block`/`r.fields`.

### Decision 7: Two guard unit tests enforce trace discipline and M-ID validity

**Choice.** Two static unit tests in `tests/unit/`:

1. `test_no_raw_debug_calls_in_yascheduler` — walk `yascheduler/**/*.py` via AST; fail on any `ast.Call` whose `func` is an attribute access named `debug` on a logger-like object (i.e. any `.debug(` call). All structured DEBUG tracing must go through `.trace()`. The shared logging module itself (`yascheduler/shared/log.py`) is exempt: `YaLogger.trace` calls `self.debug(...)` internally, which is the sanctioned implementation, not a contract violation. The AST walk scopes to `yascheduler/` only so third-party `.debug(` calls outside the package do not trip the guard.
2. `test_logger_names_are_real_m_ids` — walk the same tree; collect every `get_logger("M-...")` call (an `ast.Call` whose `func` is a name or attribute referencing `get_logger`, with a single string-literal argument); parse `docs/knowledge-graph.xml`; assert each literal matches a `<M-*>` tag name. The test additionally asserts that no `logging.getLogger(...)` call inside `yascheduler/` is used for module-level logger binding (the factory is the only sanctioned path), so a stray `logging.getLogger("yascheduler.M-...")` regress fails the guard.

Both run under `-m unit`, no external resources.

**Rationale.** The contract is only as strong as its enforcement. A convention in `AGENTS.md` that says "use `trace()`" will rot the moment someone writes `log.debug(...)` in a hurry; the AST guard makes that a CI failure. Same for fabricated M-IDs: without the guard, a typo like `M-APLICATION-ALLOCATE` would silently produce a logger that nothing captures and no test catches.

### Decision 8: Split the test-targeted user-facing emits into `trace()` + narrative

**Choice.** The emits that are simultaneously user-facing (INFO/WARN/ERROR) and test-targeted become two records: a `trace()` DEBUG record (the test target, carrying the block marker and structured fields) and a clean narrative record (the user target, carrying plain prose). The split points, identified by scanning the test suite for assertions on marker substrings:

| Callsite | Marker | Level | Test target (DEBUG) | User target |
|---|---|---|---|---|
| `webhook.py:110` | `RETRY` | warning | `log.trace("RETRY", url=url)` | `log.warning("webhook retry to %s", url)` |
| `abandon_node.py:59` | `CLOUD_DELETE_FAILED` | error | `log.trace("CLOUD_DELETE_FAILED", node_id=..., hostname=..., cloud=..., err=...)` | `log.error("cloud delete failed for node %s: %s", hostname, err)` |
| `abandon_node.py:86` | `AMBIGUOUS_TRACKER` | warning | `log.trace("AMBIGUOUS_TRACKER", node_id=..., hostname=..., count=...)` | `log.warning("ambiguous tracker: node %s has %d entries", hostname, count)` |
| `orchestrator.py:300` | `CONNECT_RETRY_STATIC` | warning | `log.trace("CONNECT_RETRY_STATIC", node_id=..., hostname=...)` | `log.warning("static node %s connect failed: %s", hostname, err)` |
| `orchestrator.py:316` | `CONNECT_RETRY` | warning | `log.trace("CONNECT_RETRY", node_id=..., hostname=...)` | `log.warning("cloud node %s connect failed: %s", hostname, err)` |
| `orchestrator.py:329` | `CONNECT_ABANDON` | error | `log.trace("CONNECT_ABANDON", node_id=..., hostname=...)` | `log.error("abandoning cloud node %s after grace exceeded", hostname)` |
| `orchestrator.py:345` | `ABANDON_FAILED` | error | `log.trace("ABANDON_FAILED", node_id=..., err=...)` | `log.error("abandon_node failed for node %s: %s", node_id, err)` |
| `orchestrator.py:630` | `CONSUMER_ERROR` | error | `log.trace("CONSUMER_ERROR", ...)` | `log.error(...)` |
| `orchestrator.py:664` | `PRODUCER_ERROR` | error | `log.trace("PRODUCER_ERROR", ...)` | `log.error(...)` |
| `orchestrator.py:249` | `ERROR` (stats context) | error | `log.trace("ERROR", context="stats", err=...)` | `log.error("stats print failed: %s", err)` |
| `ssh/repository.py:242` | `CPUs` | info | `log.trace("CPUS", hostname=..., ncpus=...)` | `log.info("connected to %s (%d CPUs)", hostname, ncpus)` |

The test asserts on the trace record's `record.block` and `record.fields`; the operator sees the narrative.

**Rationale — why split instead of just re-leveling.** These emits serve two audiences with incompatible needs: tests want a stable, parseable, grepable marker; operators want readable prose. One record cannot serve both without putting the marker into the prose (today's leak) or dropping the marker (losing the test hook). Two records, one per audience, is the clean separation.

**Rationale — why exactly these.** The principle is *test-targeted*: a `trace()` double is added exactly when a test already asserts on the marker. The 11 entries above are the complete set of user-facing markers for which a test assertion exists today. Non-test-targeted WARN/ERROR emits (Decision 9) get cleanup only, no double, per the Non-Goal "no `trace()` doubles for WARN/ERROR logs that are not test-targeted."

### Decision 9: Cleanup of non-test-targeted WARN/ERROR emits to pure narrative

**Choice.** The remaining marker-bearing WARN/ERROR emits that are NOT test-targeted — `CREATE_FAILED` (`cloud/manager.py:170`), `CLOUDS_STOP_FAILED` / `DISCONNECT_ALL_FAILED` / `HTTP_CLOSE_FAILED` (`orchestrator.py:803/810/818`), `[CloudProvisionerImpl] stop` (`manager.py:99`), `GIVEUP` (`webhook.py:86`) — lose their markers and become plain `warning(...)`/`error(...)`/`exception(...)` narrative. No `trace()` double is added.

**Rationale.** These are not asserted by any test (verified by scanning the test suite for marker substrings). Adding a `trace()` double "in case a future test wants it" violates YAGNI. The cleanup is the minimum work needed to remove the marker leak from user-facing output; a future test that needs a hook can add the double then.

### Decision 10: `configure_logger` wires `LogFormatter` on both handlers

**Choice.** `configure_logger` in `daemon_common.py` instantiates one `LogFormatter` and calls `setFormatter` on both the `StreamHandler(sys.stderr)` and the `FileHandler` (when present). The function's documented behavior is updated to note the formatter wiring; the `backoff`/`asyncssh` ERROR-level suppression and `captureWarnings(True)` behavior is unchanged.

**Rationale.** The formatter must be on a handler, not on the root logger (Python `logging` does not consult a logger-level formatter). Wiring it in `configure_logger` keeps all logging setup in the single existing seam — no new entry point, no scattered formatter instantiation.

## Risks / Trade-offs

- **`__class__` reclassing inside the factory** → Reclassing a cached `logging.Logger` instance to `YaLogger` is unusual. Mitigation: it is idempotent (subsequent `getLogger` returns the already-reclassed object), it adds no instance state, and it is localized to one function. Verified by the unit test (Decision 1's `test_trace_emits_block_and_fields` constructs a `YaLogger` via the factory and asserts `isinstance(_, YaLogger)`).

- **Static-typing correctness depends on the factory return type** → If a module bypasses `get_logger` and writes `log = logging.getLogger("yascheduler.M-...")` directly, zuban reports `"Logger" has no attribute "trace"` at that module's `log.trace(...)` callsite. Mitigation: the guard test (Decision 7, test 2) rejects any `logging.getLogger(...)` module-level binding inside `yascheduler/`, so the bypass is a CI failure, not silent drift.

- **`stacklevel=2` assumption** → `funcName` correctness depends on `trace()` being called directly from the function being traced, not through an extra wrapper. Mitigation: the guard test forbids raw `.debug(` calls, and any wrapper around `trace` is a localized change that can pass a deeper `stacklevel`. The contract is "callsite function name," not "the specific integer 2."

- **M-ID literal drift from knowledge graph** → If a module is renamed in the graph but not in the logger literal (or vice versa), the guard test fails. Mitigation: that is the *intended* behavior — the guard exists to make drift loud. The fix is to update both in the same change, which is cheap because the M-ID is the single source of truth.

- **Test migration from `getMessage()` to `record.block`/`record.fields`** → A test that still greps `getMessage()` after the change would pass against the old format and fail against the new. Mitigation: big-bang migration in one change (per Non-Goal); the 9 affected test files are enumerated across the spec deltas and Decision 8's split table covers every test-targeted marker. No test is left half-migrated.

- **`record.fields` attribute collision** → If a caller writes `log.trace("BLOCK", fields={...})`, the `fields` keyword collides with the `extra={"fields": ...}` slot. Mitigation: Python raises `TypeError: __init__() got multiple values for argument 'fields'` at emit time — a loud, immediate failure, not silent drift. This is the caller's responsibility per the Non-Goal "no whitelist of permitted structured-field names."

- **Single formatter for stderr and file** → Operators wanting a richer file format (with `lineno`, `threadName`) for post-mortem analysis cannot get it without a future change. Mitigation: the decision is reversible in a later change and does not foreclose a second formatter; YAGNI today.

- **Big-bang migration touches ~30 callsites + 9 test files at once** → A large diff is harder to review and riskier to land. Mitigation: the change is mechanical (callsite rewrites follow a 1:1 pattern: `[Module][fn][BLOCK] k=%s v=%s` → `log.trace("BLOCK", k=v)`); the guard tests catch any callsite missed; the e2e suite (`test_full_cycle.py`, `test_hetzner_live.py`) validates the end-to-end trace capture path. Phased rollout would leave the project half-migrated with two logging styles coexisting, which is worse than a single clean cutover.