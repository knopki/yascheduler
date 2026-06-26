# Design — Resolve Type Bridge Debt

## Context

The config-layer split (P1–P4) and the engine/cloud migrations archived a series
of structural refactors. The tail of that work left two kinds of static-debt
artifacts in the tree:

1. **Five `cast("Sequence[CloudConfig]", ...)` / `cast("ConfigCloud", ...)`
   bridges** in the composition root (`entrypoints/di.py`) and the INI parser
   (`entrypoints/config_parser.py`).
2. **Seven `# type: ignore` annotations** across the domain and entrypoints
   (`domain/model.py` ×5, `entrypoints/config_parser.py` ×1, `domain/settings.py`
   ×1, `infra/cloud/providers/az.py` ×1).

The casts were added under a stated hypothesis ("the Union is not assignable to
the Protocol under invariance", per the comments at `di.py:159-162` and
`config_parser.py:683-685`). Empirical reproduction in
`/tmp/opencode/tc_repro/repro3.py` through `repro6.py` disproved that
hypothesis: the real blocker is **writable Protocol attributes vs
`@dataclass(frozen=True)` DTOs**, not `Sequence` invariance. Pyright's
diagnostic was explicit — `"prefix" is not read-only in protocol; "prefix" is
writable in protocol` — and explicit Protocol inheritance by the DTOs clears
it (`repro6.py`: mypy pass, pyright pass, runtime pass, frozen preserved, replace
preserved, `isinstance` preserved).

The 7 ignore sites split into two severity tiers:

- **Two latent-hazard ignores** that mask runtime bugs:
  - `config_parser.py:175` (`spawn=spawn  # type: ignore[arg-type]`): a missing
    `spawn` key builds `Engine(spawn=None)`; the post-construction validator
    `_check_spawn(engine, engine.spawn)` then calls `None.format(...)` →
    `AttributeError`, not the `ValueError` a user expects from a config error.
  - `model.py:155-159` (`TaskContext.from_metadata`): `metadata.get(...) ->
    object | None` assigned to `str | None` fields; a corrupted JSONB row (a
    non-str value under a str key) silently builds an invalid `TaskContext`;
    consumers far downstream call `.upper()` and crash far from the source.

- **Five honest-gap ignores** with no runtime hazard:
  - `az.py:210` (`dataclasses.replace` on a Protocol-typed arg loses the
    concrete `render_base64` method).
  - `settings.py:112` (`Field.default: object` stored into `dict[str, int]`
    after a `MISSING` guard — runtime-safe but statically under-narrowed).
  - `model.py:158` (`webhook_custom_params` field) — over-cautious ignore; the
    existing `isinstance(wcp, dict)` guard already narrows to `dict`, which is
    assignable to `dict[str, object]`.

This change resolves 10 of the 12 artifacts (3 upcasts + 7 ignores) via four
localized techniques, and retains 2 Protocol→Union downcasts as honest
boundary casts. None of the techniques alters a public API, an INI key, a DB
column, or a CLI flag.

## Goals / Non-Goals

**Goals:**

- Remove **3 of the 5** cloud-config `cast` bridges by having the 4 DTOs
  explicitly inherit the domain `CloudConfig` Protocol: the 2 upcasts in
  `di.py` (`cast("Sequence[CloudConfig]", config.clouds)` and
  `cast("Sequence[CloudConfig]", active_clouds)`) and the 1 cast in
  `config_parser.py` (`cast("Sequence[CloudConfig]", clouds)`). The remaining
  2 `di.py` casts (`cast("ConfigCloud", cfg)` and
  `cast("list[ConfigCloud]", [...])`) are Protocol→Union downcasts at the
  entrypoints→infra boundary; D1 removes the upcast direction only, so these
  are retained with corrected comments documenting the downcast direction.
- Remove the 2 latent-hazard `# type: ignore` sites by tightening parser-side
  and JSONB-deserialization-side validation.
- Remove the 5 honest-gap `# type: ignore` sites by tighter static narrowing
  (retype a parameter, `cast` after a runtime guard, drop an over-cautious
  ignore).
- Codify the tightened behaviors in 5 delta specs so a regression reintroducing
  the removable debt fails the spec.
