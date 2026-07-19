## Why

`openspec/specs/config-value-objects/spec.md` (213 lines, 6 requirements, 24
scenarios) interleaves the actual SHALL requirements with three content kinds
that GRACE assigns to code-local contracts, not to spec text:

1. **Invented `SHALL NOT` and redundant positive prose already covered by
   scenarios** — 2 instances on `LocalSettings`:
   - The invented `SHALL NOT`: `LocalSettings SHALL NOT carry the
     cloud_package_upgrade field — that knob is a cloud-only concern and has
     been relocated to the per-provider ConfigCloud* DTOs`. The negative
     assertion is already covered by the positive `LocalSettings has no
     cloud_package_upgrade field` scenario (introspection), and the trailing
     "cloud-only concern / relocated" narrative is design rationale, not
     spec.
   - The redundant positive prose: `A legacy [local] cloud_package_upgrade
     INI key, if present, SHALL surface as an "unknown field" ConfigWarning,
     not as an error`. This is already asserted verbatim by the
     `legacy [local] cloud_package_upgrade warns as unknown` scenario, so the
     requirement-body restatement is drift bait — the WHY ("clean break, no
     deprecation shim, so old configs fail loudly") belongs in `RATIONALE`.
2. **Design rationale living in the spec body** — five distinct pieces:
   - the `SHALL NOT carry cloud_package_upgrade` "cloud-only concern /
     relocated to per-provider ConfigCloud* DTOs" narrative on `LocalSettings`;
   - the `[remote]` parser-validation split ("This follows the existing
     `getint` + range-check parser idiom (e.g. `max_nodes`, `idle_tolerance` in
     the cloud per-prefix parsers), NOT `__post_init__` validation on
     `RemoteDefaults`");
   - the `Config` aggregate composition-root narrative ("the aggregate is a
     composition-root concept consumed only by `entrypoints`");
   - the `Config.clouds` covariance narrative ("Application-layer consumers
     (`Orchestrator`, `deallocate_nodes`) type their parameters against the
     domain `CloudConfig` Protocol and receive `Sequence[ConfigCloud]` values
     assignable to `Sequence[CloudConfig]` via covariance plus the explicit
     DTO→Protocol inheritance on the `ConfigCloud*` DTOs");
   - the `shared.compat` conditional-dependency aside ("`typing-extensions` is
     already a conditional dependency (`python_version < '3.11'` in
     `pyproject.toml`); no new runtime dependency is introduced").
   Every piece answers *why the code is shaped this way* — they belong in
   `RATIONALE` / `INVARIANTS` on the owning entity, not in spec.

In parallel, the code under `yascheduler/` violates the GRACE Python rule ("if
an entity is annotated by markup, it must always be wrapped in a region"):
`RemoteDefaults`, `PostgresDbConfig`, and the `Config` aggregate are entirely
unwrapped — each carries a `MODULE_CONTRACT` for its owning file but no
enclosing `CLASS_*` region. Where regions exist
(`CLASS_LocalSettings` in `yascheduler/domain/settings.py`, the
`FUNC_*`/`METHOD_*` regions in `yascheduler/entrypoints/config_parser.py`),
they hold `PURPOSE` only — the rationale/invariants/scope that should
accompany the code is missing because it currently sits in the spec.

## What Changes

- **MODIFIED `config-value-objects`**: rewrite all 6 requirements to carry
  only behavioral contracts (SHALL statements + Gherkin scenarios). Remove
  the 1 invented `SHALL NOT` enumeration of absent code, the redundant
  positive prose restatement on `LocalSettings` legacy-key handling, and the
  5 design-rationale pieces listed above. Every observable behavioral
  scenario (24) survives unchanged. No requirement is added, removed,
  merged, or split; the 6 requirement headers stay identical so OpenSpec
  recognizes the MODIFIED operation.
- Add the missing `CLASS_*` regions required by the GRACE Python rule on the 3
  currently-unwrapped public dataclasses:
  - `RemoteDefaults` in `yascheduler/domain/settings.py`;
  - `PostgresDbConfig` in `yascheduler/infra/persistence/db_config.py`;
  - `Config` in `yascheduler/entrypoints/config.py`.
- Enrich existing `MODULE_CONTRACT`, `CLASS_*`, and `FUNC_*` regions with the
  rationale/invariants/scope that leaves the spec, each in its correct GRACE
  field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
    `LocalSettings` carries no `cloud_package_upgrade` field; `Config` carries
    no INI-parsing methods; `Sequence[ConfigCloud]` is assignable to
    `Sequence[CloudConfig]` via DTO→Protocol inheritance + covariance).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why `cloud_package_upgrade` is off `LocalSettings`; why the `[remote]`
    parser runs jump-port validation instead of `__post_init__`; why `Config`
    is composition-root-only; why `Sequence[ConfigCloud]` types the `clouds`
    field; why `shared.compat` introduces no new runtime dependency).
  - `SCOPE` declares the entity's functional boundaries with explicit `NOT:`
    exclusions where useful.
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  free-form labels. The spec's removed `SHALL NOT` sentences do NOT become a
  `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating the
  positive contract, or a `RATIONALE` Q/A if the rationale is the valuable
  part.
- Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity —
  the `@dataclass(...)` decorator (if any), the `class` / `def` line, the
  docstring, every field, every `__init__` line, every `self.<attr>` assignment,
  through the trailing blank line before the next region marker. No region
  closes before its entity ends. The contract comment block sits INSIDE the
  region, above the entity's first line; nested `BLOCK_*` regions (e.g.
  `BLOCK_validate` inside `LocalSettings.__post_init__`) stay INSIDE the
  enclosing `CLASS_*`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `config-value-objects`: requirements slimmed to SHALL statements and
  behavior scenarios; invented `SHALL NOT` negative-space language, the
  parser-idiom split, the composition-root narrative, the `Config.clouds`
  covariance narrative, and the `typing-extensions` conditional-dependency
  aside relocated out of the spec text and into GRACE code contracts across
  `yascheduler/domain/settings.py`,
  `yascheduler/infra/persistence/db_config.py`,
  `yascheduler/entrypoints/config.py`, `yascheduler/shared/compat.py`, and
  the `[remote]`-parser region of `yascheduler/entrypoints/config_parser.py`.
  No config-value-objects behavior, field, signature, scenario, INI key,
  import path, or public API is added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/config-value-objects/spec.md` rewritten — every
  requirement trimmed to behavioral SHALL + scenarios; pre/post scenario
  count MUST remain 24 → 24. `openspec validate --all --json` must still pass
  after the change.
- **Code (markup only, no logic)**:
  - `yascheduler/domain/settings.py` — wrap `CLASS_RemoteDefaults`; enrich
    `MODULE_CONTRACT`, `CLASS_LocalSettings`, and `CLASS_RemoteDefaults` with
    `RATIONALE` (relocated narrative). Comment-only diff.
  - `yascheduler/infra/persistence/db_config.py` — wrap
    `CLASS_PostgresDbConfig`; enrich `MODULE_CONTRACT` and the new `CLASS_*`
    with `INVARIANTS`. Comment-only diff.
  - `yascheduler/entrypoints/config.py` — wrap `CLASS_Config`; enrich
    `MODULE_CONTRACT` and `CLASS_Config` with `INVARIANTS` + `RATIONALE`
    (composition-root narrative + covariance narrative). Comment-only diff.
  - `yascheduler/shared/compat.py` — enrich `MODULE_CONTRACT` with `RATIONALE`
    (typing-extensions conditional dependency). Comment-only diff.
  - `yascheduler/entrypoints/config_parser.py` — enrich only the
    `[remote]`-parser region `FUNC__parse_remote_section` with `RATIONALE`
    (parser-idiom vs `__post_init__` split). The cloud-related regions of the
    same file are owned by the in-flight `cloud-spec-trim` change and are out
    of scope. Comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing unit tests in `tests/unit/test_config.py` and
  `tests/unit/test_compat.py` already assert them. A passing
  `uv run pytest -m unit` run after the change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config key,
  DB schema, public API, or log-format change in the diff. The diff is
  `# region` / `# endregion` markup + comment-field enrichment + spec text
  trim only.
- **Pilot scope**: this change ONLY dehydrates the `config-value-objects`
  spec. Other specs (`cloud`, `cli`, `orchestrator`, `engine-config-parsing`,
  etc.) are explicitly out of scope. Follows the pattern set by
  `2026-07-17-orchestrator-spec-dehydrate`,
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, the completed `cli-spec-trim`, and
  the in-flight `cloud-spec-trim`.
- **Non-goals**:
  - No change to any config-value-objects behavior, field, signature,
    decorator, INI key, validation rule, or import path.
  - No spec split; all trimmed requirements remain in the
    `config-value-objects` capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No markup additions to the cloud-related regions of
    `yascheduler/entrypoints/config_parser.py` (`FUNC__check_port`,
    `FUNC_cloud_valid_fields`, the four `FUNC__parse_*_section` regions,
    `FUNC_parse_cloud_section`, `FUNC_parse_clouds`, `_CLOUD_*` tables) —
    those regions are owned by the in-flight `cloud-spec-trim` change. This
    change touches ONLY the `FUNC__parse_remote_section` region of
    `config_parser.py`.
  - No rewrite of `yascheduler/entrypoints/config.py`'s composition-root
    wiring; only the `Config` dataclass itself is wrapped.
