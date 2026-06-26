## Why

The config-layer split (P1–P4) and the engine/cloud/domain migrations left behind
type-bridge debt: 5 `cast("Sequence[CloudConfig]", ...)` / `cast("ConfigCloud", ...)`
calls in the composition root and parser, plus 7 `# type: ignore` comments across
domain and entrypoints. The casts were thought to be forced by `Sequence`
invariance against the domain `CloudConfig` Protocol; empirical reproduction
(`/tmp/opencode/tc_repro/repro6.py`, mypy + pyright + runtime) showed the actual
blocker is **writable Protocol attributes vs `@dataclass(frozen=True)` DTOs**,
and that having the DTOs explicitly inherit the Protocol removes **3 of the 5
casts** (the 2 upcasts `list[ConfigCloud] → Sequence[CloudConfig]` and the
`config_parser.py:686` `Sequence[CloudConfig]` cast) without breaking the layers
contract (`infra → domain` is allowed; runtime import of domain symbols from
infra already exists in `infra/cloud/manager.py:30`).

The remaining **2 casts** (`di.py` `cast("ConfigCloud", cfg)` and
`cast("list[ConfigCloud]", [...])`) are **Protocol→Union downcasts**, not
upcasts: `config.clouds` is typed `Sequence[CloudConfig]` (domain Protocol), so
iterating yields `CloudConfig`, but the composition root feeds `cfg` to
infra-side sinks that expect the concrete `ConfigCloud` Union
(`resolve_adapter(cfg: ConfigCloud)`, `CloudProvisionerImpl.configs:
dict[str, ConfigCloud]`, `active_clouds: list[ConfigCloud]`). D1 (DTOs inherit
Protocol) makes the **upcast** direction (`list[ConfigCloud] →
Sequence[CloudConfig]`) typecheck via covariance + inheritance; it does nothing
for the opposite **downcast** direction (`CloudConfig → ConfigCloud`), which
remains invalid because a Protocol variable is not assignable to a
concrete-Union target regardless of inheritance. These 2 downcasts are honest
boundary casts at the entrypoints→infra seam and are retained with corrected
comments (the prior comments blamed "Sequence invariance"; the real reason is
the Protocol→Union downcast direction).

Two of the ignored sites hide latent runtime hazards that `# type: ignore`
masks:
- `config_parser.py:175` (`spawn=spawn  # type: ignore[arg-type]`): if an
  `[engine.*]` section omits `spawn`, `Engine(spawn=None)` is built and the
  post-construction validator `_check_spawn(engine, engine.spawn)` raises
  `AttributeError` (`None.format()`) instead of a meaningful `ValueError`.
- `model.py:155-159` (`TaskContext.from_metadata`): `metadata.get("remote_folder")`
  returns `object | None`, assigned to `str | None` fields with `# type: ignore`.
  A corrupted JSONB row (a non-str value under a str-typed key) silently builds
  an invalid `TaskContext`; consumers far downstream call `.upper()` and crash.

The remaining ignored sites are honest static gaps with no runtime hazard:
`az.py:210` (`dataclasses.replace` on a `PCloudConfig`-typed arg loses the
concrete `render_base64`), `settings.py:112` (`Field.default` typed `object`
stored into `dict[str, int]` after a `MISSING` guard).

## What Changes

