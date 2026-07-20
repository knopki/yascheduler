## Common rules for every code-touching task

Every code-touching task below obeys these invariants. They exist because a
prior attempt at a similar change was discarded specifically for violating
them.

- **GRACE fields are a closed set.** Allowed fields: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No invented fields. Specifically: no `SHALL NOT:`
  pseudo-field, no `RAISES:`, no `EFFECTS:`, no `EXAMPLES:`, no `NOTES:`, no
  free-form labels. The spec's removed "not in `Engine.__post_init__`" sentence
  does NOT become a `SHALL NOT:` contract field — it becomes an `INVARIANTS`
  entry on `CLASS_Engine` stating the positive contract (plain frozen
  dataclass; no `__post_init__`; validation lives in the parser).
- **`RATIONALE` is Q/A format only**, answering "why is this entity shaped
  this way?". It is NOT a junk drawer for arbitrary prose, NOT a place to
  restate `PURPOSE`, NOT a place to dump the trimmed spec text. One Q and one
  A per item; multi-item allowed when there are distinct reasons.
- **`PURPOSE` answers WHY, not WHAT.** "Validate the spawn template" is WHAT
  and fails. "Reject malformed spawn templates at parse time so a misconfigured
  engine fails fast at config load instead of producing cryptic `KeyError`s
  during task spawn" is WHY and passes.
- **Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity.**
  For a function: the decorator (if any), the `def` line, the entire body, the
  trailing blank line before the next region marker. For a class: the
  `@dataclass(...)` decorator (if any), the `class` line, the docstring, every
  field, every `__init__` line, every `self.<attr>` assignment, through the
  trailing blank line before the next region marker. A region that closes
  before its entity ends (e.g. wrapping only the contract comment) is a
  defect. Nesting is allowed: `METHOD_*` and inner `BLOCK_*` regions live
  INSIDE the enclosing `CLASS_*`; the `CLASS_*` `# endregion` comes after the
  last nested `# endregion`.
- **Comment-only diff on the code side.** No code logic, signature,
  decorator choice, docstring semantics, or import changes. Edits are
  `# region` / `# endregion` marker insertion and contract-field enrichment
  inside the marker block. The existing nested
  `# region BLOCK_validate_engine` inside `FUNC_parse_engine_section` stays
  as-is (it is the inner non-trivial block and names the validator helpers).

## 1. Apply the engine-config-parsing spec delta

- [x] 1.1 Apply the single MODIFIED requirement from
  `openspec/changes/engine-config-parsing-spec-trim/specs/engine-config-parsing/spec.md`
  to `openspec/specs/engine-config-parsing/spec.md`, replacing the original
  `### Requirement: Engine INI parser functions` block in place. Preserve the
  requirement header text exactly (whitespace-insensitive match) so OpenSpec
  recognizes the MODIFIED operation.
- [x] 1.2 Confirm the trimmed main spec contains zero `not in
  Engine.__post_init__` / `SHALL NOT` / `shall not` instances in the
  requirement body and scenarios (the one enumerated in `proposal.md` Why § 1
  is gone). Confirm every observable behavioral scenario (`#### Scenario:`
  count) is preserved: pre 5 → post 5. Confirm the duplicated
  `engine_valid_fields` narrative paragraph (the one restating the scenario's
  include/exclude key list) is removed.
- [x] 1.3 `openspec validate --all --json` passes (exit 0). The change
  validates AND the trimmed main spec validates AND no other spec regresses
  (currently 20 specs + the in-flight changes including this one).

## 2. domain/engine.py — enrich existing CLASS_Engine

The existing `# region CLASS_Engine` ... `# endregion CLASS_Engine` block
(lines 64–94) already encloses the FULL class body — `@dataclass(frozen=True)`
decorator, `class Engine:` line, docstring, every dataclass field, and the
nested `METHOD_validate_inputs` region. The `# endregion CLASS_Engine` already
sits after the nested `# endregion METHOD_validate_inputs`. Do NOT move either
`# endregion`; the edit is comment-only enrichment inside the existing region
header. Only defined GRACE fields are used; `PURPOSE` answers WHY.

