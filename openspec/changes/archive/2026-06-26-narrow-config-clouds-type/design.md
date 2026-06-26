## Context

The composition root (`yascheduler/entrypoints/di.py`) feeds `config.clouds`
into two categories of sinks:

1. **Application sinks** typed against the domain `CloudConfig` Protocol:
   `Orchestrator.__init__(config_clouds: Sequence[CloudConfig], active_clouds:
   Sequence[CloudConfig])` and `deallocate_nodes(config_clouds:
   Sequence[CloudConfig])`. These read only the 6 Protocol fields (`prefix`,
   `max_nodes`, `idle_tolerance`, `username`, `jump_username`, `jump_host`).
2. **Infra sinks** typed against the concrete `ConfigCloud` Union:
   `resolve_adapter(cfg: ConfigCloud)`, `CloudProvisionerImpl.configs:
   dict[str, ConfigCloud]`, and the local `active_clouds: list[ConfigCloud]`.
   These reach provider-specific fields (`token`, `api_key`, `vm_size`, …) via
   the Union.

`Config.clouds` is currently typed `Sequence[CloudConfig]` (domain Protocol), so
iterating yields `CloudConfig`. The application sinks accept that directly.
The infra sinks do not — a Protocol variable is not assignable to a
concrete-Union target — so the composition root carries 2 `cast(...)`
Protocol→Union downcasts:

- `cfg = cast("ConfigCloud", cfg)` at `di.py:165`, before
  `resolve_adapter(cfg, log)` and the `_configs[adapter.name] = cfg` /
  `active_clouds.append(cfg)` writes.
- `active_clouds = cast("list[ConfigCloud]", [...])` at `di.py:194-201`,
  wrapping the list comprehension in the `clouds is not None` branch.

The only producer of `Config.clouds` is `parse_clouds()` in
`entrypoints/config_parser.py`, which returns `list[ConfigCloud]`. At runtime
the field always holds `list[ConfigCloud]`; the Protocol typing is a
static-only widening that has no runtime correlate.

### Prior proposal context

The archived `2026-06-26-resolve-type-bridge-debt` proposal already dealt with
this surface. Its decisions:

- **D1**: the 4 `ConfigCloud*` DTOs explicitly inherit the domain `CloudConfig`
  Protocol. This removed the writable-vs-frozen mismatch (writable Protocol
  attributes vs `@dataclass(frozen=True)` DTOs) that had blocked
  `list[ConfigCloud] → Sequence[CloudConfig]` assignment.
- D1 unlocked removal of 2 **upcast** bridges
  (`cast("Sequence[CloudConfig]", config.clouds)` and
  `cast("Sequence[CloudConfig]", active_clouds)`).
- The proposal's design.md (lines 137-142) **rejected** narrowing
  `Config.clouds` to `Sequence[ConfigCloud]` (its "A1" variant) because, at the
  time of evaluation (pre-D1), `list[ConfigCloud] → Sequence[CloudConfig]`
  still failed under the writable-vs-frozen mismatch.
- The 2 **downcast** bridges were retained as "honest boundary casts" with
  corrected comments, because D1 removes only the upcast direction.

The premise of the A1 rejection (writable-vs-frozen mismatch) was removed by
D1 itself. The prior proposal did not revisit A1 after D1 landed. This change
is the revisit.

## Goals / Non-Goals

**Goals:**

- Remove the 2 Protocol→Union downcasts in `entrypoints/di.py` by narrowing
  `Config.clouds: Sequence[CloudConfig]` → `Sequence[ConfigCloud]`.
- Keep the application-layer typing (`Orchestrator`, `deallocate_nodes`)
  against the domain `CloudConfig` Protocol — application stays free of
  infra-DTO imports (the layers contract forbids `application → infra` at
  runtime; `TYPE_CHECKING`-only is already the pattern).
- Prove the change typechecks under the project's actual static checker
  (`zuban`) and passes the full static suite (`ruff`, `lint-imports`) and the
  unit suite.
- Codify the no-cast invariant in delta specs so a regression reintroducing
  the downcasts fails the spec.

**Non-Goals:**