- Make the 4 cloud-config DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`,
  `ConfigCloudUpcloud`, `ConfigCloudVastAI`) explicitly inherit the domain
  `CloudConfig` Protocol. The Protocol field types are already aligned with the
  DTOs (`jump_username: str | None`, `jump_host: str | None`); pyright/mypy
  pass with explicit inheritance (`/tmp/opencode/tc_repro/repro6.py`).
  `infra/cloud/cloud_configs.py` gains a runtime import of
  `CloudConfig` from `yascheduler.domain` (a new `infra → domain` edge, already
  exercised at runtime by `infra/cloud/manager.py:30` and `infra/persistence/
  postgres.py:27`). The layers contract permits `infra → domain` (infra sits
  above domain in `pyproject.toml:125-131`). A runtime import is required
  (not `TYPE_CHECKING`-only) because Python evaluates base classes at class
  definition time — a `TYPE_CHECKING`-only import would leave `CloudConfig`
  undefined at runtime and raise `NameError` when `cloud_configs.py` is loaded.
  No circular-import risk: `domain/ports.py` imports only stdlib `typing`.
- Remove **3 of the 5** cloud-config casts: the 2 upcasts
  `entrypoints/di.py:212,216` (`cast("Sequence[CloudConfig]", config.clouds)`
  and `cast("Sequence[CloudConfig]", active_clouds)`) and the parser cast
  `entrypoints/config_parser.py:686` (`cast("Sequence[CloudConfig]", clouds)`).
  After explicit DTO→Protocol inheritance, `list[ConfigCloud]` is assignable to
  `Sequence[CloudConfig]` (covariance + inheritance) and these 3 upcasts become
  dead weight. The **2 retained downcasts** `entrypoints/di.py:163,190`
  (`cast("ConfigCloud", cfg)` and `cast("list[ConfigCloud]", [...])`) are
  Protocol→Union downcasts at the entrypoints→infra boundary
  (`config.clouds: Sequence[CloudConfig]` → infra sinks typed `ConfigCloud`);
  D1 does not remove the downcast direction, so these stay with corrected
  comments. Update the now-inaccurate comments at `di.py:159-162` and
  `config_parser.py:683-685` (they blame "Sequence invariance"; the real
  cause was writable-vs-frozen mismatch for the upcasts and Protocol→Union
  downcast direction for the retained casts).
- Resolve `config_parser.py:175` (`spawn=spawn  # type: ignore[arg-type]`): hoist
  the missing-spawn check above the `Engine(...)` constructor. `parse_engine_section`
  SHALL raise `ValueError(f"Engine {name} has no spawn command")` when
  `sec.get("spawn")` is `None`, before constructing `Engine`. `Engine.spawn`
  stays `str` (non-Optional); `_check_spawn` continues to receive a guaranteed
  `str`.
- Resolve `az.py:210` (`.render_base64()  # type: ignore[misc]`): retype the
  `_render_custom_data` parameter from `PCloudConfig | None` to
  `CloudConfig | None` (the concrete `infra/cloud/cloud_config.CloudConfig`
  class, not the domain Protocol). The 3 callers (`create_node`,
  `create_vm_params`, `az_create_node`) currently typed
  `cloud_config: PCloudConfig | None` narrow at the call boundary with an
  `isinstance(cloud_config, CloudConfig)` guard or are retyped to accept the
  concrete class where they only ever forward the value.
- Resolve `settings.py:112` (`f.default  # type: ignore[dict-item]`): replace
  with `cast("int", f.default)`. The existing `f.default is not MISSING` guard
  plus the field-name filter (`f.name in _GE1_LIMIT_FIELDS + (...)`) guarantees
  the default is an `int` at runtime; the cast makes that assertion explicit to
  the type checker without altering runtime behavior.
- Resolve `model.py:155-159` (`TaskContext.from_metadata` 5×
  `# type: ignore[arg-type]`): introduce a private `_get_opt_str(metadata, key)`
  helper that returns `str | None` via `isinstance` narrowing and raises
  `TypeError(f"TaskContext JSONB field {key!r} expected str or None, got
  {type(v).__name__}")` on any other type. The 4 `str | None` field assignments
  (`remote_folder`, `local_folder`, `webhook_url`, `error`) route through the
  helper; the `engine` field already uses `str(metadata.get("engine", ""))`.
  The 5th ignored site, `webhook_custom_params`, is typed `dict[str, object]`
  (not `str | None`), so it cannot share the str helper — its existing
  `isinstance(wcp, dict)` guard already narrows `object` to `dict`; dropping
  the `# type: ignore[arg-type]` suffices because `dict` is assignable to
  `dict[str, object]` (the ignore was over-cautious, not load-bearing).