- Preserve every public contract: DTO field sets/names/types/defaults, the
  `CloudConfig` Protocol's 6-field surface, `Engine.spawn: str` (non-Optional),
  the `isinstance(dto, CloudConfig)` runtime check, the layers contract, the
  `attrs`-free dependency posture, and the frozen-ness of every touched class.

**Non-Goals:**

- Refactoring the consumers of `CloudConfig` (`Orchestrator`,
  `deallocate_nodes`) — they continue to type against the domain Protocol; this
  change does not flip them to the infra `ConfigCloud` Union (that was the
  rejected A1 variant).
- Touching the 3rd-party SDK stub gaps in `az.py`, `hetzner.py`, `upcloud.py`
  (the ~15 `cast("int", hkey.id)` / `cast("str", nic.name)` calls). Those are
  out of scope; they are tracked separately as theme C.
- Touching the ~30 test-file `# type: ignore` annotations that reach into
  private attributes (`orch._gateway`, `repo._run`, etc.). Those are tracked
  separately as theme F.
- Adding `__post_init__` type validation to `TaskContext` or `Engine` beyond the
  JSONB-boundary helper. Defensive validation at every `replace()` is out of
  scope.
- Renaming, relocating, or splitting any module. No new files except 3 test
  files and the 5 spec-delta folders.

## Decisions

### D1: Explicit Protocol inheritance by the 4 DTOs (chosen over A1 and A3)

**Decision.** Make `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
`ConfigCloudVastAI` explicitly inherit the domain `CloudConfig` Protocol via an
**unconditional runtime import**:

```python
# infra/cloud/cloud_configs.py
from yascheduler.domain import CloudConfig   # runtime import — infra→domain permitted

@dataclass(frozen=True)
class ConfigCloudAzure(CloudConfig):
    prefix: str = "az"
    ...