- Flipping application-layer consumers (`Orchestrator`, `deallocate_nodes`) to
  type against `ConfigCloud`. They stay on the domain Protocol (variant A3 in
  the prior proposal, rejected for breaking the layers contract). The
  covariance+inheritance unlocked by D1 makes `Sequence[ConfigCloud]` assignable
  to `Sequence[CloudConfig]` at the call site, so application code is untouched.
- Touching the 3rd-party SDK stub gaps in `az.py`/`hetzner.py`/`upcloud.py`
  (~15 `cast("int", hkey.id)` calls). Out of scope; tracked separately.
- Renaming, relocating, or splitting any module. No new files except 1 test
  file and 3 spec-delta folders.
- Revisiting D1 (explicit Protocol inheritance by the DTOs). D1 stays — it is
  the precondition that makes A1 viable.

## Decisions

### D1: Narrow `Config.clouds` to `Sequence[ConfigCloud]` (variant A1, post-D1-prior)

**Decision.** In `yascheduler/entrypoints/config.py`, change the `clouds`
field type from `Sequence[CloudConfig]` to `Sequence[ConfigCloud]` and swap the
`TYPE_CHECKING` import accordingly:

```python
if TYPE_CHECKING:
    from collections.abc import Sequence

    from yascheduler.domain import (
        EngineRepository,
        LocalSettings,
        RemoteDefaults,
    )
    from yascheduler.infra.cloud.cloud_configs import ConfigCloud
    from yascheduler.infra.persistence import PostgresDbConfig


@dataclass(frozen=True)
class Config:
    db: PostgresDbConfig
    local: LocalSettings
    remote: RemoteDefaults
    clouds: Sequence[ConfigCloud]
    engines: EngineRepository
```

`ConfigCloud` is imported via the deep path
`yascheduler.infra.cloud.cloud_configs`, mirroring the existing import in
`entrypoints/config_parser.py:57-63`. The import is `TYPE_CHECKING`-only —
`Config` is a dataclass field annotation; under
`from __future__ import annotations` (already present at `config.py:18`) the
annotation is a string at runtime and the import is never executed.

**Why A1 now (post-D1-prior).** D1 of the prior proposal removed the
writable-vs-frozen mismatch by making the 4 `ConfigCloud*` DTOs explicitly
inherit `CloudConfig`. The same covariance+inheritance that let the prior
proposal delete the 2 upcast bridges makes `Sequence[ConfigCloud]` assignable
to `Sequence[CloudConfig]` — the mechanism is identical, only the source type
differs (`list[ConfigCloud]` vs `Sequence[ConfigCloud]`). Empirically verified
this session on the real tree: applied A1 + removed both casts + dropped the
`cast` import; `uv run zuban check` → Success (148 files); `uv run ruff check .`
→ All checks passed; `uv run lint-imports` → KEPT; `uv run pytest -m unit` →
647 passed. Tree restored; zuban green on clean tree.

**Why not keep the 2 downcasts as "honest boundary casts" (the prior proposal's
choice).** The casts are honest but unnecessary post-D1. Carrying them adds
maintenance cost (the comments explaining them are 6 lines of prose) and
signals to future contributors that Protocol→Union downcasts at this boundary
are expected — they are not, they are an artifact of a stale type widening.
Removing them aligns the static type with the runtime reality
(`list[ConfigCloud]` is what the field always holds).

### D2: Drop the 2 downcasts and the `cast` import from `di.py`

**Decision.** In `yascheduler/entrypoints/di.py`:

- Remove the 6-line comment + `cfg = cast("ConfigCloud", cfg)` at lines
  160-165. The loop variable `cfg` from `for cfg in config.clouds` is now
  `ConfigCloud` directly (D1 narrowed the field type); `resolve_adapter(cfg,
  log)`, `_configs[adapter.name] = cfg`, and `active_clouds.append(cfg)` all
  accept `ConfigCloud` without a cast.
- Remove the 2-line comment + `cast("list[ConfigCloud]", [...])` wrapper at
  lines 192-201. The list comprehension `[cfg for cfg in config.clouds if
  cfg.max_nodes > 0 and cfg.prefix in resolved_prefixes]` infers
  `list[ConfigCloud]` directly.
- Drop `cast` from the `from typing import TYPE_CHECKING, cast` line (now
  `from typing import TYPE_CHECKING`).