- Update the `CHANGE_SUMMARY` headers in touched files (`infra/cloud/
  cloud_configs.py`, `entrypoints/di.py`, `entrypoints/config_parser.py`,
  `infra/cloud/providers/az.py`, `domain/settings.py`, `domain/model.py`)
  with a `LAST_CHANGE` entry referencing this proposal.
- No public API, CLI, INI config, DB schema, or AiiDA entrypoint change. No new
  runtime dependency. No new module files.

## Capabilities

### New Capabilities

None. This is a type-hygiene change tightening existing contracts; no new
behavioral capability is introduced.

### Modified Capabilities

- `cloud-config-dtos`: DTOs now explicitly inherit the domain `CloudConfig`
  Protocol (was: structural-only satisfaction). The Requirement "Cloud config
  DTOs relocated to infra" gains a Scenario asserting explicit Protocol
  inheritance plus `isinstance(dto, CloudConfig) is True` (still works; Protocol
  is `@runtime_checkable`).
- `cloud-config-protocol`: the "structural, no explicit inheritance required"
  phrasing is relaxed to "structural or explicit inheritance; DTOs now inherit
  explicitly". The rationale paragraph (multiple DTO implementers → Protocol
  stays) is unchanged; the inheritance is a typing aid, not a structural
  requirement relaxation.
- `domain-entities`: the `TaskContext JSONB serialization` Requirement gains a
  Scenario asserting `from_metadata` raises `TypeError` on a non-str, non-None
  value under a str-typed key (was: silent `# type: ignore` assignment). The
  `webhook_custom_params` field is unchanged in behavior (the dropped ignore was
  over-cautious, not a contract change); only the 4 `str | None` fields gain the
  `TypeError` guard.
- `config-parser-assembly`: the engine-section parser Requirement gains a
  Scenario asserting `parse_engine_section` raises `ValueError` when `spawn` is
  absent (was: `Engine(spawn=None)` built, then `AttributeError` deep in
  `_check_spawn`).
- `domain-ports`: the `CloudConfig` Requirement's "satisfied by the concrete
  ConfigCloud* DTOs **without inheritance**" wording (lines 110-116 of the
  current spec) is synced to "satisfied structurally OR by explicit inheritance;
  the DTOs now explicitly inherit the Protocol as a typing aid". The Protocol's
  structural character is preserved (a DTO outside the inheritance tree still
  satisfies it structurally); the explicit inheritance is the chosen technique,
  not a structural requirement relaxation.

## Impact

- **Code**:
  - `yascheduler/infra/cloud/cloud_configs.py`: 4 DTO class headers gain
    `(CloudConfig)` inheritance + 1 runtime import.
  - `yascheduler/entrypoints/di.py`: drop 2 upcast `cast(...)` calls
    (`cast("Sequence[CloudConfig]", config.clouds)` and
    `cast("Sequence[CloudConfig]", active_clouds)`); keep 2 downcast
    `cast(...)` calls (`cast("ConfigCloud", cfg)` and
    `cast("list[ConfigCloud]", [...])`) with corrected comments explaining
    the Protocol→Union downcast direction; rewrite the inaccurate comments
    that blamed "Sequence invariance".
  - `yascheduler/entrypoints/config_parser.py`: drop 1 `cast(...)` (line 686),
    the inaccurate comment at 683-685; hoist the missing-spawn `ValueError` above
    the `Engine(...)` constructor (lines 169-185); drop the `spawn=spawn  # type:
    ignore[arg-type]` annotation.
  - `yascheduler/infra/cloud/providers/az.py`: retype `_render_custom_data`
    parameter to `CloudConfig | None`; drop the `# type: ignore[misc]` on line
    210; adjust the 3 callers' `cloud_config` typing where forwarded.
  - `yascheduler/domain/settings.py`: swap `f.default  # type: ignore[dict-item]`
    for `cast("int", f.default)` (line 112); add `cast` to the import list.
  - `yascheduler/domain/model.py`: add `_get_opt_str` private helper; route the
    5 ignored assignments in `from_metadata` through it (lines 155-159).
- **APIs**: None. No public symbol signature changes. DTO field sets, names,
  types, defaults — all preserved. `Engine.spawn` stays `str`; the change is
  parser-side validation tightening.
