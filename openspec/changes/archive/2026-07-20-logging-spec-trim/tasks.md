## Common rules for every code-touching task

Every code-touching task below obeys these invariants. They exist because a
prior attempt at this change was discarded specifically for violating them.

- **GRACE fields are a closed set.** Allowed fields: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No invented fields. Specifically: no `SHALL NOT:`
  pseudo-field, no `EFFECTS:`, no `EXAMPLES:`, no `NOTES:`, no `RAISES:`,
  no free-form labels. The spec's removed `SHALL NOT` sentences do NOT become
  a `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating
  the positive contract, or a `RATIONALE` Q/A if the rationale is the
  valuable part.
- **`RATIONALE` is Q/A format only**, answering "why is this entity shaped
  this way?". It is NOT a junk drawer for arbitrary prose, NOT a place to
  restate `PURPOSE`, NOT a place to dump the trimmed spec text verbatim. One
  Q and one A per item; multi-item allowed when there are distinct reasons.
- **`PURPOSE` answers WHY, not WHAT.** "Format log records" is WHAT and
  fails. "Let developers observe internal execution flow at DEBUG level
  while keeping production output clean" is WHY and passes. If the existing
  `PURPOSE` already answers WHY, leave it — do not churn for churn's sake.
- **Every existing `CLASS_*` / `FUNC_*` / `METHOD_*` region must continue to
  enclose the FULL entity after enrichment.** For a class: the
  `class`/`@dataclass(...)` line, the docstring, every method, every field,
  through the trailing blank line before the next region marker. For a
  function: the decorator (if any), the `def`/`async def` line, the entire
  body, the trailing blank line. A region that closes before its entity
  ends (e.g. wrapping only the contract comment block) is a defect. The
  contract comment block (`# PURPOSE:`, `# INVARIANTS:`, etc.) sits
  INSIDE the region, ABOVE the entity's first line; the `# region` marker
  opens the block, the contract fields follow, then the entity, then
  `# endregion`. Nesting is allowed: `METHOD_*` and inner `BLOCK_*` regions
  live INSIDE the enclosing `CLASS_*` region; the `CLASS_*` `# endregion`
  comes after the last nested `# endregion`. In
  `yascheduler/shared/log.py`, `CLASS_LogFormatter` already correctly wraps
  its nested `METHOD_format` region — the enrichment must NOT change those
  marker positions.
- **Comment-only diff.** No code logic, signature, decorator choice, docstring
  semantics, or import changes. Edits are contract-field enrichment inside
  the existing `MODULE_CONTRACT`, `CLASS_LogFormatter`, and `METHOD_format`
  marker blocks. No `# region`/`# endregion` marker is added, removed, or
  moved. Module docstrings (the first `"""..."""` after `# endregion MODULE_CONTRACT`)
  are NOT touched.
- **Scope boundary.** This change touches ONLY `yascheduler/shared/log.py`.
  Other modules are out of scope: `yascheduler/entrypoints/cli/daemon_common.py`
  already carries the relevant `FUNC_configure_logger.INVARIANTS` entry
  "Both handlers share a single LogFormatter instance." that absorbs the
  relocated "no per-handler format variants" language; do NOT touch it.
  Test files (`tests/unit/test_log.py`, `tests/unit/test_log_scope_discipline.py`)
  are out of trim scope.

## 1. Apply the logging spec delta

- [x] 1.1 Apply the 2 MODIFIED requirements from `openspec/changes/logging-spec-trim/specs/logging/spec.md`
  to `openspec/specs/logging/spec.md`, replacing each original requirement
  block in place. Preserve requirement header text exactly (whitespace-
  insensitive match) so OpenSpec recognizes the MODIFIED operation. Headers
  to match (in spec order): `Module-local stdlib logger binding`,
  `LogFormatter renders trace and user-facing records distinctly`.