- The upcast comment at lines 204-206 ("The concrete ConfigCloud* DTOs
  explicitly inherit the domain CloudConfig Protocol (D1), so list[ConfigCloud]
  is assignable to Sequence[CloudConfig] (covariance + inheritance) without a
  cast.") stays — it is now the only cast-related comment and is accurate.

**Why not also retype the infra sinks (`resolve_adapter`, `configs` dict) to
`CloudConfig`.** That is variant B in the explore brief. The infra sinks read
provider-specific fields (`token`, `api_key`, `vm_size`) via the Union; widening
them to the Protocol forces casts *inside* infra where it is currently clean.
B moves debt deeper. Rejected.

### D3: Regression test guarding against silent reintroduction

**Decision.** Add `tests/unit/test_di_no_casts.py` (or append to `test_di.py`)
with a test that parses `yascheduler/entrypoints/di.py` via `ast` and asserts
no `typing.cast` usage: neither an `ImportFrom`/`Import` binding the name
`cast` (from `typing`), nor a `Call` whose function is `cast` (bare name) or
`typing.cast` (attribute). This is a cheap static guard: a future contributor
who reintroduces a `cast` in the composition root fails the unit suite.

```python
import ast
import pathlib

DI_PATH = pathlib.Path(__file__).resolve().parents[2] / "yascheduler" / "entrypoints" / "di.py"


def test_di_has_no_cast_usage() -> None:
    """The composition root must not use typing.cast.

    Config.clouds is typed Sequence[ConfigCloud], so iterating yields
    ConfigCloud directly and feeds the infra sinks without a cast. See
    openspec/changes/narrow-config-clouds-type for rationale.
    """
    tree = ast.parse(DI_PATH.read_text(), filename=str(DI_PATH))
    for node in ast.walk(tree):
        # `from typing import ... cast ...` (alias.name is "cast" even if `as _c`)
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            for alias in node.names:
                if alias.name == "cast":
                    raise AssertionError(f"typing.cast imported at line {node.lineno}")
        # `cast(...)` call (bare name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "cast":
            raise AssertionError(f"cast(...) called at line {node.lineno}")
        # `typing.cast(...)` call (attribute)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "cast"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "typing"
        ):
            raise AssertionError(f"typing.cast(...) called at line {node.lineno}")
```

**Why an AST-based test rather than a plain string `assert "cast(" not in
source`.** A plain string assertion would false-positive on the `cast(`
tokens that legitimately appear inside `CHANGE_SUMMARY` `PREVIOUS_CHANGE`
comment lines (D5 moves the current `LAST_CHANGE`, which references
`cast("ConfigCloud", cfg)` and `cast("list[ConfigCloud]", [...])` verbatim,
into `PREVIOUS_CHANGE`). The AST walk inspects only code — comments and string
literals are not visited, so the historical `cast(` tokens in the
`PREVIOUS_CHANGE` comment do not trip the test. This keeps the regression guard
honest without forcing a rewrite of the historical record.

**Why not also assert no `# type: ignore` in `di.py`.** Out of scope — the
prior proposal handled the `type: ignore` sites elsewhere; `di.py` currently
has none. The narrow assertion is sufficient for this change.

### D4: Spec deltas — remove the downcast carve-out, broaden the no-cast Scenario

**Decision.** Three delta specs:

- `config-aggregate`: the `Config aggregate` Requirement's `clouds` field type
  changes from `Sequence[CloudConfig]` to `Sequence[ConfigCloud]`. Add a
  Scenario asserting `Config.clouds` annotation resolves to
  `Sequence[ConfigCloud]` (importable from
  `yascheduler.infra.cloud.cloud_configs`).
- `cloud-config-protocol`: replace the "Retained Protocol→Union downcasts at
  entrypoints→infra boundary" Scenario with "No downcast bridges in
  composition root" (asserts `cast("ConfigCloud"` and
  `cast("list[ConfigCloud]"` both return zero matches in `di.py`). Broaden
  "No upcast bridges in composition root" to "No cast bridges in composition
  root" (single Scenario covering both directions). Remove the rationale
  paragraph that justified the downcasts as honest boundary casts. Keep the
  application-typing Scenarios (`deallocate_nodes`, `orchestrator` typing
  against `Sequence[CloudConfig]`) unchanged — they still hold.