```

The Protocol field types in `domain/ports.py:100-116` are already aligned with
the DTOs (`prefix: str`, `max_nodes: int`, `idle_tolerance: int`,
`username: str`, `jump_username: str | None`, `jump_host: str | None`); no
override-invariance clash. Verified in `repro6.py`: mypy + pyright + runtime all
pass, frozen preserved, `replace(a, max_nodes=5)` works, `isinstance(a,
CloudConfig)` is `True`.

**Runtime-import requirement.** Python evaluates base classes at class
definition time. A `TYPE_CHECKING`-only import of `CloudConfig` would leave
`CloudConfig` undefined in the module namespace at runtime and raise
`NameError` the moment `cloud_configs.py` is imported — which happens on every
package load (it is imported unconditionally by `protocols.py:37`,
`adapters.py`, `manager.py`). The import must be runtime. The pattern mirrors
the existing runtime `infra → domain` edge at `infra/cloud/manager.py:30`
(`from yascheduler.domain import CloudAllocateError, ConnectedMachine, Node`).
Verified no circular import: `domain/ports.py:23-25` uses
`from __future__ import annotations` and imports only stdlib (`typing`); it
does not import `infra`. End-to-end import sanity-checked
(`/tmp/opencode/tc_repro/repro_runtime.py`: `from
yascheduler.infra.cloud.cloud_configs import ConfigCloudAzure; from
yascheduler.domain import CloudConfig; isinstance(ConfigCloudAzure(),
CloudConfig)` → `True`, RC 0).

**Why not A1** (type `Config.clouds: Sequence[ConfigCloud]`, the infra Union):
tested in `repro3.py` — does **not** remove the casts. Consumers
(`Orchestrator`, `deallocate_nodes`) type against the domain Protocol; the
`Sequence[Union] → Sequence[Protocol]` assignment still fails for the
writable-vs-frozen reason. A1 just relocates the cast from the parser to the
composition-root's call to the consumer. Rejected.

**Why not A3** (flip consumers to the infra Union): breaks the layers contract
(`application` is below `infra`; `application → infra` is forbidden at runtime,
allowed only `TYPE_CHECKING`). Rejected.

**Why not move the Protocol to `shared`**: forces a cloud-concept into the
shared kernel, which today holds only typing shims (`Self`, `Unpack`). Pollutes
the kernel and creates a slippery slope. Rejected as disproportionate.

**Why not `TYPE_CHECKING`-only import of `CloudConfig`**: technically tempting
(to keep the import graph leaner), but Python's class-definition semantics
require the base class to be resolvable at runtime. A `TYPE_CHECKING`-only
guard on a base class raises `NameError`. The runtime import is required; the
`exclude_type_checking_imports = true` config at `pyproject.toml:120` is
irrelevant (it governs importlinter's view of `TYPE_CHECKING` blocks, not
Python's class-definition semantics).

**Layers contract check.** `pyproject.toml:122-131` layers contract is
`entrypoints > infra > application > domain > shared`. The new **runtime**
`infra → domain` edge in `cloud_configs.py` is permitted (infra is above
domain). An existing runtime `infra → domain` edge
(`infra/cloud/manager.py:30`) already passes `uv run lint-imports` with `KEPT`;
the new edge is structurally identical.

**Caveats addressed:**

- `issubclass(ConfigCloudAzure, CloudConfig)` raises `TypeError` at runtime for
  Protocols with non-method members (PEP 544). Verified in `repro4.py`.
  Mitigation: **production code never calls `issubclass` on `CloudConfig`** (grep
  confirmed zero matches in `yascheduler/`). The test
  `test_cloud_provisioner_impl.py:523` uses `isinstance(dto, CloudConfig)`,
  which works on instances (verified `True` in `repro6.py`). The new
  `test_cloud_config_protocol_inheritance.py` uses `__mro__` introspection and
  `isinstance`, never `issubclass`.
- Structural matching continues to work: a DTO outside the inheritance tree
  still satisfies `CloudConfig` structurally (PEP 544). Verified in
  `repro5.py` (`isinstance(RogueDTO(), CloudConfig)` is `True` even without
  inheritance). This means the inheritance is a typing aid, not a structural
  requirement relaxation.
- **D1 removes only the upcast direction.** Empirical post-D1 `zuban check`
  revealed that 2 of the 4 `di.py` casts are **Protocol→Union downcasts**, not
  upcasts: `config.clouds` is typed `Sequence[CloudConfig]` (domain Protocol),
  so iterating yields `CloudConfig`, but the composition root feeds `cfg` to
  infra-side sinks typed `ConfigCloud` (`resolve_adapter(cfg: ConfigCloud)`,
  `CloudProvisionerImpl.configs: dict[str, ConfigCloud]`,
  `active_clouds: list[ConfigCloud]`). D1 (DTOs inherit Protocol) makes the
  **upcast** `list[ConfigCloud] → Sequence[CloudConfig]` typecheck via
  covariance + inheritance; it does nothing for the opposite **downcast**
  direction (`CloudConfig → ConfigCloud`), which remains invalid because a
  Protocol variable is not assignable to a concrete-Union target regardless of
  inheritance. The 2 downcasts (`di.py` `cast("ConfigCloud", cfg)` and
  `cast("list[ConfigCloud]", [...])`) are retained as honest boundary casts
  with corrected comments (the prior comments blamed "Sequence invariance";
  the real reason is the downcast direction). Rejected alternatives for the
  downcasts: (a) retyping `Config.clouds: Sequence[ConfigCloud]` (variant A1,
  rejected pre-D1 in `repro3.py`; would require unfreezing the
  "Config.clouds stays Sequence[CloudConfig]" commitment across proposal +
  design + 3 specs); (b) retyping the infra sinks to accept `CloudConfig`
  (widens the infra surface to the domain Protocol, downstream ripple on
  `manager.py`/`provider_selection.py` which read provider-specific fields).
  Retaining the 2 downcasts with honest comments is the minimal change.

### D2: Hoist the missing-spawn `ValueError` above the `Engine(...)` constructor

**Decision.** In `parse_engine_section`, check `spawn is None` before building
`Engine`:

```python
spawn = sec.get("spawn")
if spawn is None:
    raise ValueError(f"Engine {name} has no spawn command")
