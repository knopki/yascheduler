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
- **`PURPOSE` answers WHY, not WHAT.** "Bundle DB, local, remote, clouds,
  engines into a frozen aggregate" is WHAT and fails. "Give the composition
  root a single immutable bag of settings so the orchestrator and CLIs
  receive one validated object instead of re-reading INI at every entry
  point" is WHY and passes. If the existing `PURPOSE` already answers WHY,
  leave it — do not churn for churn's sake.
- **Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity.**
  For a class: the `@dataclass(...)` decorator (if any), the `class` line,
  the docstring, every field, every `__init__` line, every `self.<attr>`
  assignment, through the trailing blank line before the next region marker.
  For a function: the decorator (if any), the `def`/`async def` line, the
  entire body, the trailing blank line. A region that closes before its
  entity ends (e.g. wrapping only the contract comment block) is a defect.
  The contract comment block (`# PURPOSE:`, `# INVARIANTS:`, etc.) sits
  INSIDE the region, ABOVE the entity's first line; the `# region` marker
  opens the block, the contract fields follow, then the entity, then
  `# endregion`. Nesting is allowed: `METHOD_*` and inner `BLOCK_*` regions
  live INSIDE the enclosing `CLASS_*` region; the `CLASS_*` `# endregion`
  comes after the last nested `# endregion`. Reference:
  `CLASS_LocalSettings` already wraps its nested `BLOCK_validate` correctly
  in `yascheduler/domain/settings.py` — use that as the shape.
- **Comment-only diff.** No code logic, signature, decorator choice, docstring
  semantics, or import changes. Edits are `# region`/`# endregion` marker
  insertion and contract-field enrichment inside the marker block. Module
  docstrings (the first `"""..."""` after `# endregion MODULE_CONTRACT`) are
  NOT touched.
- **Scope boundary for `config_parser.py`.** This change touches ONLY the
  `FUNC__parse_remote_section` region of
  `yascheduler/entrypoints/config_parser.py`. The cloud-related regions
  (`FUNC__check_port`, `FUNC_cloud_valid_fields`, the four
  `FUNC__parse_*_section` cloud parsers, `FUNC_parse_cloud_section`,
  `FUNC_parse_clouds`, `_CLOUD_*` tables, the engine/db/local/`parse_config`
  regions) are owned by the in-flight `cloud-spec-trim` change and are out
  of scope here.

## 1. Apply the config-value-objects spec delta

- [x] 1.1 Apply the 6 MODIFIED requirements from `openspec/changes/config-value-objects-spec-trim/specs/config-value-objects/spec.md` to `openspec/specs/config-value-objects/spec.md`, replacing each original requirement block in place. Preserve requirement header text exactly (whitespace-insensitive match) so OpenSpec recognizes the MODIFIED operation. Headers to match (in spec order): `LocalSettings value object`, `RemoteDefaults value object`, `[remote] section jump_port parsing and validation`, `PostgresDbConfig value object`, `Config aggregate`, `shared.compat re-exports StrEnum`.
- [x] 1.2 Confirm the trimmed main spec contains zero invented `SHALL NOT` enumerations of absent code (the `LocalSettings SHALL NOT carry the cloud_package_upgrade field` sentence is gone). Confirm every observable behavioral scenario (`#### Scenario:` count) is preserved: pre 24 → post 24. Confirm the 5 rationale pieces enumerated in `proposal.md` Why § 2 are gone from the spec body (the `getint` + range-check idiom split, the composition-root concept trailing phrase, the `Config.clouds` covariance narrative, the `typing-extensions` conditional-dependency paragraph, the `cloud-only concern` trailing rationale on `LocalSettings`). Confirm the redundant positive prose on `LocalSettings` legacy-key handling is gone (the corresponding scenario MUST stay).
- [x] 1.3 `openspec validate --all --json` passes (exit 0). The change validates AND the trimmed main spec validates AND no other spec regresses (currently 20 specs + `cli-spec-trim` + `cloud-spec-trim` + `config-value-objects-spec-trim`).

