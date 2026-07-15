## Context

The `reform-grace-logging` change introduced three coupled abstractions in
`yascheduler/shared/log.py`:

1. `YaLogger(logging.Logger)` — a subclass exposing `.trace(block, /, **fields)`.
2. `get_logger(name) -> YaLogger` — a factory that prepends the `yascheduler.`
   namespace prefix and reclasses the cached `logging.Logger` instance's
   `__class__` to `YaLogger` so static type checkers accept `.trace(...)` calls.
3. `LogFormatter` — a `logging.Formatter` with two rendering branches keyed on
   the presence of a `record.fields` attribute (set by `.trace()`).

Three AST-based guard tests in `tests/unit/test_log_scope_discipline.py`
defend this design: no raw `.debug(` calls, no `logging.getLogger` module-level
bindings outside `log.py`, no `logging.setLoggerClass`. A fourth guard forbids
the `log` parameter in collaborator `__init__` (from
`switch-to-module-local-loggers`).

Today's state:

- ~48 callsites bind `logger = get_logger("M-...")` using a knowledge-graph
  M-ID as the runtime logger name, producing names like
  `yascheduler.M-APPLICATION-ORCHESTRATOR`.
- ~90 callsites emit `logger.trace("BLOCK", k=v)`, which internally calls
  `self.debug(block, extra={"block": block, "fields": fields})`.
- E2E and unit log assertions read the structured attributes
  `record.block` / `record.fields` set by `.trace()`.
- The `log_records` e2e fixture attaches a handler to the `"yascheduler"`
  parent logger at DEBUG and relies on descendant propagation.
- `LogFormatter` is wired onto both the stderr `StreamHandler` and the file
  `FileHandler` in `daemon_common.configure_logger`, which configures the
  ROOT logger — so third-party loggers (`asyncssh`, `backoff`, `pg8000`,
  `aiohttp`) flow through the same formatter.

The coupling of logger name to a knowledge-graph M-ID decouples log output
from the module import path: an operator cannot map
`yascheduler.M-APPLICATION-ORCHESTRATOR` back to a source file without
consulting `docs/knowledge-graph.xml`, and the mapping goes stale on module
rename.

## Goals / Non-Goals

**Goals:**

- Replace the `YaLogger` subclass and `.trace()` method with stdlib
  `logging.getLogger(__name__)` plus `logger.debug(msg, extra={...})`.
- Remove the `get_logger` factory and the `__class__` reclass.
- Replace the `record.fields`-presence discriminator with a DEBUG-level +
  extra-diff discriminator: a record is a trace record iff it is DEBUG-level,
  carries user attributes beyond the native `LogRecord` attribute set, and its
  logger name belongs to the project package.
- Derive the native attribute set by introspection (auto-adapting to the
  Python version) and derive the package prefix from the formatter module's
  own `__name__` top segment — no hardcoded literals.
- Retire M-ID-based logger names in favor of module import paths.
- Reduce the logging-discipline guard set and add a guard against
  `extra`-key collisions with native `LogRecord` attributes.

**Non-Goals:**

- No change to the rendering of regular INFO/WARN/ERROR logs
  (`LEVEL name: message`).
- No wrapper function (e.g. `trace(logger, msg, **kw)`).
- No nested sentinel dict in `extra` (e.g. `extra={"trace": {...}}`).
- No change to the `log_records` e2e fixture mechanism.
- No change to the set of emitted messages or their levels.
- No change to the `Migration` base class `log` attribute.
- No phased rollout — single big-bang change.

## Decisions

### Decision 1: Dynamic introspection for the native LogRecord attribute set

**Choice.** The native attribute set used by the discriminator is computed
once at import time from a freshly constructed `logging.LogRecord` instance:

```
_NATIVE_KEYS = frozenset(
    logging.LogRecord("ref", logging.DEBUG, "<ref>", 0, "", (), None).__dict__.keys()
)
```

The trace discriminator is then: `record.levelno == DEBUG` AND
`set(record.__dict__) - _NATIVE_KEYS` is non-empty AND the logger name is
in-package.

**Alternatives considered.**

- *Hardcoded literal set of ~21 names.* Rejected: breaks silently on
  Python version drift. `taskName` was added to `LogRecord` in 3.12; a
  hardcoded list missing it would cause any `extra` diff to spuriously
  include `taskName` as a user field on every record, or worse, mask a real
  collision if a future stdlib attribute name matched a user field name.
  The introspection approach auto-includes version-specific attributes.
- *Sentinel key in `extra`* (e.g. `extra={"_trace": True, ...}`). Rejected:
  requires either a wrapper function (a non-goal) or a non-standard callsite
  shape on every trace emission, and consumes one reserved `extra` name.

**Why introspection.** The `LogRecord.__dict__` key set is stable across
the project's supported Python range (>=3.9), is part of stdlib's de facto
public surface, and self-documents the contract: "trace fields are exactly
the attributes stdlib did not put there."