input_files = gettuple("input_files")
...
engine = Engine(name=name, spawn=spawn, ...)   # spawn: str, no ignore
```

`Engine.spawn` stays `str` (non-Optional). `_check_spawn(engine,
engine.spawn)` receives a guaranteed `str`; its `value.format(...)` body is
safe.

**Why not B1b** (`Engine.spawn: str | None` + `__post_init__` validation):
relaxes the domain invariant. Every consumer of `engine.spawn` would have to
defend against `None`. The current contract is that `Engine.spawn` is a usable
command string; relaxing that to defend callers is the wrong direction.

**Why not B1c** (`cast("str", spawn)`): lies to the type checker — `None`
flows into `Engine`, then `_check_spawn` raises `AttributeError`. The bug stays;
only the static warning is silenced.

**Behavioral change scope.** Today, a missing `spawn` produces
`AttributeError: 'NoneType' object has no attribute 'format'` from
`_check_spawn`. After D2, it produces `ValueError("Engine <name> has no spawn
command")` from `parse_engine_section`. Both are unrecoverable config errors
raised at parser time; neither is a regression in any sensible sense. The new
error is strictly better (named exception, actionable message). The
`config-parser-assembly` delta spec codifies this with a Scenario.

### D3: Retype `_render_custom_data` to accept the concrete `CloudConfig` class

**Decision.** In `infra/cloud/providers/az.py`, change the parameter type of
`_render_custom_data` from `PCloudConfig | None` to `CloudConfig | None` (the
concrete `infra/cloud/cloud_config.CloudConfig` class, not the domain Protocol).
`dataclasses.replace(cloud_config, bootcmd=...)` then returns `CloudConfig`,
which has a concrete `render_base64()` method; the `# type: ignore[misc]`
drops.

The 3 callers (`create_node`, `create_vm_params`, `az_create_node`) are
currently typed `cloud_config: PCloudConfig | None`. Two routes:

- (D3a) Narrow at the call boundary: `if cloud_config is not None and not
  isinstance(cloud_config, CloudConfig): raise TypeError(...)` before forwarding
  to `_render_custom_data`. Defensive; rejects any foreign `PCloudConfig`
  implementation at the Azure-specific boundary (Azure never sees non-`CloudConfig`
  `PCloudConfig` impls in this codebase).
- (D3b) Retype the 3 callers' `cloud_config` parameters to `CloudConfig | None`
  wholesale. Simpler; but widens the signature change.

Chosen: **D3a (narrow at the boundary)** — retype only `_render_custom_data` to
`CloudConfig | None`, and keep `az_create_node`'s public signature at
`PCloudConfig | None` to preserve assignability to `CreateNodeCallable` at
`adapters.py:112`. The `az_create_node` body narrows at the single call site
where it forwards to `create_node`/`_render_custom_data`:

```python
async def az_create_node(
    log, cfg, key, cloud_config: PCloudConfig | None = None,
) -> str:
    if cloud_config is not None and not isinstance(cloud_config, CloudConfig):
        raise TypeError(
            f"az_create_node expects infra CloudConfig, got {type(cloud_config).__name__}"
        )
    ...
```

The private `create_node` and `create_vm_params` (called only by `az_create_node`)
are retyped to `CloudConfig | None` — no external caller, no contravariance risk.

**Why D3a over D3b:** `adapters.py:112` assigns `az_create_node` to
`create_node: CreateNodeCallable[TConfigCloud_co]` whose `__call__` takes
`cloud_config: Optional[PCloudConfig]`. Widening the parameter from
`PCloudConfig | None` to the concrete subclass `CloudConfig | None` narrows the
callable's accepted input set — callable contravariance would make
`az_create_node` **not** assignable to `CreateNodeCallable` (a function that
accepts fewer types is not a substitute for one that accepts more). D3b would
force a `# type: ignore[assignment]` or `cast(CreateNodeCallable, ...)` at
`adapters.py:112`, re-introducing the very kind of debt this change removes.
D3a keeps the public signature compatible with `CreateNodeCallable` and puts the
narrowing at the internal boundary, where it is honest and costs one guard per
forwarding call.

**Why not D2-alt (a `cast("CloudConfig", replace(...))`):** moves from
`ignore` to `cast`; both are static-only suppressions, but `cast` is honest
about "I know better than the checker", while the retype + boundary guard makes
the contract true at the boundary and catches foreign `PCloudConfig` impls at
runtime (defense-in-depth). Prefer the retype.

### D4: `cast("int", f.default)` for `_INT_DEFAULTS`

**Decision.** In `domain/settings.py:111-116`, swap the `# type: ignore[dict-item]`
for `cast("int", f.default)`:

```python
_INT_DEFAULTS: dict[str, int] = {
    f.name: cast("int", f.default)
    for f in fields(LocalSettings)
    if f.name in (_GE1_LIMIT_FIELDS + ("webhook_reqs_limit",))
    and f.default is not MISSING
}
```

The existing `f.default is not MISSING` guard plus the field-name filter
(`f.name in _GE1_LIMIT_FIELDS + ("webhook_reqs_limit",)`) guarantees the
default is an `int` at runtime — `LocalSettings` declares those fields as
`int` with `int` defaults. The `cast` makes that assertion explicit to mypy
without altering runtime behavior.

**Why not D4-alt (`isinstance(f.default, int)` additional guard):** redundant
given the field-name filter; would also change `0` (a legitimate default for
`webhook_reqs_limit`) handling — no, `isinstance(0, int)` is `True`, so it
would not. Still, the filter already constrains to int-defaulted fields; the
extra guard is belt-and-suspenders with no safety gain. The `cast` is the
minimal honest suppression.

### D5: `_get_opt_str` helper for `TaskContext.from_metadata`

**Decision.** In `domain/model.py`, introduce a module-private helper:

```python
def _get_opt_str(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None or isinstance(value, str):
        return value  # type checker narrows: None | str
    raise TypeError(
        f"TaskContext JSONB field {key!r} expected str or None, "
        f"got {type(value).__name__}"
    )
```

Route the 4 `str | None` field assignments (`remote_folder`, `local_folder`,
`webhook_url`, `error`) through it. The `engine` field already uses
`str(metadata.get("engine", ""))`. The 5th originally-ignored site
(`webhook_custom_params: dict[str, object]`) drops its `# type: ignore` because
the existing `isinstance(wcp, dict)` guard at `model.py:151-152` already
narrows `object` to `dict`, which is assignable to `dict[str, object]` — the
ignore was over-cautious.

**Fail-fast vs coerce.** Chosen: **fail-fast** (`raise TypeError` on a non-str,
non-None value). Rationale: the JSONB round-trip is the domain integrity
boundary; a non-str value under a str-typed key indicates upstream corruption
(a botched migration, a hand-edited row, a serialization bug). Silently
coercing (`return None`) would mask the corruption and shift the crash
downstream where the origin is untraceable. Fail-fast at the boundary is the
defensive choice for a domain value object.

**Why not B4c (a `TypedDict` for the JSONB schema):** strong long-term option,
but out of scope for this change. A `TypedDict` would require describing the
JSONB schema exhaustively (every known key, every type), and the current
`extra: dict[str, object]` channel explicitly allows arbitrary unknown keys
(the schema is intentionally open). A `TypedDict(total=False)` could model the
known fields, but the `from_metadata` body would still need an `isinstance`-or-
`cast` path for the open `extra` channel. Deferred to a future
`task-context-typed-metadata` proposal if the JSONB schema grows more rigid.

**Why not B4d (`__post_init__` type validation on `TaskContext`):** defensive
across all construction paths (not just `from_metadata`), but adds runtime
overhead to every `replace()` call and to every test fixture. The JSONB
boundary is the one place corruption enters; defending there is sufficient and
cheaper.

### D6: Comment and docstring corrections in `di.py`, `config_parser.py`, `domain/ports.py`

**Decision.** Rewrite three pieces of now-inaccurate prose:

- `di.py:159-162, 200-203`: the comments blamed "the Union is not assignable to
  the Protocol under invariance". The empirical finding is that the actual
  blocker was **writable Protocol attributes vs frozen dataclass DTOs**, and
  that blocker is removed by D1 (explicit inheritance). After D1, the casts are
  gone; the comments explaining them are co-located and also gone. No
  replacement comment is needed — the absence of the cast is the explanation.
- `config_parser.py:683-685`: same prose, same fate.
- `domain/ports.py:101-108`: the `CloudConfig` Protocol docstring currently
  says *"Satisfied structurally by every `ConfigCloud*` DTO in
  `infra/cloud/cloud_configs.py` (no explicit inheritance)."* After D1, the
  DTOs **do** inherit the Protocol. The docstring becomes factually wrong
  unless updated. Rewrite to: *"Satisfied by every `ConfigCloud*` DTO in
  `infra/cloud/cloud_configs.py` — the DTOs inherit this Protocol explicitly
  (typing aid); a DTO outside the inheritance tree still satisfies it
  structurally (PEP 544)."*

### D7: Knowledge graph and `CHANGE_SUMMARY` updates

**Decision.** `docs/knowledge-graph.xml` gains:

- `<M-CLOUD-CONFIGS>` `<depends>` entry adds `M-DOMAIN-PORTS` (the DTOs now
  explicitly reference the `CloudConfig` Protocol via a runtime import).
- `<CrossLink from="M-CLOUD-CONFIGS" to="M-DOMAIN-PORTS" relation="DTOs explicitly inherit CloudConfig Protocol as typing aid (structural matching still works without inheritance)" />`.

No `M-*` node added/removed; no `DF-*` data-flow change.

`CHANGE_SUMMARY` `LAST_CHANGE` entries refreshed in **7 touched modules** (the
proposal listed 6; `M-DOMAIN-PORTS` was missing — added here):

- `M-CLOUD-CONFIGS` (`infra/cloud/cloud_configs.py`) — DTOs inherit Protocol.
- `M-DOMAIN-PORTS` (`domain/ports.py`) — Protocol docstring updated; no
  signature change.
- `M-ENTRYPOINTS-DI` (`entrypoints/di.py`) — 4 casts removed, comments dropped.
- `M-ENTRYPOINTS-CONFIG-PARSER` (`entrypoints/config_parser.py`) — 1 cast
  removed; missing-spawn `ValueError` hoisted; 1 `type: ignore` removed.
- `M-CLOUD-AZ` (`infra/cloud/providers/az.py`) — `_render_custom_data` retyped;
  `az_create_node` boundary guard added; 1 `type: ignore` removed.
- `M-DOMAIN-SETTINGS` (`domain/settings.py`) — 1 `cast` replacing 1 `type:
  ignore`.
- `M-DOMAIN-MODEL` (`domain/model.py`) — `_get_opt_str` helper added; 5 `type:
  ignore` removed (4 routed through helper, 1 dropped as over-cautious).

No graph-edge changes for the 6 modules beyond `M-CLOUD-CONFIGS →
M-DOMAIN-PORTS`; they don't gain or lose a dependency (the `infra → domain`
runtime edge from `M-CLOUD-CONFIGS` is the only new structural relationship).