- [x] 1.2 Confirm the trimmed main spec contains zero invented `SHALL NOT`
  enumerations of absent code. Specifically gone: `Package modules SHALL
  NOT use a project factory or wrapper`, `no nested sentinel dict such as
  extra={"trace": {...}}, and no project-defined wrapper function`,
  `The package SHALL NOT provide a YaLogger subclass ... or a get_logger(...)
  factory`, `The package SHALL NOT use logging.setLoggerClass`,
  `the project SHALL NOT maintain per-handler format variants`,
  `the formatter SHALL NOT additionally filter or transform these keys`.
  Confirm every observable behavioral scenario (`#### Scenario:` count) is
  preserved: pre 12 → post 12. Confirm the 4 rationale pieces enumerated in
  `proposal.md` Why § 2 are gone from the spec body (the `stdlib merges
  extra into the record via __dict__.update` explanation; the `stdlib
  logging.getLogger(__name__) is statically typed to return logging.Logger
  with no reclass needed` justification; the `so that the set auto-adapts
  to the running Python version (e.g. taskName added in 3.12) without a
  hardcoded list` trailing clause; the `The structured key=value rendering
  SHALL be deterministic so that log-driven tests can rely on stable field
  ordering` restatement's `so that ...` tail — the deterministic ordering
  SHALL stays, only the rationale tail goes).
- [x] 1.3 `openspec validate --all --json` passes (exit 0). The change
  validates AND the trimmed main spec validates AND no other spec
  regresses.

## 2. yascheduler/shared/log.py — enrich MODULE_CONTRACT, CLASS_LogFormatter

The existing `MODULE_CONTRACT`, `CLASS_LogFormatter`, and `METHOD_format`
regions are kept in place; only the contract comment fields inside those
regions are enriched. No `# region`/`# endregion` marker is added,
removed, or moved. Only defined GRACE fields are used; every `PURPOSE`
already present answers WHY — leave it.

- [x] 2.1 Enrich the existing `MODULE_CONTRACT` in
  `yascheduler/shared/log.py`: keep `PURPOSE` as-is (current text "Make
  internal trace flow observable via structured DEBUG logs without
  polluting user-facing output." answers WHY — do NOT touch). Keep `SCOPE`
  as-is (already accurate). Keep `KEYWORDS` as-is. Add `INVARIANTS`
  capturing the project-wide module-local-logger conventions that left the
  spec body:
  - every module under `yascheduler/` binds its module-level logger via
    `logging.getLogger(__name__)` directly — no project factory, no
    wrapper function invoked at the binding site;
  - no `YaLogger` subclass of `logging.Logger`, no `get_logger(...)`
    factory reclassing the cached `logging.Logger` instance, and no
    `logging.setLoggerClass` call exists in the package;
  - every `extra={...}` callsite uses flat user-supplied keys — no nested
    sentinel container such as `extra={"trace": {...}}`;
  - every `extra={...}` callsite uses keys that do NOT collide with native
    `LogRecord` attribute names (enforced by the static guard in
    `tests/unit/test_log_scope_discipline.py`).
  Add `RATIONALE` Q/A:
  - Q1: why does every module bind via `logging.getLogger(__name__)`
    instead of a project factory such as `get_logger(__name__)`? A1:
    `logging.getLogger(__name__)` is statically typed to return
    `logging.Logger` and caches by name; a project factory that subclasses
    it (e.g. `YaLogger`) would fight stdlib's cache (a `setLoggerClass`
    call retroactively reclasses only loggers created after it, not the
    already-cached ones), and any wrapper is just a forwarding layer over
    the same cached object — stdlib binding is the only path that stays
    type-stable and cache-correct;
  - Q2: why does the static guard reject `extra` keys that collide with
    native `LogRecord` attributes? A2: stdlib merges `extra` into the
    `LogRecord` via `__dict__.update`, silently overwriting reserved keys
    (`name`, `msg`, `funcName`, `levelname`, `lineno`, `module`, …); a
    colliding key is silent corruption of the record's own metadata, so
    the guard turns it into a static failure rather than a runtime
    surprise in formatted output.
