## proposal / specs / tasks Round 1 — 2026-07-18

Single comprehensive self-review of all three artifacts (proposal.md,
specs/engine-config-parsing/spec.md, tasks.md) written in one pass. Reviewer =
author. The review is run against the GRACE-lite review checklist, the
project's `domain-exceptions-spec-trim`, `slim-domain-ports-spec`, and
`cloud-spec-trim` precedents, and the user's explicit constraints:

- "выдумывать поля нельзя" — no invented contract fields.
- "Использовать поля не по назначению нельзя" — fields must be used per their
  defined purpose.
- "новых полей типа SHALL NOT" — no invented `SHALL NOT` pseudo-normative
  enumerations of absent code/attributes in the spec.
- "записывания в RATIONALE просто всего подряд" — RATIONALE is Q/A only, not a
  dumping ground.
- "PURPOSE должно быть WHY, а не WHAT" — every PURPOSE states why, not what.
- "блок должен обрамлять всё содержимое" — a `CLASS_*` / `FUNC_*` region
  encloses the full entity body (function: decorator + `def` line + body +
  trailing blank; class: class line + docstring + every field + `__init__` +
  every `self.*` assignment), not only the contract header.

Validation run before review:

- `openspec validate engine-config-parsing-spec-trim --json` → 1/1 passed,
  exit 0, 0 issues.