## Risks / Trade-offs

- **[Risk] `issubclass(DTOClass, CloudConfig)` raises `TypeError` at runtime
  for data-Protocols with non-method members (PEP 544 limitation).**
  → Mitigation: production code never calls `issubclass` on `CloudConfig` (grep
  confirmed). Tests use `isinstance(dto, CloudConfig)` (works on instances) and
  `__mro__` introspection (avoids the `issubclass` ban). The new
  `test_cloud_config_protocol_inheritance.py` documents the constraint in its
  contract.

- **[Risk] A future contributor adds a 5th `ConfigCloud*` DTO that forgets to
  inherit `CloudConfig`.**
  → Mitigation: structural matching still works (the Protocol is
  `@runtime_checkable` and the new DTO satisfies it structurally if it has the
  6 fields). The `test_cloud_config_protocol_inheritance.py` test asserts
  inheritance for the 4 known DTOs; a 5th DTO would need to be added to the test,
  which is a forcing function for the contributor to remember. The
  `cloud-config-dtos` delta spec Scenario also codifies "the 4 DTOs inherit
  CloudConfig".

- **[Risk] D3a narrows `az_create_node`'s accepted `cloud_config` to the
  concrete `infra/cloud/cloud_config.CloudConfig` subclass at runtime; a foreign
  `PCloudConfig` implementer fed into the Azure path would now raise `TypeError`
  instead of flowing through.**
  → Mitigation: grep `class.*PCloudConfig\|PCloudConfig)` confirms the only
  implementer is `infra/cloud/cloud_config.CloudConfig`. The Azure path is
  private to `az.py` and reached only via `CloudProvisionerImpl`, which builds
  `CloudConfig` directly. If a foreign implementer is introduced later, the
  `TypeError` is the correct signal — the Azure provider does not know how to
  render an alien `PCloudConfig`. The defensive guard is defense-in-depth, not
  a contract restriction.