### Decision 2: Package prefix derived from `__name__`

**Choice.** The package prefix — used both to strip the shortname in trace
output and to gate the in-package check — is the top segment of the
formatter module's own `__name__`:

```
_PACKAGE = __name__.split(".", 1)[0]   # "yascheduler" when imported as yascheduler.shared.log
```

The in-package gate is: `record.name == _PACKAGE or record.name.startswith(_PACKAGE + ".")`.

The shortname strip is: `record.name.removeprefix(_PACKAGE + ".")`.

**Alternatives considered.**

- *Hardcoded `"yascheduler"` literal.* Rejected: violates the explicit
  "no hardcoded package literal" constraint, and would drift if the package
  were ever renamed or vendored under a different top-level name.
- *Top segment from a caller-supplied parameter.* Rejected: the formatter is
  constructed once in `configure_logger` and wired onto root handlers; no
  caller is positioned to supply the package name, and parameterizing would
  add ceremony for no benefit.

**Why `__name__`.** The formatter module lives inside the package it
describes. Its `__name__` therefore encodes the package identity without a
literal, and stays correct through package rename or vendoring.

### Decision 3: Discriminator requires all three conditions (DEBUG + extra + in-package)

**Choice.** A record is rendered as a trace record iff ALL THREE hold:

1. `record.levelno == logging.DEBUG`, AND
2. `set(record.__dict__) - _NATIVE_KEYS` is non-empty (user-supplied extra
   attributes exist), AND
3. `record.name` is in-package per Decision 2's gate.

Any record failing any condition renders as regular narrative.

**Why all three.**

- DEBUG-without-extra (e.g. `logger.debug("progress: ok")`) is a regular
  debug message, not a trace — condition 2 excludes it. This honors the
  non-goal "regular logs are not changed."
- Out-of-package DEBUG-with-extra (e.g. `asyncssh` or `backoff` emitting
  debug records carrying attributes through the shared root handler) is NOT
  a project trace — condition 3 excludes it. Without this gate, the
  formatter would color third-party debug noise as project traces whenever
  a third party happened to use `extra=`.
- The level gate (condition 1) keeps INFO/WARN/ERROR always regular.

### Decision 4: Trace output layout `[module][funcName]:lineno msg sorted k=v`

**Choice.** Trace records render as:

```
[<shortname>][<funcName>]:<lineno> <message> <k=v> <k=v>
```

where `<shortname>` is `record.name` with the package prefix removed,
`<funcName>` is stdlib's auto-captured caller function name, `<lineno>` is
the source line, and the `key=value` pairs are sorted alphabetically by key
using `repr()` for values, joined by single spaces.

Regular records render unchanged: `<LEVEL> <name>: <message>`.

**Why this layout.** The message (formerly the trace block marker) remains
the grep anchor; the module path restores provenance that M-ID names lost;
`funcName:lineno` locates the callsite without a knowledge-graph lookup;
sorted fields keep log-driven tests deterministic. `repr()` preserves types
distinguishable in output (e.g. `"10.0.0.1"` vs `10`).

### Decision 5: No `record.shortname` attribute mutation

**Choice.** The formatter computes the shortname on the fly during
`format()` and does NOT set `record.shortname`. The prior spec's
`SIDE_EFFECTS: Sets record.shortname` guarantee is retired.

**Why.** The shortname is a rendering concern, not a record contract.
Tests that need the module portion derive it from `record.name` directly.
Avoids mutating `LogRecord` instances (which can be shared across handlers).

### Decision 6: Mechanical callsite migration via AST transform

**Choice.** The ~48 `get_logger("M-...")` bindings and ~90 `.trace(...)`
callsites are migrated mechanically, in two passes:

- Binding pass: in each of the ~18 affected modules, replace
  `from yascheduler.shared import get_logger` with `import logging` (if not
  already present) and `logger = get_logger("M-...")` with
  `logger = logging.getLogger(__name__)`.
- Trace pass: rewrite `logger.trace(BLOCK, k=v, ...)` to
  `logger.debug(BLOCK, extra={"k": v, ...})`. The positional `BLOCK` becomes
  the message; keyword arguments become the `extra` dict.