## 2. yascheduler/domain/settings.py — wrap CLASS_RemoteDefaults + enrich existing regions

Each new region opens one line above the entity and closes one line below the entity body, enclosing the FULL entity per the Common rules. Only defined GRACE fields are used; every `PURPOSE` answers WHY.

- [x] 2.1 Add `# region CLASS_RemoteDefaults` ... `# endregion CLASS_RemoteDefaults` enclosing the FULL dataclass block — the `@dataclass(frozen=True)` decorator, the `class RemoteDefaults:` line, the docstring, every field (`data_dir`, `tasks_dir`, `engines_dir`, `username`, `jump_username`, `jump_host`, `jump_port`), and the trailing blank line. The contract comment block (`# PURPOSE:`, `# INVARIANTS:`) sits INSIDE the region, above the `@dataclass(frozen=True)` line. `PURPOSE` (WHY: give every SSH-remote consumer a single immutable bundle of remote FS + jump-host defaults so they never re-derive paths or bastion identity at each call site). `INVARIANTS` (frozen stdlib dataclass, no INI parsing methods; `username` defaults to `"root"` matching the project's standard SSH identity; `jump_*` fields default to `None`/`22` so a flat topology returns a value without a bastion leg; `data_dir`/`tasks_dir`/`engines_dir` are `PurePath` because these are remote-side paths, never resolved locally).
- [x] 2.2 Enrich the existing `CLASS_LocalSettings` region: tighten `PURPOSE` to WHY if slipped (current text "Freeze the daemon's runtime configuration ... so it is validated once and shared safely across async components." already answers WHY — keep). Add `INVARIANTS` (frozen stdlib dataclass with no INI parsing methods; carries no `cloud_package_upgrade` field — that knob is cloud-only and lives on the per-provider `ConfigCloud*` DTOs; concurrency-limit fields in `_GE1_LIMIT_FIELDS` are `>= 1`; `webhook_reqs_limit >= 0`; path fields are `Path` instances). Add `RATIONALE` Q/A — Q: why does `LocalSettings` carry no `cloud_package_upgrade` field even though the legacy `[local]` INI schema used to declare one? A: `cloud_package_upgrade` is a per-provider knob sourced from each `ConfigCloud*` DTO at allocation time, so a single global value on `LocalSettings` would be ambiguous in multi-provider deployments; a leftover `[local] cloud_package_upgrade` INI key surfaces as a `ConfigWarning` (unknown field), not an error, so old configs fail loudly on the warning rather than silently mis-configuring cloud behavior.
- [x] 2.3 Tighten the existing `MODULE_CONTRACT` `PURPOSE` to WHY if slipped (current text "Carry daemon and remote-SSH defaults as validated, immutable values shared across layers without re-parsing INI at each use site." answers WHY — keep). No further enrichment needed.
- [x] 2.4 Verify `uv run ruff check yascheduler/domain/settings.py` and `uv run ruff format --check yascheduler/domain/settings.py` pass; `uv run pytest -m unit tests/unit/test_config.py tests/unit/test_domain_model.py` is green.

## 3. yascheduler/infra/persistence/db_config.py — wrap CLASS_PostgresDbConfig + enrich MODULE_CONTRACT

The new region encloses the FULL dataclass per the Common rules. Only defined GRACE fields are used; every `PURPOSE` answers WHY.

- [x] 3.1 Add `# region CLASS_PostgresDbConfig` ... `# endregion CLASS_PostgresDbConfig` enclosing the FULL dataclass block — the `@dataclass(frozen=True)` decorator, the `class PostgresDbConfig:` line, the docstring, every field (`user`, `password`, `database`, `host`, `port`), and the nested `BLOCK_validate` region (already exists — leave its content untouched; the `CLASS_*` `# endregion` comes after the nested `BLOCK_*` `# endregion`), and the trailing blank line. The contract comment block (`# PURPOSE:`, `# INVARIANTS:`) sits INSIDE the new region, above the `@dataclass(frozen=True)` line. `PURPOSE` (WHY: hand every persistence consumer — UoW, schema applier, migration runner, CLI — one immutable, validated connection bundle so they all reach the same database without re-listing defaults). `INVARIANTS` (frozen stdlib dataclass, no INI parsing methods — parsing lives in `entrypoints.config_parser._parse_db_section`; `port >= 1` enforced in `__post_init__`; default credentials are placeholders suitable for local development only — production deployments always override via INI).
- [x] 3.2 Tighten the existing `MODULE_CONTRACT` `PURPOSE` to WHY if slipped (current text "Supply type-safe, immutable connection parameters so all persistence consumers (UoW, migrations, schema applier, CLI) connect to the same database without repeating defaults or parsing config ad-hoc." answers WHY — keep). No further enrichment needed.
- [x] 3.3 Verify `uv run ruff check yascheduler/infra/persistence/db_config.py` and `uv run ruff format --check yascheduler/infra/persistence/db_config.py` pass; `uv run pytest -m unit tests/unit/test_config.py tests/unit/test_persistence_node_adapter.py` is green.

## 4. yascheduler/entrypoints/config.py — wrap CLASS_Config + enrich with composition-root + covariance rationale

The new region encloses the FULL dataclass per the Common rules. Only defined GRACE fields are used; every `PURPOSE` answers WHY.

- [x] 4.1 Add `# region CLASS_Config` ... `# endregion CLASS_Config` enclosing the FULL dataclass block — the `@dataclass(frozen=True)` decorator, the `class Config:` line, the docstring, every field (`db`, `local`, `remote`, `clouds`, `engines`), and the trailing blank line. The contract comment block (`# PURPOSE:`, `# INVARIANTS:`, `# RATIONALE:`) sits INSIDE the new region, above the `@dataclass(frozen=True)` line. `PURPOSE` (WHY: give the composition root a single immutable bag of every layer's settings so the orchestrator and CLI entry points receive one validated object instead of re-reading INI or threading five separate values through their constructors). `INVARIANTS` (frozen stdlib dataclass; carries no INI-parsing methods — parsing is owned by `entrypoints.config_parser.parse_config`; `clouds` is typed `Sequence[ConfigCloud]` — the infra Union of the 4 concrete `ConfigCloud*` DTOs, not the domain `CloudConfig` Protocol; consumed only at the composition root — no module in `yascheduler.application` or `yascheduler.infra` imports `Config`). `RATIONALE` Q/A — Q1: why is `Config` composition-root-only and not importable from `application` or `infra`? A1: `Config` is an aggregate over layer-specific DTOs (`PostgresDbConfig`, `LocalSettings`, `RemoteDefaults`, `ConfigCloud*`, `EngineRepository`); the upper layers (`application`, `infra`) already depend on the individual DTOs and the `CloudConfig` Protocol — letting them import `Config` would let the aggregate leak back down the dependency arrow and re-couple the layers to the composition root. Q2: why is `clouds` typed `Sequence[ConfigCloud]` (infra Union) when `application`-layer consumers (`Orchestrator`, `deallocate_nodes`) type their parameters against the domain `CloudConfig` Protocol? A2: the aggregate owns the concrete runtime list built by `parse_clouds`; `Sequence[ConfigCloud]` values are assignable to `Sequence[CloudConfig]` via covariance plus the explicit DTO→Protocol inheritance on each `ConfigCloud*` DTO, so the application layer keeps its Protocol-typed seam while the composition root keeps its concrete-typed aggregate — no `cast(...)` bridge needed.
- [x] 4.2 Tighten the existing `MODULE_CONTRACT` `PURPOSE` to WHY if slipped (current text "Bundle all layer-specific settings (DB, local, remote, clouds, engines) into a single frozen composition-root dataclass for delivery to the orchestrator and CLI entry points." answers WHY — keep). No further enrichment needed.
- [x] 4.3 Verify `uv run ruff check yascheduler/entrypoints/config.py` and `uv run ruff format --check yascheduler/entrypoints/config.py` pass; `uv run pytest -m unit tests/unit/test_config.py tests/unit/test_di.py` is green.

## 5. yascheduler/shared/compat.py — enrich MODULE_CONTRACT with typing-extensions rationale

No new region added (the file declares no class or function — it is a version-branch re-export module). Only the existing `MODULE_CONTRACT` is enriched. Only defined GRACE fields are used.

- [x] 5.1 Enrich the existing `MODULE_CONTRACT` in `yascheduler/shared/compat.py`: tighten `PURPOSE` to WHY if slipped (current text "Maintain forward-compatible type annotations across Python 3.9+ without import branching at every call site." answers WHY — keep). Update `SCOPE` to name `StrEnum` alongside `Self` and `Unpack`. Add `RATIONALE` Q/A — Q: why does `shared.compat` import `StrEnum` from `typing_extensions` below Python 3.11 instead of vendoring a local shim or pinning a newer Python? A: `typing-extensions` is already a conditional runtime dependency (`python_version < '3.11'` marker in `pyproject.toml`) — re-using it introduces no new dependency and stays in lockstep with upstream `enum.StrEnum` semantics; vendoring a shim would drift from upstream the moment a corner-case behavior changes.
- [x] 5.2 Verify `uv run ruff check yascheduler/shared/compat.py` and `uv run ruff format --check yascheduler/shared/compat.py` pass; `uv run pytest -m unit tests/unit/test_compat.py` is green.

## 6. yascheduler/entrypoints/config_parser.py — enrich FUNC__parse_remote_section with parser-idiom rationale

Only the `[remote]`-parser region is touched. The cloud-related regions of the same file are owned by the in-flight `cloud-spec-trim` change and are out of scope (see Common rules — Scope boundary).

- [x] 6.1 Enrich existing `FUNC__parse_remote_section` region: tighten `PURPOSE` to WHY if slipped (current text "Build a frozen RemoteDefaults from a [remote] INI section." is WHAT — replace with a WHY statement such as "Turn a `[remote]` INI section into a validated `RemoteDefaults` value object so the rest of the system consumes immutable typed values instead of re-reading `ConfigParser` proxies at every SSH call site"). Add `INVARIANTS` (validation runs in the parser, not in `RemoteDefaults.__post_init__` — `jump_port` is checked against the 1..65535 range via `_check_port`, mirroring the `yascheduler_nodes.jump_port` DB `CHECK` constraint; `user` and `jump_user` are INI aliases for `username` and `jump_username` and are registered in `_remote_valid_fields` so `warn_unknown_fields` does not fire on them). Add `RATIONALE` Q/A — Q: why does `jump_port` validation run in `_parse_remote_section` via `_check_port` instead of in `RemoteDefaults.__post_init__` like `LocalSettings` does for its concurrency limits? A: `jump_port` mirrors the `yascheduler_nodes.jump_port` DB `CHECK` constraint (1..65535) — keeping the same range check at parse time surfaces a misconfigured INI before any downstream code receives the value, and it follows the existing per-section parser idiom (`max_nodes`, `idle_tolerance`, cloud `{prefix}_jump_port`) so all port/limit invariants fail fast at config load; `LocalSettings` uses `__post_init__` because its limits are dataclass-internal (no DB mirror) and the parser must let a legitimate `0` reach `__post_init__` so `ge(1)` raises rather than being silently coerced.
- [x] 6.2 Tighten the existing `MODULE_CONTRACT` `PURPOSE` to WHY if slipped (current text "Parse INI config files into frozen domain/infra configuration objects — the adapter between ConfigParser and the application's typed configuration model." is borderline WHAT — replace with a WHY statement such as "Adapt `ConfigParser` to the application's frozen typed-configuration model so the rest of the system consumes validated value objects and never touches raw INI proxies"). Do NOT touch any other region in this file.
- [x] 6.3 Verify `uv run ruff check yascheduler/entrypoints/config_parser.py` and `uv run ruff format --check yascheduler/entrypoints/config_parser.py` pass; `uv run pytest -m unit tests/unit/test_config.py` is green.

## 7. End-to-end verify

- [x] 7.1 Manual scan: every `# region CLASS_*`, `FUNC_*`, `METHOD_*`, `BLOCK_*`, and `MODULE_CONTRACT` in `yascheduler/domain/settings.py`, `yascheduler/infra/persistence/db_config.py`, `yascheduler/entrypoints/config.py`, `yascheduler/shared/compat.py`, and the `[remote]`-parser region of `yascheduler/entrypoints/config_parser.py` has a paired `# endregion` and wraps the entire entity. No orphaned trailing code outside the region; no region closes before its entity ends. `CLASS_LocalSettings` and `CLASS_PostgresDbConfig` correctly enclose their nested `BLOCK_validate` regions (the `CLASS_*` `# endregion` comes after the inner `BLOCK_*` `# endregion`). `CLASS_RemoteDefaults` and `CLASS_Config` are newly added and wrap their full dataclass blocks including the `@dataclass(frozen=True)` decorator and the trailing blank line.
- [x] 7.2 Manual scan: no invented GRACE field names anywhere in the touched files — only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` / `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`. Specifically, NO `SHALL NOT:` field, NO `RAISES:` field, NO `EFFECTS:` field, NO `EXAMPLES:` field, NO `NOTES:` field anywhere.
- [x] 7.3 Manual scan: every `PURPOSE` field answers WHY, not WHAT. Spot-check `MODULE_CONTRACT` and every `CLASS_*` / `FUNC_*` / `METHOD_*` region in: `yascheduler/domain/settings.py`, `yascheduler/infra/persistence/db_config.py`, `yascheduler/entrypoints/config.py`, `yascheduler/shared/compat.py`, and the `FUNC__parse_remote_section` region of `yascheduler/entrypoints/config_parser.py`. Where the existing `PURPOSE` already answers WHY, leave it.
- [x] 7.4 Manual scan: every `RATIONALE` field is in Q/A format ("Q: ... A: ..."). No `RATIONALE` block contains free-form prose that should be in `PURPOSE` / `INVARIANTS` / `SCOPE`. Specifically, the `cloud-only concern / relocated to per-provider ConfigCloud* DTOs` narrative lives as a Q/A in `CLASS_LocalSettings.RATIONALE`; the parser-idiom split lives as a Q/A in `FUNC__parse_remote_section.RATIONALE`; the composition-root concept lives as a Q/A in `CLASS_Config.RATIONALE`; the covariance narrative lives as a Q/A in `CLASS_Config.RATIONALE`; the `typing-extensions` conditional-dependency narrative lives as a Q/A in `yascheduler/shared/compat.py` `MODULE_CONTRACT.RATIONALE`.
- [x] 7.5 `openspec validate --all --json` passes (exit 0); the trimmed `config-value-objects` spec validates AND the change `config-value-objects-spec-trim` validates AND no other spec regresses (still 20 specs + `cli-spec-trim` + `cloud-spec-trim` + `config-value-objects-spec-trim`).
- [x] 7.6 `uv run pytest -m unit` — all unit tests pass (no behavior changed; the existing 24 scenarios in `tests/unit/test_config.py` and `tests/unit/test_compat.py` already assert them).
- [x] 7.7 `uv run ruff check .` and `uv run ruff format --check .` pass on all changed files.
- [x] 7.8 `uv run lint-imports` passes (no new imports introduced; markup-only edits).
- [x] 7.9 Confirm no public-surface change: no CLI command, console_script, INI config key, DB schema, public API, or log-format change in the diff. The diff is `# region`/`# endregion` markup + comment-field enrichment + spec text trim only.
