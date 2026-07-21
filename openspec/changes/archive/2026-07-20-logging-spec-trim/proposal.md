## Why

`openspec/specs/logging/spec.md` (146 lines, 2 requirements, 12 scenarios) interleaves
the actual SHALL requirements with two content kinds that GRACE assigns to
code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 6 instances
   enumerating absent code or non-existent code paths dressed up as normative
   requirements:
   - `Package modules SHALL NOT use a project factory or wrapper for
     module-level binding` — there is no project factory or wrapper in the
     committed package.
   - `no nested sentinel dict such as extra={"trace": {...}}, and no
     project-defined wrapper function` — neither exists in the package.
   - `The package SHALL NOT provide a YaLogger subclass of logging.Logger or a
     get_logger(...) factory reclassing the cached logging.Logger instance` —
     no such class or factory exists.
   - `The package SHALL NOT use logging.setLoggerClass` — the call does not
     exist in the package.
   - `the project SHALL NOT maintain per-handler format variants` — no
     per-handler variant exists; `FUNC_configure_logger` already installs a
     single `LogFormatter` instance on both handlers.
   - `the formatter SHALL NOT additionally filter or transform these keys` —
     no filter or transform exists in `LogFormatter._format_trace`; the
     passthrough is the contract.

   Every one is already asserted by a positive behavioral scenario
   (`module logger is bound via logging.getLogger(__name__)`,
   `structured DEBUG trace uses flat extra keys`,
   `single formatter serves both handlers`) or describes a non-existent code
   path dressed up as a normative requirement. The negative prose is drift
   bait — a future reader cannot tell whether the prohibition guards real
   code or merely documents absence.

2. **Design rationale living in the spec body** — four distinct pieces:
   - the `stdlib merges extra into the record via __dict__.update, silently
     overwriting reserved keys (e.g. name, msg, funcName, levelname, lineno,
     module)` explanation on the no-collision rule (this answers *why the
     static guard is necessary*, not *what the rule is*);
   - the `stdlib logging.getLogger(__name__) is statically typed to return
     logging.Logger with no reclass needed` justification for forbidding a
     subclass factory (this answers *why no factory exists*);
   - the `so that the set auto-adapts to the running Python version (e.g.
     taskName added in 3.12) without a hardcoded list` trailing clause on
     the introspection rule (this answers *why the set is derived by
     introspection*, not *what the rule is*);
   - the `The structured key=value rendering SHALL be deterministic so that
     log-driven tests can rely on stable field ordering` restatement, whose
     `so that ...` tail is rationale for the already-stated alphabetical-sort
     contract.

   Every piece answers *why the code is shaped this way* — they belong in
   `RATIONALE` / `INVARIANTS` on the owning entity, not in spec.

In parallel, the code under `yascheduler/shared/log.py` carries a
`MODULE_CONTRACT` and a `CLASS_LogFormatter` region that hold `PURPOSE` only.
The rationale and invariants that should accompany the code —
why every module binds via `logging.getLogger(__name__)` instead of a
factory, why the static guard against colliding `extra` keys exists, why
`_NATIVE_KEYS` is derived by introspection rather than a literal list, why
the formatter does no filtering or transformation of trace fields — are
absent from the regions because they currently sit in the spec.

## What Changes

- **MODIFIED `logging`**: rewrite both requirements to carry only behavioral
  contracts (SHALL statements + Gherkin scenarios). Remove the 6 invented
  `SHALL NOT` enumerations of absent code and the 4 design-rationale pieces
  listed above. Every observable behavioral scenario (12) survives unchanged.
  No requirement is added, removed, merged, or split; both requirement
  headers stay identical so OpenSpec recognizes the MODIFIED operation.