**Why AST, not sed.** Multi-line trace calls exist (e.g.
`postgres_migrations._record_py_tracker`'s `logger.trace("TRACKER_RECORD",
exc=exc,)` split across lines). An AST transform handles line spanning,
trailing commas, and nested calls correctly; sed does not. The transform is
a one-shot migration tool, not a retained project artifact.

### Decision 7: Reduced guard set + new extra-collision guard

**Choice.** `tests/unit/test_log_scope_discipline.py` is reduced to two
guards:

1. Retained: `test_no_injected_logger_in_collaborator_constructors`
   (unchanged — seven collaborator classes reject `log` in `__init__`).
2. Added: `test_no_extra_key_collision_with_native_attrs` — AST-scan every
   `extra={...}` literal in `yascheduler/` and fail if any key intersects
   the native `LogRecord` attribute set (derived by the same introspection
   as Decision 1, or imported from `shared/log.py`).

Removed guards (and their synthetic-violation meta-tests):
`test_no_raw_debug_calls_in_yascheduler`, `test_logger_names_are_real_m_ids`,
`test_no_setloggerclass_in_yascheduler`.

**Why.** With stdlib `debug(..., extra=...)` as the sanctioned trace path,
the raw-`.debug()`, M-ID-validity, and `setLoggerClass` guards defend
retired abstractions. The extra-collision guard defends the one remaining
silent-failure mode: stdlib merges `extra` via `__dict__.update` and
silently overwrites reserved keys (`name`, `msg`, `funcName`, `levelname`,
`lineno`, `module`, ...).

## Risks / Trade-offs

- **Stdlib `LogRecord` attribute set drifts across Python versions** → the
  introspection in Decision 1 absorbs the drift automatically. A future
  Python adding an attribute simply enlarges `_NATIVE_KEYS`; a removal
  shrinks it. No code change required on version bump.
- **An `extra` key silently collides with a native attribute** → stdlib's
  `__dict__.update` overwrites the native value without error, producing
  corrupted records (e.g. `extra={"name": ...}` would rewrite the logger
  name on the record). Mitigation: the new static guard (Decision 7)
  rejects any colliding `extra` literal at test time.
- **Third-party DEBUG-with-extra records render incorrectly without the
  in-package gate** → the root handler sees `asyncssh`/`backoff`/`pg8000`/
  `aiohttp` records. Mitigation: the in-package gate (Decision 3, condition
  3) excludes them from trace rendering; they render as regular narrative.
- **Loss of M-ID ↔ logger-name linkage in the knowledge graph** → operators
  and tools that grepped logs by M-ID lose that anchor. Mitigation: the
  module import path in the logger name is a strictly better provenance
  anchor (maps directly to source, survives renames via `__name__`). The
  knowledge graph's `M-LOGGING` entry is updated to drop M-ID-in-name
  annotations.
- **E2E log-assertion helpers must change** → `_assert_allocation_logs`,
  `_assert_cloud_done_log`, `_assert_cloud_delete_log`, and the node-pairing
  trace assertions currently read `record.block` / `record.fields`.
  Mitigation: they migrate to `record.getMessage()` (the former block
  marker is now the message) plus the extra-diff for field values. The
  `log_records` fixture itself is unchanged.
- **Big-bang migration touches ~138 callsites** → a partial migration would
  leave mixed `YaLogger`/stdlib code. Mitigation: single atomic change,
  no compatibility shim (per AGENTS.md), full test suite
  (`uv run pytest -m unit,integration,e2e`) gates merge.

## Migration Plan

Single big-bang change, no compatibility shim. Order:

1. Rewrite `yascheduler/shared/log.py`: remove `YaLogger`, `get_logger`;
   retain only `LogFormatter` with `_NATIVE_KEYS` (introspection) and
   `_PACKAGE` (from `__name__`); update `MODULE_CONTRACT` / `MODULE_MAP` /
   `CHANGE_SUMMARY`.
2. Update `yascheduler/shared/__init__.py`: drop re-exports of `YaLogger`
   and `get_logger`; retain `Self`, `Unpack`, `StrEnum`, `LogFormatter`.
3. Migrate ~48 logger bindings across ~18 modules to
   `logging.getLogger(__name__)` (AST or per-file edit).
4. Migrate ~90 `.trace(BLOCK, **kw)` callsites to
   `logger.debug(BLOCK, extra={**kw})` (AST transform; handle multi-line
   calls).
5. Rewrite `tests/unit/test_log.py` around `LogFormatter` and the
   extra-diff discriminator.
6. Reduce `tests/unit/test_log_scope_discipline.py` to the two retained
   guards; remove the three retired guards and their meta-tests; add the
   extra-collision guard.
7. Migrate e2e and unit log-assertion helpers off `record.block` /
   `record.fields` onto `getMessage()` + extra-diff.
8. Update `openspec/specs/logging/spec.md` and
   `openspec/specs/testing-unit/spec.md` to the archived delta content.
9. Update `docs/knowledge-graph.xml` `M-LOGGING` annotations: drop
   `fn-trace`, `class-YaLogger`, `export-get_logger`; retain
   `class-LogFormatter`.
10. Update `AGENTS.md` GRACE-lite logging subsections (logger binding and
    record contract for tests).
11. Verify: `uv run pytest -m unit,integration,e2e`;
    `openspec validate --all --json`;
    `python3 scripts/grace_check.py`.

**Rollback.** `git revert` of the change commit(s). No runtime state, no
schema, no config format affected — rollback is purely source-level.

## Open Questions

None. All design decisions trace to confirmed user constraints (stdlib
`getLogger(__name__)`, DEBUG+extra discriminator, no wrapper, no nested
sentinel, regular format unchanged, package prefix from `__name__`).
