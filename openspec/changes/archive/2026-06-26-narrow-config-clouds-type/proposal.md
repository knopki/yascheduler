## Why

The composition root (`entrypoints/di.py`) still carries 2 `cast(...)`
Protocol→Union downcasts at the entrypoints→infra boundary:
`cfg = cast("ConfigCloud", cfg)` (di.py:165) and
`active_clouds = cast("list[ConfigCloud]", [...])` (di.py:194-201). They exist
because `Config.clouds` is typed `Sequence[CloudConfig]` (domain Protocol) while
its only producer `parse_clouds` returns `list[ConfigCloud]` (infra Union), and
the composition root's infra sinks (`resolve_adapter`,
`CloudProvisionerImpl.configs`, `active_clouds`) consume the concrete Union.

The prior `2026-06-26-resolve-type-bridge-debt` proposal rejected narrowing
`Config.clouds` to `Sequence[ConfigCloud]` (its "A1" variant) on the grounds
that `list[ConfigCloud] → Sequence[CloudConfig]` failed under writable-vs-frozen
mismatch. That same proposal's D1 (the 4 `ConfigCloud*` DTOs explicitly inherit
the `CloudConfig` Protocol) removed the mismatch — which is why the proposal
could delete the 2 *upcast* bridges — but it did not revisit A1, leaving the 2
*downcasts* in place as "honest boundary casts". The D1 premise that
invalidated A1 is gone; A1 is now viable and strictly cleaner than carrying
boundary casts. This has been empirically verified on the real tree (zuban,
ruff, lint-imports, 647 unit tests all green with A1 applied and both casts
removed).

## What Changes

- Narrow `Config.clouds` field type from `Sequence[CloudConfig]` (domain
  Protocol) to `Sequence[ConfigCloud]` (infra Union) in
  `yascheduler/entrypoints/config.py`. Import `ConfigCloud` from
  `yascheduler.infra.cloud.cloud_configs` under `TYPE_CHECKING` (replacing the
  `CloudConfig` import that is no longer referenced by this file).
- Remove the 2 Protocol→Union downcasts in `yascheduler/entrypoints/di.py`:
  `cfg = cast("ConfigCloud", cfg)` and the `cast("list[ConfigCloud]", [...])`
  wrapper around the `active_clouds` list comprehension. Drop the now-unused
  `cast` import from `typing`. Remove the comments explaining the downcasts
  (the casts are gone; the upcast comment at di.py:204-206 stays and becomes
  more accurate).
- Update `CHANGE_SUMMARY` headers in `entrypoints/config.py` and
  `entrypoints/di.py` with a `LAST_CHANGE` entry referencing this proposal.
- Add a regression unit test asserting `cast(` is absent from
  `yascheduler/entrypoints/di.py` source (guards against silent reintroduction).
- No public API, CLI, INI config, DB schema, or AiiDA entrypoint change. No new
  runtime dependency. `Config` is internal to the composition root; its field
  type is not part of any stabilized surface in AGENTS.md.

## Capabilities

### New Capabilities

None. This is a type-narrowing hygiene change; no new behavioral capability is
introduced.

### Modified Capabilities

- `config-aggregate`: the `Config aggregate` Requirement's `clouds` field type
  changes from `Sequence[CloudConfig]` to `Sequence[ConfigCloud]`. A new
  Scenario codifies that `Config.clouds` is typed against the infra Union
  (composition root knows concrete DTOs; application/infra layers continue to
  type against the domain Protocol independently).
- `cloud-config-protocol`: the "Retained Protocol→Union downcasts at
  entrypoints→infra boundary" Scenario is replaced by a "No downcast bridges in
  composition root" Scenario — the carve-out for the 2 honest boundary casts is
  removed because the casts no longer exist. The "No upcast bridges in
  composition root" Scenario is broadened to "No cast bridges in composition
  root" (covers both directions). The rationale paragraph about downcasts being
  honest boundary casts is removed. Application-layer typing requirements
  (`deallocate_nodes`, `orchestrator` typing against `Sequence[CloudConfig]`)
  are unchanged — they continue to type against the domain Protocol; the
  covariance+inheritance unlocked by D1 makes `Sequence[ConfigCloud]` assignable
  to `Sequence[CloudConfig]` at the call site.