- **[Risk] D2 changes the exception type raised on a missing `spawn` from
  `AttributeError` to `ValueError`, breaking any test that asserts
  `AttributeError`.**
  → Mitigation: grep `AttributeError.*spawn\|spawn.*AttributeError` over
  `tests/` for existing assertions; if any exist, update them to assert
  `ValueError` (the test task 5.2 covers this). The new error is strictly more
  informative; no test should be relying on `AttributeError` from a config
  parser. The behavioral change is parser-side only and matches the existing
  convention (other parser validators like `_check_az_user` raise
  `ValueError`).

- **[Risk] D5's `TypeError` on corrupted JSONB surfaces previously-silent
  corruption as a runtime crash, potentially in production.**
  → Mitigation: this is the intended behavior — silent corruption is worse
  than a loud crash at the deserialization boundary. The crash includes the
  field name and the offending type, enabling quick diagnosis. The
  `domain-entities` delta spec codifies the `TypeError` so contributors know
  the boundary enforces types. If a deployment hits this, it indicates
  pre-existing data corruption that was already breaking consumers downstream;
  surfacing it at the boundary is the fix, not the regression.

- **[Risk] The new `infra → domain` `TYPE_CHECKING` edge is later promoted to
  a runtime import by a careless contributor.**
  → Mitigation: the edge is `TYPE_CHECKING`-only; promoting to runtime would
  require deliberate code change. The `cloud-config-dtos` delta spec codifies
  the `TYPE_CHECKING`-only nature. `uv run lint-imports` with
  `exclude_type_checking_imports = true` will not flag a runtime promotion, but
  code review would catch it (the `TYPE_CHECKING` block is a visible seam).