- `dependency-injection`: the `make_daemon factory` Requirement gains a Scenario
  asserting the composition root contains no `cast("ConfigCloud"` and no
  `cast("list[ConfigCloud]"` calls — the `active_clouds` list comprehension
  and the `resolve_adapter` feed are now type-clean against `ConfigCloud`
  directly.

**Why not a single combined delta.** The three specs have independent
Requirements; OpenSpec deltas map 1:1 to existing specs. The change touches
3 existing specs, so 3 delta folders.

### D5: `CHANGE_SUMMARY` updates (no knowledge-graph change)

**Decision.** Update `CHANGE_SUMMARY` `LAST_CHANGE` entries in
`entrypoints/config.py` and `entrypoints/di.py`. No `docs/knowledge-graph.xml`
change: `M-CLOUD-CONFIGS` is already in `M-ENTRYPOINTS-CONFIG`'s `<depends>`
(confirmed at `config.py:6`); the field type narrows but the structural
dependency is unchanged. No `M-*` node added/removed; no `CrossLink` change;
no `DF-*` data-flow change.

## Risks / Trade-offs

- **[Risk] `Config.clouds` stops being typed against the domain Protocol; a
  future contributor reads this as "the composition root knows about infra
  DTOs, so application/infra may also."**
  → Mitigation: the delta spec for `cloud-config-protocol` keeps the
  application-typing Scenarios unchanged (`deallocate_nodes`,
  `orchestrator` type against `Sequence[CloudConfig]`). The layers contract
  is enforced by `uv run lint-imports` and the `application → infra` ban
  stays. `Config` is the composition-root aggregate; it already imports
  `PostgresDbConfig` from infra, so importing `ConfigCloud` from infra is
  consistent with the aggregate's existing posture.

- **[Risk] A future contributor reverts the narrowing and reintroduces the
  downcasts to "make it compile" after some unrelated change.**
  → Mitigation: D3's regression test fails the unit suite if `cast(` reappears
  in `di.py`. The delta spec for `cloud-config-protocol` codifies the no-cast
  invariant. The delta spec for `dependency-injection` adds a parallel
  Scenario.

- **[Risk] `TYPE_CHECKING`-only import of `ConfigCloud` in `config.py` is
  promoted to a runtime import by a careless contributor.**
  → Mitigation: `from __future__ import annotations` at `config.py:18` keeps
  the annotation a string at runtime; promoting the import to runtime would
  require deleting the `TYPE_CHECKING` guard, which is a visible seam.
  `uv run lint-imports` with `exclude_type_checking_imports = true`
  (`pyproject.toml:119`) does not flag a runtime promotion, but code review
  would catch it. The prior proposal used a runtime import for `CloudConfig`
  in `cloud_configs.py` because Python resolves base classes at class
  definition time — that constraint does not apply here (`Config` does not
  inherit from `ConfigCloud`; it only annotates a field).

- **[Risk] D1-prior's empirical repro (`repro3.py` referenced in the archived
  design.md:138) is not available for re-inspection; the current proposal
  relies on a fresh repro (`/tmp/opencode/repro_a1/repro_a1_clean.py`) plus a
  real-tree spike.**
  → Mitigation: the real-tree spike is the stronger evidence — it ran on the
  actual project tree with the project's actual static checker (`zuban`),
  not an isolated repro. The spike was reverted; the tree is clean; the
  verification commands in the proposal can be re-run during implementation
  to confirm. The isolated repro remains at `/tmp/opencode/repro_a1/` for
  reference.

- **[Trade-off] `Config.clouds: Sequence[ConfigCloud]` couples the aggregate
  to the infra Union more tightly than `Sequence[CloudConfig]` did.**
  → Accepted: the coupling already exists at runtime (`parse_clouds` returns
  `list[ConfigCloud]`), and `Config` already imports `PostgresDbConfig` from
  infra. The static type now matches the runtime type. The alternative
  (keeping the Protocol widening + the 2 casts) preserves a false
  abstraction at the cost of maintenance debt.

- **[Trade-off] The regression test (D3) reads source as text, which is
  brittle to formatting (e.g., `cast (` with a space would slip through).**
  → Accepted: `cast(` is the canonical form in this codebase (confirmed via
  grep — all existing `cast` calls use `cast("...", ...)` with no space). The
  assertion is a guard, not a parser; false negatives from weird formatting
  are acceptable given the invariant is rarely threatened.