- `dependency-injection`: the `make_daemon factory` Requirement gains a Scenario
  asserting the composition root contains no `cast("ConfigCloud"` and no
  `cast("list[ConfigCloud]"` calls — the `active_clouds` list comprehension and
  the `resolve_adapter` feed are now type-clean against `ConfigCloud` directly.

## Impact

- **Code**:
  - `yascheduler/entrypoints/config.py`: 1 import swap (`CloudConfig` →
    `ConfigCloud` under `TYPE_CHECKING`), 1 field type change, `SCOPE` contract
    line + `CHANGE_SUMMARY` update.
  - `yascheduler/entrypoints/di.py`: drop 2 `cast(...)` calls + their comments;
    drop `cast` from the `typing` import; `CHANGE_SUMMARY` update.
  - `tests/unit/test_di.py` (or a new `test_di_no_casts.py`): add a regression
    assert that `cast(` does not appear in `di.py` source.
- **APIs**: None. No public symbol signature changes. `Config.clouds` is an
  internal field; its element type narrows from a Protocol to the concrete
  Union that already populates it at runtime. `parse_clouds` still returns
  `list[ConfigCloud]`; consumers reading Protocol-level fields (`.prefix`,
  `.max_nodes`, `.jump_host`, `.jump_username`, `.idle_tolerance`) are
  unaffected because every Union member declares those fields (via explicit
  Protocol inheritance from D1).
- **Layers contract**: One new `TYPE_CHECKING`-only `entrypoints →
  infra.cloud.cloud_configs` edge in `config.py`. The layers contract
  (`entrypoints > infra > application > domain > shared`) permits
  `entrypoints → infra`. The edge is `TYPE_CHECKING`-only (no runtime import);
  `uv run lint-imports` with `exclude_type_checking_imports = true` is
  unaffected. `Config` is already constructed at runtime by `parse_config` in
  the same `entrypoints` package; no new runtime cross-layer edge.
- **Dependencies**: None. No new package; no version bump.
- **Specs**: Delta specs for `config-aggregate`, `cloud-config-protocol`,
  `dependency-injection` (3 deltas). The `cloud-config-protocol` delta removes
  the "honest boundary cast" carve-out and broadens the no-cast Scenario.
- **Tests**:
  - New unit: `tests/unit/test_di_no_casts.py` (or appended to `test_di.py`) —
    asserts `cast(` is absent from `yascheduler/entrypoints/di.py` source.
  - Existing tests unchanged: `test_config.py` (parser behavior; `Config` field
    type is not asserted at the type level in tests), `test_di.py` (asserts
    `active_clouds` in kwargs — still passes), `test_cloud_config_protocol_inheritance.py`
    (D1 inheritance unaffected).
  - No integration/e2e changes: static-typing-only change; DB/SSH/cloud paths
    untouched.
- **Knowledge graph** (`docs/knowledge-graph.xml`): no `M-*` node added/removed;
  no `<depends>` change (`M-CLOUD-CONFIGS` is already in `M-ENTRYPOINTS-CONFIG`'s
  `<depends>`); no `CrossLink` change. The field type narrows but the structural
  dependency is unchanged. `CHANGE_SUMMARY` headers updated in the 2 touched
  modules.
- **Verification**:
  - `uv run pytest -m unit` passes (incl. new no-cast regression test).
  - `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`,
    `uv run lint-imports` — all clean.
  - `rg -n 'cast\(' yascheduler/entrypoints/di.py` returns zero matches.
  - `openspec validate --all --json` passes after the 3 delta specs are added.
  - `python3 scripts/grace_check.py` passes (updated `CHANGE_SUMMARY` entries).