- [x] 2.1 Enrich the `CLASS_Engine` region header (currently `PURPOSE` only at
  line 65). Tighten the existing `PURPOSE` to WHY if slipped (current text
  "Specify a calculation engine's spawn command, platform support, and deploy
  artefacts so tasks can be matched to compatible machines and provisioned
  reproducibly." — WHY-flavored; keep). Add `INVARIANTS` capturing the
  layering contract that the removed spec sentence tried to enforce as
  negative-space: `@dataclass(frozen=True)` stdlib; no `__post_init__` —
  `Engine` is a plain frozen dataclass and carries no INI parsing or
  validation logic; all INI-time validation (spawn placeholders via
  `_check_spawn`, check-method presence via `_check_check_`, input/output
  file presence via `_check_at_least_one_elem`) lives in
  `yascheduler.entrypoints.config_parser.parse_engine_section` and its helper
  functions; `validate_inputs` (the one method on this class) is a runtime
  pre-deployment check against a task's extra payload, not an INI-time
  validator. The phrase "no `__post_init__`" stays inside `INVARIANTS` as a
  positive-contract statement of fact, NOT as a `SHALL NOT:` pseudo-field.
- [x] 2.2 Verify `uv run ruff check yascheduler/domain/engine.py` and
  `uv run ruff format --check yascheduler/domain/engine.py` pass;
  `uv run pytest -m unit tests/unit/test_domain_model.py
  tests/unit/test_config.py tests/unit/test_parse_engine_spawn_required.py`
  is green.

## 3. entrypoints/config_parser.py — enrich MODULE_CONTRACT

The existing `# region MODULE_CONTRACT` ... `# endregion MODULE_CONTRACT`
block (lines 2–6) already encloses the file-level contract. Do NOT move
either `# endregion`; the edit is comment-only enrichment inside the existing
region header. Only defined GRACE fields are used; `PURPOSE` answers WHY.

- [x] 3.1 Tighten the existing `MODULE_CONTRACT` `PURPOSE` to WHY if slipped.
  Current text: "Parse INI config files into frozen domain/infra configuration
  objects — the adapter between ConfigParser and the application's typed
  configuration model." — acceptable WHY (states the goal: be the adapter
  between ConfigParser and the typed model). Keep; do not bloat.
- [x] 3.2 Add `INVARIANTS` to the `MODULE_CONTRACT` capturing the layering
  contract: every domain/infra value object built here (`Engine`,
  `EngineRepository`, `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`,
  the four `ConfigCloud*` DTOs) is a frozen stdlib dataclass with no INI
  parsing methods on the DTO itself; all INI-time validation (spawn
  placeholders, check-method presence, input/output file presence,
  `jump_port` range, `max_nodes >= 0`, `idle_tolerance >= 1`, VastAI
  `disk_gb >= 1` / `min_vram_mb >= 1024` / `num_gpus >= 1` /
  `max_price_per_hr >= 0`) runs inside the per-section parser functions via
  the `_check_*` helpers, never in `__post_init__`. Phrase each line as a
  positive contract statement.