- Enrich existing `MODULE_CONTRACT`, `CLASS_LogFormatter`, and `METHOD_format`
  regions in `yascheduler/shared/log.py` with the rationale/invariants that
  leaves the spec, each in its correct GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
    The existing `MODULE_CONTRACT.PURPOSE` ("Make internal trace flow
    observable via structured DEBUG logs without polluting user-facing
    output.") and `CLASS_LogFormatter.PURPOSE` ("Let developers observe
    internal execution flow at DEBUG level while keeping production output
    clean.") already answer WHY — leave them.
  - `INVARIANTS` carries conditions/contracts that always hold (every
    `yascheduler/` module binds `logger = logging.getLogger(__name__)`
    directly with no project factory or wrapper; no `YaLogger` subclass,
    no `get_logger(...)` factory, no `logging.setLoggerClass` call exists in
    the package; no `extra={"trace": {...}}` nested sentinel — `extra` is
    always flat user keys; `extra` keys never collide with native
    `LogRecord` attributes; trace fields are exactly the record attributes
    that are not members of the native `LogRecord` set — no additional
    filtering or transformation; one `LogFormatter` instance serves both
    handlers — no per-handler format variant).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way
    (why every module binds via `logging.getLogger(__name__)` instead of a
    project factory; why the static guard against colliding `extra` keys is
    necessary; why `_NATIVE_KEYS` is derived by introspecting a freshly
    constructed `logging.LogRecord` instead of maintaining a literal list;
    why `_PACKAGE` is derived from the module's own `__name__` top segment
    instead of a hardcoded literal).
  - `SCOPE` is already accurate on the existing `MODULE_CONTRACT` — leave it.
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  free-form labels. The spec's removed `SHALL NOT` sentences do NOT become a
  `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating
  the positive contract, or a `RATIONALE` Q/A if the rationale is the
  valuable part.
- The existing `CLASS_LogFormatter` region in `yascheduler/shared/log.py`
  already encloses the FULL class body (the `class LogFormatter(logging.Formatter):`
  line, the docstring, `_is_trace`, `_format_trace`, `_format_user`, the
  nested `METHOD_format` region, and the trailing blank line). The
  `MODULE_CONTRACT` already encloses the module docstring + comment block.
  No `# region` / `# endregion` marker is added, removed, or moved — only
  the contract comment fields inside the existing regions are enriched.
  Comment-only diff.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `logging`: requirements slimmed to SHALL statements and behavior scenarios;
  invented `SHALL NOT` negative-space language and design rationale relocated
  out of the spec text and into GRACE code contracts on
  `yascheduler/shared/log.py`. No logging behavior, scenario, format,
  handler-wiring contract, public API, or static-guard contract is added,
  removed, or changed.

## Impact

- **Specs**: `openspec/specs/logging/spec.md` rewritten — every requirement
  trimmed to behavioral SHALL + scenarios; pre/post scenario count MUST
  remain 12 → 12. `openspec validate --all --json` must still pass after the
  change.
- **Code (markup only, no logic)**:
  - `yascheduler/shared/log.py` — enrich `MODULE_CONTRACT` with `INVARIANTS`
    (project-wide module-local-logger conventions) + `RATIONALE` (why
    `logging.getLogger(__name__)` not a factory; why the no-collision guard
    exists); enrich `CLASS_LogFormatter` with `INVARIANTS` (no filtering of
    trace fields; one formatter serves both handlers) + `RATIONALE` (why
    introspection-derived `_NATIVE_KEYS`; why module-name-derived
    `_PACKAGE`). Comment-only diff. No `# region`/`# endregion` marker is
    added, removed, or moved; no code logic, signature, decorator, docstring
    semantics, or import changes.
- **Tests**: no change. The 12 existing scenarios in the trimmed spec remain
  the acceptance criteria; the 8 existing unit tests in
  `tests/unit/test_log.py` plus the static-guard tests in
  `tests/unit/test_log_scope_discipline.py` already assert them. A passing
  `uv run pytest -m unit` run after the change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config key,
  DB schema, public API, or log-format change in the diff. The diff is
  comment-field enrichment + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `logging` spec. Other
  specs (`testing-unit`, `cli`, `orchestrator`, `cloud`, etc.) are
  explicitly out of scope. Follows the pattern set by
  `cli-spec-trim`, `cloud-spec-trim`, `config-value-objects-spec-trim`,
  `db-migrations-spec-trim`, `dependency-injection-spec-trim`, and
  `e2e-testing-spec-trim`.
- **Non-goals**:
  - No change to any logging behavior, scenario, log-format string, handler
    wiring, public API, or static-guard contract.
  - No spec split; both trimmed requirements remain in the `logging`
    capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No markup additions to `yascheduler/entrypoints/cli/daemon_common.py` —
    `FUNC_configure_logger` already carries the relevant `INVARIANTS`
    entry "Both handlers share a single LogFormatter instance."; that
    invariant already covers the relocated "no per-handler format variants"
    negative-space language, so the file is untouched.
  - No rewrite of `yascheduler/shared/log.py` formatting logic; only the
    contract comment fields inside the existing `MODULE_CONTRACT`,
    `CLASS_LogFormatter`, and `METHOD_format` regions are enriched.