- **[Trade-off] D1's explicit inheritance adds a `TYPE_CHECKING` import to
  `cloud_configs.py` that was not there before, slightly increasing the
  module's static-dependency surface.**
  → Accepted: the alternative (keeping the casts) is worse — the casts lie to
  the type checker about the assignability and accumulate as debt. The
  `TYPE_CHECKING` import is zero-runtime-cost and the layers contract permits
  the edge.

- **[Trade-off] D5's `_get_opt_str` helper adds ~6 lines to `domain/model.py`
  for 4 call sites.**
  → Accepted: the alternative (per-call `isinstance` + `raise`) duplicates the
  narrowing 4 times. The helper is module-private, has one job, and is tested
  by `test_task_context_from_metadata_type_safety.py`.

## Migration Plan

This is a pure refactor + validation-tightening change; no data migration, no
config migration, no deployment ordering.

1. **Apply D1** (DTOs inherit Protocol). Run `uv run lint-imports`, `uv run
   zuban check`, `uv run ruff check .` — confirm the new `TYPE_CHECKING` edge
   is clean and no new static errors appear.
2. **Remove the 3 upcast casts** (D1 unlocks these). Re-run the same checks;
   confirm `rg -n 'cast\("Sequence\[CloudConfig\]"' yascheduler/` returns
   zero matches at the resolved sites (`di.py:212,216`,
   `config_parser.py:686`). The 2 Protocol→Union downcasts (`di.py:163,190`)
   are retained as honest boundary casts with corrected comments.
3. **Apply D2** (hoist missing-spawn `ValueError`). Add the
   `test_parse_engine_spawn_required.py` test. Run `uv run pytest -m unit`.
4. **Apply D3a** (retype `_render_custom_data` and private `create_node`/
   `create_vm_params`; add the `az_create_node` boundary guard). Run
   `uv run zuban check`; confirm the `# type: ignore[misc]` at `az.py:210`
   is removed and no new contravariance error surfaces at `adapters.py:112`.
5. **Apply D4** (`cast("int", f.default)`). Run `uv run zuban check`.
6. **Apply D5** (`_get_opt_str` helper). Add the
   `test_task_context_from_metadata_type_safety.py` test. Run `uv run pytest -m
   unit`.
7. **Update comments** (D6) and `CHANGE_SUMMARY` headers in the 6 touched
   files.
8. **Update the knowledge graph** (D7). Run `python3 scripts/grace_check.py`.
9. **Final verification**: `uv run pytest -m unit`, `uv run zuban check`,
   `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`,
   `openspec validate --all --json`, `python3 scripts/grace_check.py`.

**Rollback:** `git revert` the change commit. No data rollback (no data
touched). No config rollback (no config touched). The rollback restores the
casts and the `# type: ignore` annotations; the latent bugs (D2, D5) re-emerge
but were present before this change anyway.

## Open Questions

None. The 7 decisions are self-contained; the explore phase empirically
verified the central D1 hypothesis (repro6.py) and the rejection of A1
(repro3.py) and A3 (layers contract). The 3 reviewer-flagged 🟡 issues on the
proposal (webhook_custom_params helper scope, grep pattern coverage,
domain-ports spec delta) are resolved in the proposal and codified in the spec
deltas below.