- [x] 3.3 Add `RATIONALE` Q/A to the `MODULE_CONTRACT` absorbing the
  layering-rationale half of the trimmed spec sentence. One Q/A item:
  - Q: Why does INI parsing live in `entrypoints/config_parser.py` while the
    typed value objects (`Engine`, `LocalSettings`, `RemoteDefaults`,
    `PostgresDbConfig`, `ConfigCloud*`) live in `yascheduler.domain` and
    `yascheduler.infra`?
  - A: Keeping the typed value objects in domain/infra lets use cases and the
    orchestrator depend on business types without importing the parser
    (the spec's "domain does not reference an entrypoints module" rule).
    `entrypoints/config_parser.py` is the sole adapter that knows about
    `ConfigParser`; it depends downward on the typed value objects, never the
    reverse. This keeps the dependency direction `entrypoints → domain` /
    `entrypoints → infra` per the hexagonal contract and prevents the domain
    from ever needing `configparser` at runtime.
- [x] 3.4 Verify `uv run ruff check yascheduler/entrypoints/config_parser.py`
  and `uv run ruff format --check yascheduler/entrypoints/config_parser.py`
  pass; `uv run pytest -m unit tests/unit/test_config.py` is green.

## 4. entrypoints/config_parser.py — wrap FUNC__check_spawn, FUNC__check_check_, FUNC__check_at_least_one_elem

The three engine-side validator helpers currently sit unwrapped under the
`MODULE_CONTRACT` (lines 44–65). They are the literal "parser-side validators"
the trimmed spec sentence refers to — wrap them so the
`parse_engine_section SHALL validate the section and raise ValueError`
requirement has a markup home. Each new region opens one line above the
`def` and closes one line below the trailing blank, enclosing the FULL
function per the Common rules. Only defined GRACE fields are used; every
`PURPOSE` answers WHY.

- [x] 4.1 Add `# region FUNC__check_spawn` ... `# endregion FUNC__check_spawn`
  enclosing the FULL function — the `def _check_spawn(engine: Engine, value:
  str) -> None:` line, the `try`/`except KeyError` body, the
  `raise ValueError(...)` line, and the trailing blank line (currently lines
  44–50). `PURPOSE` (WHY: reject malformed spawn templates at parse time so a
  misconfigured engine fails fast at config load instead of producing a
  cryptic `KeyError` during task spawn on a remote node).
  `INVARIANTS` (the only template placeholders accepted are `task_path`,
  `engine_path`, `ncpus` — any other `{name}` triggers `ValueError` whose
  message names the engine and the offending placeholder; uses
  `value.format(task_path="", engine_path="", ncpus="")` as the schema probe
  with all three legitimate keys blanked so an unknown key surfaces as
  `KeyError`; re-raises as `ValueError`, never lets `KeyError` escape).
- [x] 4.2 Add `# region FUNC__check_check_` ... `# endregion FUNC__check_check_`
  enclosing the FULL function — the `def _check_check_(engine: Engine) ->
  None:` line, the `if not engine.check_cmd and not engine.check_pname:`
  body, the `raise ValueError(...)` line, and the trailing blank line
  (currently lines 52–56). `PURPOSE` (WHY: enforce that every engine declares
  at least one liveness-check method so the daemon can detect task completion
  on a node — an engine with neither `check_cmd` nor `check_pname` is
  unusable and must fail at config load, not at first scheduling cycle).
  `INVARIANTS` (the function name carries the historical double underscore
  `_check_check_` — left as-is; raises `ValueError` whose message names the
  engine; performs no I/O).
- [x] 4.3 Add `# region FUNC__check_at_least_one_elem` ...
  `# endregion FUNC__check_at_least_one_elem` enclosing the FULL function —
  the `def _check_at_least_one_elem(engine: Engine, field_name: str, value:
  Sequence[object] | None) -> None:` line, the `if not value or len(value) <
  1:` body, the `raise ValueError(...)` line, and the trailing blank line
  (currently lines 58–66). `PURPOSE` (WHY: reject engines that ship no input
  files or no output files so a task cannot be queued for an engine that
  would have nothing to upload or download — a misconfigured engine fails at
  config load, not at task dispatch). `INVARIANTS` (`None` and empty
  sequence both trigger `ValueError`; message names the engine and the
  offending `field_name`; used for `input_files` and `output_files` from
  `BLOCK_validate_engine` inside `parse_engine_section`).
- [x] 4.4 Verify `uv run ruff check yascheduler/entrypoints/config_parser.py`
  and `uv run ruff format --check yascheduler/entrypoints/config_parser.py`
  pass; `uv run pytest -m unit tests/unit/test_config.py
  tests/unit/test_parse_engine_spawn_required.py` is green.

## 5. entrypoints/config_parser.py — enrich existing FUNC_engine_valid_fields

The existing `# region FUNC_engine_valid_fields` ...
`# endregion FUNC_engine_valid_fields` block (lines 77–92) already encloses
the FULL function. Do NOT move either `# endregion`; the edit is
comment-only enrichment inside the existing region header. Only defined GRACE
fields are used; `PURPOSE` answers WHY.

- [x] 5.1 Tighten the existing `FUNC_engine_valid_fields` `PURPOSE` to WHY if
  slipped. Current text: "Return valid INI keys for an [engine.*] section
  (dataclass fields + deploy aliases, excluding name and deployable)." — this
  is WHAT (describes the operation), not WHY. Replace with a WHY statement
  such as: "Tell the unknown-field warning which `[engine.*]` INI keys are
  legitimate so a typo in an engine section surfaces as a warning at config
  load instead of silently being dropped on the floor."
- [x] 5.2 Add `INVARIANTS` to `FUNC_engine_valid_fields` absorbing the
  include/exclude rule that the trimmed spec narrative restated. State the
  positive contract: returns one INI key per `dataclasses.fields(Engine)`
  entry except `name` (the engine name is parsed from the section title
  `[engine.<name>]`, not from a key) and `deployable` (the deployable tuple
  is built from the three deploy-alias keys, not read directly); appends the
  three deploy-alias keys `deploy_local_files`, `deploy_local_archive`,
  `deploy_remote_archive` because each maps to a `Deploy` strategy variant
  rather than to a top-level `Engine` field; auto-introspects via
  `dataclasses.fields(Engine)` so adding a field to the `Engine` dataclass
  auto-registers its INI key — no separate field-list maintenance. Phrase
  each line as a positive contract statement; do NOT use `SHALL NOT:`.
- [x] 5.3 Verify `uv run ruff check yascheduler/entrypoints/config_parser.py`
  and `uv run ruff format --check yascheduler/entrypoints/config_parser.py`
  pass; `uv run pytest -m unit tests/unit/test_config.py` is green.

## 6. entrypoints/config_parser.py — enrich existing FUNC_parse_engine_section

The existing `# region FUNC_parse_engine_section` ...
`# endregion FUNC_parse_engine_section` block (lines 95–150) already encloses
the FULL function — decorator-free `def parse_engine_section(...)`, docstring,
the inner `gettuple`, the deploy-strategy assembly, the `Engine(...)`
construction, the nested `# region BLOCK_validate_engine` ...
`# endregion BLOCK_validate_engine` (lines 141–146), and the `return engine`.
The `# endregion FUNC_parse_engine_section` already sits after the nested
`# endregion BLOCK_validate_engine`. Do NOT move either `# endregion`; the
edit is comment-only enrichment inside the existing region header. Only
defined GRACE fields are used; `PURPOSE` answers WHY.

- [x] 6.1 Tighten the existing `FUNC_parse_engine_section` `PURPOSE` to WHY if
  slipped. Current text: "Build a frozen Engine from a single [engine.*] INI
  section, validating spawn placeholders, check methods, and required file
  lists." — leans WHAT. Replace with a WHY statement such as: "Turn one INI
  `[engine.*]` section into a frozen `Engine` value object the orchestrator
  can match against task requirements, with every malformed config (unknown
  spawn placeholder, missing check method, empty input/output list, missing
  spawn) surfacing as `ValueError` at config load rather than as a cryptic
  failure during task scheduling."
- [x] 6.2 Add `REQUIRES` to `FUNC_parse_engine_section`: `sec` is a
  `SectionProxy` for a section whose name starts with `engine.` (the parser
  derives `name = sec.name[7:]`, i.e. strips the literal `engine.` prefix);
  `engines_dir` is the absolute base directory under which per-engine
  subdirectories live (composed as `engines_dir / name` for deploy-strategy
  path resolution).
- [x] 6.3 Add `ENSURES` to `FUNC_parse_engine_section`: on success, returns a
  frozen `Engine` whose `name` is the section suffix after `engine.`, whose
  `deployable` tuple is built by appending `LocalFilesDeploy`,
  `LocalArchiveDeploy`, `RemoteArchiveDeploy` in the INI-declaration order
  (`deploy_local_files` → `deploy_local_archive` → `deploy_remote_archive`),
  and whose remaining fields carry the section values (with `check_cmd_code`
  default `0`, `sleep_interval` default `10`); on malformed config (missing
  `spawn`, unknown spawn placeholder, missing `check_cmd` AND `check_pname`,
  empty `input_files`, empty `output_files`) raises `ValueError` naming the
  engine — validation runs HERE inside this function via the
  `BLOCK_validate_engine` calls to `_check_spawn`, `_check_check_`,
  `_check_at_least_one_elem`, never in `Engine.__post_init__` (which does not
  exist). Phrase as positive postcondition; do NOT use `SHALL NOT:`.
- [x] 6.4 Add `INVARIANTS` to `FUNC_parse_engine_section`: warns about unknown
  fields via `warn_unknown_fields(engine_valid_fields(), sec)` BEFORE
  constructing the `Engine` so typos surface even on otherwise-valid
  sections; `gettuple` is the local helper that splits whitespace-separated
  INI values into a stripped non-empty tuple (used for `input_files`,
  `output_files`, `platforms`, `platform_packages`, `deploy_local_files`);
  the three deploy aliases (`deploy_local_files`, `deploy_local_archive`,
  `deploy_remote_archive`) are NOT dataclass fields — they are parsed here
  into `Deploy` strategy tuples that land on `Engine.deployable`. Phrase each
  line as a positive contract statement.
- [x] 6.5 Verify `uv run ruff check yascheduler/entrypoints/config_parser.py`
  and `uv run ruff format --check yascheduler/entrypoints/config_parser.py`
  pass; `uv run pytest -m unit tests/unit/test_config.py
  tests/unit/test_parse_engine_spawn_required.py` is green.

## 7. entrypoints/config_parser.py — enrich existing FUNC_parse_engines

The existing `# region FUNC_parse_engines` ...
`# endregion FUNC_parse_engines` block (lines 153–165) already encloses the
FULL function. Do NOT move either `# endregion`; the edit is comment-only
enrichment inside the existing region header. Only defined GRACE fields are
used; `PURPOSE` answers WHY.

- [x] 7.1 Tighten the existing `FUNC_parse_engines` `PURPOSE` to WHY if
  slipped. Current text: "Parse all engine.* sections from an INI config into
  an EngineRepository." — leans WHAT. Replace with a WHY statement such as:
  "Collect every `[engine.*]` section in the INI into one frozen
  `EngineRepository` so the orchestrator and allocator have a single
  read-only registry to match task platforms against, built once at config
  load and never re-parsed."
- [x] 7.2 Add `ENSURES` to `FUNC_parse_engines`: returns an
  `EngineRepository` whose `data` maps each section suffix (the engine name)
  to the `Engine` returned by `parse_engine_section`; iterates only sections
  whose name starts with the literal `engine.` prefix (other sections are
  invisible); duplicate engine names cannot occur (`ConfigParser` enforces
  unique section names).
- [x] 7.3 Verify `uv run ruff check yascheduler/entrypoints/config_parser.py`
  and `uv run ruff format --check yascheduler/entrypoints/config_parser.py`
  pass; `uv run pytest -m unit tests/unit/test_config.py` is green.

## 8. End-to-end verify

- [x] 8.1 Manual scan: every `# region CLASS_*`, `FUNC_*`, `METHOD_*`,
  `BLOCK_*`, and `MODULE_CONTRACT` in the touched files
  (`yascheduler/domain/engine.py` and the engine-touched regions of
  `yascheduler/entrypoints/config_parser.py`) has a paired `# endregion` and
  wraps the entire entity. Specifically: the three new `FUNC__check_*`
  regions each enclose the FULL function body and the trailing blank line;
  no region closes before its entity ends; the nested
  `BLOCK_validate_engine` stays INSIDE the enclosing `FUNC_parse_engine_section`;
  the nested `METHOD_validate_inputs` stays INSIDE the enclosing
  `CLASS_Engine`; the `CLASS_Engine` `# endregion` comes AFTER the
  `METHOD_validate_inputs` `# endregion`.
- [x] 8.2 Manual scan: no invented GRACE field names anywhere in the touched
  files — only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` /
  `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`.
  Specifically, NO `SHALL NOT:` field and NO `RAISES:` field anywhere. The
  trimmed spec sentence "not in `Engine.__post_init__`" appears in code ONLY
  as a positive `INVARIANTS` statement on `CLASS_Engine` ("no
  `__post_init__`; ... validation lives in the parser").
- [x] 8.3 Manual scan: every `PURPOSE` field in the touched regions answers
  WHY, not WHAT. Spot-check: `MODULE_CONTRACT` `PURPOSE` in `config_parser.py`
  (kept WHY); `FUNC_engine_valid_fields` (replaced WHAT with WHY per task
  5.1); `FUNC_parse_engine_section` (replaced WHAT-leaning text with WHY per
  task 6.1); `FUNC_parse_engines` (replaced WHAT-leaning text with WHY per
  task 7.1); the three new `FUNC__check_*` regions (each WHY per tasks
  4.1–4.3); `CLASS_Engine` (kept WHY per task 2.1).
- [x] 8.4 Manual scan: every `RATIONALE` field is in Q/A format ("Q: ...
  A: ..."). No `RATIONALE` block contains free-form prose that should be in
  `PURPOSE` / `INVARIANTS` / `SCOPE`. Specifically the `MODULE_CONTRACT`
  `RATIONALE` added in task 3.3 is one Q (the layering question) and one A
  (the layering answer with the dependency-direction justification).
- [x] 8.5 Manual scan: the engine-related regions of
  `config_parser.py` enriched here do NOT overlap with the regions the
  in-flight `cloud-spec-trim` change claims (`FUNC__check_port`,
  `FUNC_cloud_valid_fields`, `FUNC__parse_*_section`, `FUNC_parse_cloud_*`).
  Engine regions only: `MODULE_CONTRACT`, `FUNC_engine_valid_fields`,
  `FUNC_parse_engine_section`, `FUNC_parse_engines`, plus the three new
  `FUNC__check_spawn` / `FUNC__check_check_` / `FUNC__check_at_least_one_elem`.
- [x] 8.6 `openspec validate --all --json` passes (exit 0); the trimmed
  `engine-config-parsing` spec validates AND the change
  `engine-config-parsing-spec-trim` validates AND no other spec regresses
  (still 20 specs + the in-flight changes including this one).
- [x] 8.7 `uv run pytest -m unit` — all unit tests pass (no behavior
  changed). Specifically `tests/unit/test_config.py`,
  `tests/unit/test_parse_engine_spawn_required.py`, and
  `tests/unit/test_domain_model.py` are green.
- [x] 8.8 `uv run pytest -m integration` — all integration tests pass (assume
  Docker running). Engine-config-parsing has no integration footprint;
  this step guards against accidental import-path regressions in
  `config_parser.py`.
- [x] 8.9 `uv run ruff check .` and `uv run ruff format --check .` pass on all
  changed files.
- [x] 8.10 `uv run lint-imports` passes (no new imports introduced;
  markup-only edits).
- [x] 8.11 Confirm no public-surface change: no CLI command, console_script,
  INI config key, DB schema, public API, or log-format change in the diff.
  The diff is `# region` / `# endregion` markup + comment-field enrichment +
  spec text trim only.