- [x] 2.2 Enrich the existing `CLASS_LogFormatter` region in
  `yascheduler/shared/log.py`: keep `PURPOSE` as-is (current text "Let
  developers observe internal execution flow at DEBUG level while keeping
  production output clean." answers WHY — do NOT touch). Add `INVARIANTS`
  capturing the formatter-output contracts that left the spec body:
  - trace fields are exactly the record attributes that are not members of
    the native `LogRecord` set — no additional filtering, transformation,
    or key whitelist is applied;
  - trace field rendering is alphabetical by key (deterministic) so
    log-driven tests can assert exact output;
  - one `LogFormatter` instance serves both handlers configured by
    `configure_logger` — no per-handler format variant exists.
  Add `RATIONALE` Q/A:
  - Q1: why is `_NATIVE_KEYS` derived by introspecting a freshly
    constructed `logging.LogRecord` instance at import time instead of
    maintaining a literal list? A1: stdlib grows the native attribute set
    over time (e.g. `taskName` was added in 3.12); introspection at import
    time auto-adapts to the running Python version, while a literal list
    would silently miss a new attribute and misclassify it as a trace
    field;
  - Q2: why is `_PACKAGE` derived from this module's `__name__` top
    segment instead of a hardcoded literal? A2: both the shortname strip
    and the in-package gate share the same prefix; deriving it from the
    module's own name avoids drift if the package is ever renamed or
    re-vendored, and avoids a class of bugs where one usage is updated and
    the other is forgotten.
- [x] 2.3 Leave the existing `METHOD_format` region untouched. Its current
  `PURPOSE` ("Route log records to trace or user-facing format based on
  the extra-diff discriminator.") already answers WHY; the three branches
  (`_is_trace`, `_format_trace`, `_format_user`) are private and out of
  markup scope per the proportional rule. No enrichment needed.
- [x] 2.4 Verify `uv run ruff check yascheduler/shared/log.py` and
  `uv run ruff format --check yascheduler/shared/log.py` pass;
  `uv run pytest -m unit tests/unit/test_log.py tests/unit/test_log_scope_discipline.py`
  is green.

## 3. End-to-end verify

- [x] 3.1 Manual scan: every `# region MODULE_CONTRACT`, `CLASS_*`,
  `METHOD_*`, and `BLOCK_*` in `yascheduler/shared/log.py` has a paired
  `# endregion` and continues to wrap its full entity after enrichment.
  `CLASS_LogFormatter` still encloses the `class LogFormatter(logging.Formatter):`
  line, the docstring, `_is_trace`, `_format_trace`, `_format_user`, and
  the nested `METHOD_format` region; the `CLASS_*` `# endregion` still
  comes after the `METHOD_*` `# endregion`. No orphaned trailing code
  outside any region; no region closes before its entity ends; no marker
  was added, removed, or moved.
- [x] 3.2 Manual scan: no invented GRACE field names anywhere in
  `yascheduler/shared/log.py` — only `PURPOSE` / `SCOPE` / `INVARIANTS` /
  `USECASES` / `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` /
  `ENSURES`. Specifically, NO `SHALL NOT:` field, NO `RAISES:` field, NO
  `EFFECTS:` field, NO `EXAMPLES:` field, NO `NOTES:` field anywhere.
- [x] 3.3 Manual scan: every `PURPOSE` field in
  `yascheduler/shared/log.py` answers WHY, not WHAT. Spot-check
  `MODULE_CONTRACT`, `CLASS_LogFormatter`, and `METHOD_format`. Where the
  existing `PURPOSE` already answers WHY (all three do), it was left
  unchanged.
- [x] 3.4 Manual scan: every `RATIONALE` field is in Q/A format
  ("Q: ... A: ..."). No `RATIONALE` block contains free-form prose that
  should be in `PURPOSE` / `INVARIANTS` / `SCOPE`. Specifically:
  - the "no factory, no wrapper" narrative lives as Q1/A1 in
    `MODULE_CONTRACT.RATIONALE`;
  - the `__dict__.update` no-collision narrative lives as Q2/A2 in
    `MODULE_CONTRACT.RATIONALE`;
  - the introspection-derived `_NATIVE_KEYS` narrative lives as Q1/A1 in
    `CLASS_LogFormatter.RATIONALE`;
  - the module-name-derived `_PACKAGE` narrative lives as Q2/A2 in
    `CLASS_LogFormatter.RATIONALE`.
- [x] 3.5 `openspec validate --all --json` passes (exit 0); the trimmed
  `logging` spec validates AND the change `logging-spec-trim` validates
  AND no other spec regresses (the pre-existing
  `engine-config-parsing-spec-trim` invalid state, if still present, is
  unrelated to this change and out of scope).
- [x] 3.6 `uv run pytest -m unit` — all unit tests pass (no behavior
  changed; the existing 12 scenarios in `tests/unit/test_log.py` and
  `tests/unit/test_log_scope_discipline.py` already assert them).
- [x] 3.7 `uv run ruff check .` and `uv run ruff format --check .` pass
  on all changed files.
- [x] 3.8 `uv run lint-imports` passes (no new imports introduced;
  markup-only edits).
- [x] 3.9 Confirm no public-surface change: no CLI command,
  console_script, INI config key, DB schema, public API, or log-format
  change in the diff. The diff is comment-field enrichment inside the
  existing `MODULE_CONTRACT`/`CLASS_LogFormatter` regions in
  `yascheduler/shared/log.py` + spec text trim only.