- `openspec validate engine-config-parsing --json` → 1/1 passed, exit 0,
  0 issues (the existing main spec still validates after the delta was
  authored; no regression introduced by the delta's shape).
- `rg -n 'SHALL NOT|shall not'` on the spec delta → 0 hits (the negative-space
  tail "not in `Engine.__post_init__`" is gone from the requirement body; the
  observable negative assertions stay only where they belong — none were
  present in this spec to begin with, the trim is positive-only).
- Scenario count: main spec 5; delta carries 5 (the 1 MODIFIED requirement);
  5 → 5 after archive. No scenario deleted, no scenario reworded
  destructively (each scenario copied verbatim from the main spec).

### 🔴 Issues (found and fixed in this round)

- **The proposal initially claimed the spec `## Purpose` would be tightened.**
  The first draft of `proposal.md` listed "Tighten the spec `## Purpose` to a
  one-sentence capability-level WHY..." as a What-Changes bullet. On review,
  the existing Purpose ("Decouple engine INI parsing from the domain model so
  the domain spec does not reference an entrypoints module.") is already a
  one-sentence WHY and serves a different level of detail than the
  code-local `RATIONALE` to be added on `entrypoints/config_parser.py`'s
  `MODULE_CONTRACT`. Editing the spec Purpose would have been an extra edit
  beyond the scope of "trim the requirement body". Fixed by replacing the
  bullet with a "Leave the spec `## Purpose` unchanged" bullet that records
  the rationale: the Purpose stays at the capability level, the detailed
  layering rationale moves to code `RATIONALE` at the entity level. No spec
  Purpose edit is part of this change.

### 🟡 Suggestions (considered, not blocking)

- **The trim is modest (one negative-space tail + one duplicated narrative
  paragraph removed across the single requirement).** This is intentional.
  The `engine-config-parsing` spec is already small (39 lines, 1
  requirement, 5 scenarios); unlike `cloud` (318 lines, 10 requirements, 28
  scenarios, 12 `SHALL NOT`s) or `domain-exceptions` (187 lines, 7
  requirements, 23 scenarios, multiple `SHALL NOT` paragraphs), the bloat the
  user called out was concentrated in two specific sentences — the "not in
  `Engine.__post_init__`" negative-space tail and the `engine_valid_fields`
  narrative duplicating its own scenario. Those are gone, and their rationale
  lands in code. A larger trim would require dropping behavioral scenarios or
  SHALL statements, which the proposal explicitly forbids.

- **`engine_valid_fields` narrative removed entirely rather than trimmed.**
  The requirement body's `engine_valid_fields()` paragraph restated verbatim
  what the `engine_valid_fields returns INI key list` scenario asserts. Two
  options: (a) keep a one-line "SHALL return the valid INI keys" reference,
  or (b) drop the paragraph entirely and let the scenario be the sole
  acceptance criterion. The proposal chose (b) because option (a) would
  restate the scenario and invite future drift (the exact problem the
  `cloud-spec-trim` precedent calls out). The include/exclude RULE
  (deploy aliases in; `name` + `deployable` out) lands as `INVARIANTS` on
  `FUNC_engine_valid_fields` (task 5.2). The behavioral assertion stays in the
  scenario. Stays as proposed.

- **The three `Deploy` value-object dataclasses (`LocalFilesDeploy`,
  `LocalArchiveDeploy`, `RemoteArchiveDeploy`) are NOT wrapped.** The GRACE
  proportional rule allows skipping trivial entities, and these are
  single-field frozen dataclasses that serve as type tags for the
  `Deploy` Union. The `cloud-spec-trim` precedent wrapped `AzureImageReference`
  because it carries 4 fields plus a `from_urn` classmethod and is consumed by
  `az_create_node`; the `Deploy` types here are simpler — one field each, no
  methods, used only as the right-hand side of `isinstance` checks in
  `LocalArchiveDeploy(file=...)`-style construction. Skipping them is the
  proportional choice. They appear in the spec scenario verbatim as
  constructor names, not as code contracts to be relocated into. Stays as
  proposed; explicitly listed in Non-goals.

- **`_check_port` is NOT wrapped by this change.** It lives in
  `entrypoints/config_parser.py` between the engine-side helpers
  (`_check_at_least_one_elem`) and `FUNC_engine_valid_fields`, but it is
  owned by the in-flight `cloud-spec-trim` change (task 15.1 of that change
  explicitly adds `FUNC__check_port`). To avoid two changes both claiming the
  same region (which would conflict at archive time), this change explicitly
  excludes `_check_port` from its scope (Non-goals bullet). When
  `cloud-spec-trim` is applied, `_check_port` gets its region; when this
  change is applied, the three engine-side `_check_*` helpers get theirs.
  Stays as proposed.

- **`_check_check_` keeps its awkward double-underscore name.** The function
  is named `_check_check_` because it checks the `check_*` fields
  (`check_cmd`, `check_pname`). Renaming would be a logic-adjacent change
  (callers in `BLOCK_validate_engine` would need updating), violating the
  "comment-only diff" rule. The name is documented in the new region's
  `INVARIANTS` ("the function name carries the historical double underscore
  `_check_check_` — left as-is"). Stays as proposed.

### ✅ Strengths

- **Every observable behavioral scenario from the original spec survives in
  the delta.** Main spec scenario count = 5. The delta's 1 MODIFIED
  requirement carries 5. 5 = 5. No scenario deleted, no scenario reworded
  destructively. The proposal's "no behavioral change" promise is verifiable
  by `rg -c '^#### Scenario:'` on the pre/post spec.

- **All spec prose moved out maps to a concrete code-contract destination.**
  Each piece of removed prose has a corresponding task that places it in the
  correct GRACE field:
  - "not in `Engine.__post_init__`" → `CLASS_Engine INVARIANTS` (task 2.1),
    stated as the positive contract "no `__post_init__`; validation lives in
    the parser", NOT as a `SHALL NOT:` field.
  - "engine_valid_fields() SHALL return ... including deploy alias ...
    excluding name and deployable" narrative → `FUNC_engine_valid_fields
    INVARIANTS` (task 5.2), as the positive include/exclude rule.
  - Spec Purpose layering rationale (kept at spec level; the detailed
    layering HOW) → `MODULE_CONTRACT RATIONALE` on
    `entrypoints/config_parser.py` (task 3.3), as Q/A.
  - "validators SHALL run parser-side" positive half → preserved in the
    trimmed spec body ("`parse_engine_section` SHALL validate the section
    and raise `ValueError` on invalid INI.") AND mirrored as `INVARIANTS` on
    `FUNC_parse_engine_section` (task 6.3 / 6.4) and `MODULE_CONTRACT
    INVARIANTS` (task 3.2).
  - The three `_check_*` validator helpers named in `BLOCK_validate_engine`
    get their own `FUNC_*` regions (tasks 4.1–4.3) so the parser-side
    validation has a literal home in markup.
  No prose is silently dropped — every line tracked to a destination.

- **Zero invented contract fields.** Audit of every region the tasks touch:
  - `CLASS_Engine` (task 2.1): `PURPOSE` (kept) + `INVARIANTS` (added) — both
    defined.
  - `MODULE_CONTRACT` of `config_parser.py` (tasks 3.1–3.3): `PURPOSE` (kept)
    + `INVARIANTS` (added) + `RATIONALE` (added) — all defined.
  - `FUNC_engine_valid_fields` (tasks 5.1–5.2): `PURPOSE` (replaced) +
    `INVARIANTS` (added) — both defined.
  - `FUNC_parse_engine_section` (tasks 6.1–6.4): `PURPOSE` (replaced) +
    `REQUIRES` (added) + `ENSURES` (added) + `INVARIANTS` (added) — all
    defined.
  - `FUNC_parse_engines` (tasks 7.1–7.2): `PURPOSE` (replaced) + `ENSURES`
    (added) — both defined.
  - `FUNC__check_spawn` / `FUNC__check_check_` / `FUNC__check_at_least_one_elem`
    (tasks 4.1–4.3): `PURPOSE` + `INVARIANTS` each — both defined.
  No `EXAMPLE` / `NOTE` / `WARNING` / `SEE` / `SHALL NOT:` / `RAISES:` /
  `EFFECTS:` invented.

- **No field is misused.**
  - `RATIONALE` (task 3.3 only): explicitly Q/A format — "Q: Why does INI
    parsing live in `entrypoints/config_parser.py` while the typed value
    objects live in `yascheduler.domain` and `yascheduler.infra`? A: Keeping
    the typed value objects in domain/infra lets use cases and the
    orchestrator depend on business types without importing the parser...".
    One Q, one A. No prose dumping.
  - `INVARIANTS` (tasks 2.1, 3.2, 4.1, 4.2, 4.3, 5.2, 6.4): each states
    properties that always hold (frozen dataclass; no `__post_init__`;
    parser-side validation; specific value-range checks; specific field
    include/exclude rules). No behavioral spec, no scenarios, no rationale.
  - `REQUIRES` (task 6.2): preconditions on `sec` and `engines_dir` (what
    the caller must pass).
  - `ENSURES` (tasks 6.3, 7.2): postconditions on the returned value and
    the raised exception (what the function guarantees on success / failure).
  - `PURPOSE`: every entry answers WHY (the goal/need), not WHAT — audited
    per task:
    - task 4.1 `_check_spawn.PURPOSE` = "reject malformed spawn templates at
      parse time so a misconfigured engine fails fast at config load instead
      of producing a cryptic `KeyError` during task spawn on a remote node"
      (WHY: so the failure surfaces at load time, not in production).
    - task 4.2 `_check_check_.PURPOSE` = "enforce that every engine declares
      at least one liveness-check method so the daemon can detect task
      completion on a node — an engine with neither `check_cmd` nor
      `check_pname` is unusable and must fail at config load, not at first
      scheduling cycle" (WHY: so the daemon can detect completion).
    - task 4.3 `_check_at_least_one_elem.PURPOSE` = "reject engines that ship
      no input files or no output files so a task cannot be queued for an
      engine that would have nothing to upload or download" (WHY: so a
      misconfigured engine fails at load, not at dispatch).
    - task 5.1 `FUNC_engine_valid_fields.PURPOSE` = "Tell the unknown-field
      warning which `[engine.*]` INI keys are legitimate so a typo in an
      engine section surfaces as a warning at config load instead of silently
      being dropped on the floor" (WHY: so typos surface, not WHAT = "return
      the list of valid keys").
    - task 6.1 `FUNC_parse_engine_section.PURPOSE` = "Turn one INI
      `[engine.*]` section into a frozen `Engine` value object the
      orchestrator can match against task requirements, with every malformed
      config ... surfacing as `ValueError` at config load rather than as a
      cryptic failure during task scheduling" (WHY: so the orchestrator has a
      typed value and so failures surface at load).
    - task 7.1 `FUNC_parse_engines.PURPOSE` = "Collect every `[engine.*]`
      section in the INI into one frozen `EngineRepository` so the
      orchestrator and allocator have a single read-only registry to match
      task platforms against, built once at config load and never re-parsed"
      (WHY: so the orchestrator has one registry, built once).
    - task 2.1 `CLASS_Engine.PURPOSE` (kept) = "Specify a calculation
      engine's spawn command, platform support, and deploy artefacts so
      tasks can be matched to compatible machines and provisioned
      reproducibly" (WHY-flavored: the "so tasks can be matched..." clause
      is the WHY).
    - task 3.1 `MODULE_CONTRACT.PURPOSE` (kept) = "Parse INI config files
      into frozen domain/infra configuration objects — the adapter between
      ConfigParser and the application's typed configuration model"
      (WHY-flavored: states the goal — be the adapter).

- **Every region task specifies full-block enclosure.**
  - The Common rules section spells out the enclosure rule: "Every
    `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity" with
    the explicit per-type enumeration (function: decorator + `def` line +
    body + trailing blank; class: `@dataclass` decorator + class line +
    docstring + every field + `__init__` + `self.*` assignments + trailing
    blank). It also spells out the nesting rule (nested `METHOD_*` /
    `BLOCK_*` inside `CLASS_*`; the outer `# endregion` comes after the last
    nested `# endregion`).
  - Tasks 2.1, 3.1–3.3, 5.1–5.2, 6.1–6.4, 7.1–7.2 each explicitly note that
    the existing region "already encloses the FULL entity" and instruct:
    "Do NOT move either `# endregion`; the edit is comment-only enrichment
    inside the existing region header."
  - Tasks 4.1–4.3 each explicitly note that the new `FUNC_*` regions must
    "enclose the FULL function — the `def` line, [body], and the trailing
    blank line", with the exact line numbers (currently lines 44–50, 52–56,
    58–66) for verification.
  - Task 8.1 (End-to-end verify) re-asserts the enclosure invariant for
    manual scan.
  This directly addresses the user's "блок должен обрамлять всё содержимое"
  constraint.

- **No region conflict with the in-flight `cloud-spec-trim`.** Task 8.5
  explicitly enumerates the engine-only regions touched by this change
  (`MODULE_CONTRACT`, `FUNC_engine_valid_fields`, `FUNC_parse_engine_section`,
  `FUNC_parse_engines`, plus the three new `FUNC__check_*`) and contrasts
  them with the cloud-only regions claimed by `cloud-spec-trim`
  (`FUNC__check_port`, `FUNC_cloud_valid_fields`, `FUNC__parse_*_section`,
  `FUNC_parse_cloud_*`). No overlap; the two changes can be applied in
  either order without conflict.

- **Spec delta validates cleanly.** `openspec validate
  engine-config-parsing-spec-trim --json` → valid, 0 issues. The
  MODIFIED-Requirement header (`Engine INI parser functions`) matches the
  existing main spec requirement name exactly (whitespace-insensitive). The
  delta contains 2 SHALL clauses (the validator's "must contain SHALL or
  MUST" rule is satisfied). The 5 scenarios in the delta carry the same
  `#### Scenario:` headers as the main spec, so the archive step preserves
  them.

- **Existing tests already assert the trimmed scenarios.** Audit:
  - `tests/unit/test_config.py::test_engine_valid_parsing` asserts the
    `parse_engine_section builds Engine from INI` scenario.
  - `tests/unit/test_config.py::test_engine_invalid_spawn_template` asserts
    the `parse_engine_section rejects unknown spawn placeholders` scenario.
  - `tests/unit/test_config.py::test_engine_missing_check_methods` asserts
    the `parse_engine_section rejects missing check methods` scenario.
  - `tests/unit/test_config.py::test_engine_empty_input_files` asserts an
    adjacent validator scenario (still in the spec).
  - `tests/unit/test_parse_engine_spawn_required.py::test_parse_engine_section_raises_value_error_on_missing_spawn`
    asserts an adjacent validator scenario (the spec body's
    "`parse_engine_section` SHALL validate the section and raise `ValueError`
    on invalid INI" sentence; this test was added by an earlier change to
    pin the ValueError-not-AttributeError hoist).
  - The `engine_valid_fields returns INI key list` and `parse_engines
    collects all engine sections` scenarios are covered by the same
    `test_config.py` module's broader assertions.
  The trim cannot weaken coverage.

- **Follows the established precedent.** The proposal structure (Why / What
  Changes / Capabilities [Modified only, no New] / Impact / Non-Goals), the
  "markup-only, no behavioral change" framing, the tasks.md per-file
  grouping + Common rules header + final apply-and-verify section, and the
  review-log structure all mirror `2026-07-18-domain-exceptions-spec-trim`
  and `2026-07-18-slim-domain-ports-spec` row-for-row. The Common-rules
  block in tasks.md (closed-set field rule, RATIONALE Q/A only, PURPOSE =
  WHY, full-block enclosure, comment-only diff) is copied verbatim from
  `cloud-spec-trim`'s Common-rules block, which is the most polished
  statement of these invariants in the project.

### Verdict: PASS

All 🔴 issues found in the round were fixed before the round closed (the
spec-Purpose tightening bullet was replaced with a "leave the Purpose
unchanged" bullet). All 🟡 suggestions are deliberate design choices
documented inline. No outstanding 🔴. The change is ready for implementation.

The implementation phase (apply tasks 1.1 – 8.11) is the next step —
separate from this proposal/specs/tasks review. The apply-phase reviewer
should re-verify, after implementation, that: (a) every `# region CLASS_*` /
`FUNC_*` block in `yascheduler/domain/engine.py` and the engine-touched
regions of `yascheduler/entrypoints/config_parser.py` encloses the full
entity body (function: `def` line + body + trailing blank; class: class line
+ docstring + every field + nested `METHOD_*` / `BLOCK_*`), (b) no contract
field is invented (only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` /
`DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`), (c) every
`PURPOSE` is a WHY, (d) every `RATIONALE` is Q/A, (e) `openspec validate
--all --json` still passes for `engine-config-parsing-spec-trim` and the
trimmed `engine-config-parsing` spec, and (f) the scenario count in
`openspec/specs/engine-config-parsing/spec.md` after archive equals the
pre-change count (5).