- **Layers contract**: One new **runtime** `infra → domain` edge in
  `infra/cloud/cloud_configs.py` (importing `CloudConfig` for the DTOs' base
  class list). `pyproject.toml:125-131` layers contract
  (`entrypoints > infra > application > domain > shared`) permits `infra →
  domain`. `uv run lint-imports` currently reports `KEPT` with an existing
  runtime `infra → domain` edge (`infra/cloud/manager.py:30`); the new edge is
  structurally identical. A runtime import (rather than `TYPE_CHECKING`-only)
  is required because Python resolves base classes at class definition time —
  a `TYPE_CHECKING`-only import of `CloudConfig` would raise `NameError` on
  module load.
- **Dependencies**: None. No new package; no version bump. `attrs` already
  removed by P5; nothing else moves.
- **Specs**: Delta specs for `cloud-config-dtos`, `cloud-config-protocol`,
  `domain-entities`, `config-parser-assembly`, `domain-ports` (5 deltas). Each
  adds Scenarios codifying the new behaviors above so a regression reintroducing
  the removable `cast`/`ignore` would fail the spec. The `cloud-config-protocol`
  delta's "No cast bridges in composition root" Scenario is scoped to the
  **removable upcasts** (`cast("Sequence[CloudConfig]"`); the 2 retained
  Protocol→Union downcasts (`cast("ConfigCloud"`, `cast("list[ConfigCloud]"`)
  are documented as honest boundary casts, not debt.
- **Tests**:
  - New unit: `tests/unit/test_cloud_config_protocol_inheritance.py` —
    asserts the 4 DTOs subclass `CloudConfig` (via `issubclass`-safe check:
    `isinstance(dto_instance, CloudConfig) is True` and explicit `issubclass`-
    via-`__mro__` introspection that avoids the runtime `issubclass` ban on
    data-Protocols with non-method members).
  - New unit: `tests/unit/test_parse_engine_spawn_required.py` — asserts
    `parse_engine_section` raises `ValueError` (not `AttributeError`) on a
    section without `spawn`.
  - New unit: `tests/unit/test_task_context_from_metadata_type_safety.py` —
    asserts `from_metadata({"remote_folder": 123})` raises `TypeError`.
  - Existing tests touched: `tests/unit/test_cloud_provisioner_impl.py:523`
    (`isinstance(cc, CloudConfig)`) continues to pass. `tests/unit/test_di.py`
    (asserts `active_clouds` in kwargs) unchanged. `tests/unit/test_config.py`
    (parser behavior) gains a missing-spawn case.
  - No integration/e2e changes: this is a static-typing + parser-validation
    change; DB/SSH/cloud paths untouched.
- **Knowledge graph** (`docs/knowledge-graph.xml`): `M-CLOUD-CONFIGS` gains a
  `<depends>` entry on `M-DOMAIN-PORTS` (DTOs now explicitly reference the
  Protocol). New `CrossLink` from `M-CLOUD-CONFIGS` to `M-DOMAIN-PORTS`
  relation "DTOs inherit CloudConfig Protocol". No `M-*` node added/removed;
  no `DF-*` data-flow change.
- **Verification**:
  - `uv run pytest -m unit` passes (incl. 3 new tests).
  - `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`,
    `uv run lint-imports` — all clean.
  - `rg -n 'cast\("(Sequence\[CloudConfig\]"' yascheduler/` returns zero
    matches for the resolved upcast sites (`di.py:212,216`,
    `config_parser.py:686`). The 2 retained downcasts
    (`di.py:163` `cast("ConfigCloud"`, `di.py:190` `cast("list[ConfigCloud]"`)
    remain and are documented as honest Protocol→Union boundary casts.
  - `openspec validate --all --json` passes after the 4 delta specs are added.
  - `python3 scripts/grace_check.py` passes (updated `MODULE_MAP` / `CHANGE_SUMMARY`
    entries in touched files; new `M-CLOUD-CONFIGS → M-DOMAIN-PORTS` CrossLink).