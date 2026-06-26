# Design — cloud-init-rename-and-prune

## Context

`resolve-type-bridge-debt` (archived 2026-06-26, partially executed) cleared the
deep az.py retyping (D3a): `_render_custom_data`, `create_node`,
`create_vm_params` now take the concrete `infra/cloud/cloud_config.CloudConfig`
class, and `az_create_node` keeps its public parameter at `PCloudConfig | None`
with a runtime `isinstance` boundary guard bridging the two types. That change
left three accumulated debts visible in the cloud protocols area:

1. `PCloudConfig` — a single-implementer Protocol (`infra/cloud/cloud_config.
   CloudConfig` is the sole structural impl), NOT `@runtime_checkable`, zero
   `isinstance` calls, zero runtime dispatch. Its "necessity" is a closed loop:
   `CreateNodeCallable.__call__` references it, and the provider callables
   reference it because `CreateNodeCallable` does.
2. `CloudCapacity` — a frozen dataclass last consumed by `clouds.get_capacity()`,
   which the archived `cloud-provisioner-pure` change (2026-06-22) deleted in
   favor of an inline `Orchestrator._clouds_get_capacity() -> int`. Survived two
   subsequent refactors (attrs→dataclass migration, config relocation) as
   busywork; never re-queried for necessity.
3. Name collision — `infra/cloud/cloud_config.py` (singular, holds
   `class CloudConfig` the cloud-init renderer) vs `infra/cloud/cloud_configs.py`
   (plural, holds the `ConfigCloud*` provider-config DTOs) vs
   `domain/ports.py` (a third, unrelated `CloudConfig` Protocol). Three concepts,
   two names, one letter of filename difference.

The window is open: D3a did the hard retyping; what remains is surface-level
(rename + Protocol collapse + dead-class deletion).

## Goals / Non-Goals

**Goals:**

- Rename the cloud-init renderer (`cloud_config.py` / `class CloudConfig`) to
  `cloud_init.py` / `class CloudInitConfig` so the cloud-init concept stops
  colliding with the provider-config concept.
- Remove the `PCloudConfig` Protocol. Collapse the single-implementer Protocol
  into its sole concrete class; retype `CreateNodeCallable.__call__` and the
  five provider `*_create_node` signatures to the concrete class in one
  coordinated pass.
- Delete the dead `CloudCapacity` dataclass and its `__init__.py` re-exports.
- Drop the D3a `isinstance` boundary guard in `az_create_node` (redundant when
  both sides are the same concrete class).
- Codify the new shape in two delta specs (`cloud-provisioner`,
  `package-facades`) and one renamed knowledge-graph node.
- Preserve every public contract: no CLI, INI, DB schema, AiiDA entrypoint, or
  `class Yascheduler` API change. No new runtime dependency.

**Non-Goals:**

- Touching the **domain** `CloudConfig` Protocol in `domain/ports.py` (Concept
  A — the 6-field provider-config contract). That Protocol is the subject of
  the `cloud-config-protocol` spec; this change does not modify it.
- Touching the 2 retained Protocol→Union downcasts in `di.py:165,194`
  (`cast("ConfigCloud", cfg)`, `cast("list[ConfigCloud]", [...])`).
  `resolve-type-bridge-debt` legalized those as honest boundary casts; they
  live on the *domain Protocol → infra Union* seam, which this change does not
  touch.
- Renaming the `ConfigCloud*` DTOs or the `ConfigCloud` Union in
  `infra/cloud/cloud_configs.py` (Concept A's infra home). That surface is
  widely referenced; the cost-benefit does not favor a rename here.
- Touching the ~15 third-party-SDK stub gaps in `az.py`, `hetzner.py`,
  `upcloud.py` (`cast("int", hkey.id)`, `cast("str", nic.name)`,
  `# type: ignore[arg-type]` on `dataclass_asdict(vm_image)`,
  `# type: ignore[attr-defined]` on `server.storage_devices`, etc.). Those are
  a separate debt theme, out of scope.
- Splitting `cloud_init.py` further (e.g., separating render vs render_base64,
  or extracting a writer). The renderer is ~13 lines; YAGNI.
- Adding `__post_init__` validation to `CloudInitConfig`. The class is a thin
  value object over cloud-init YAML keys; the provider serializes it and the
  VM consumes it. Defensive validation belongs at the YAML boundary, not here.
- Deprecating the old import path with a shim. The old name
  (`from yascheduler.infra.cloud import CloudConfig`) is an intra-`yascheduler/`
  convenience re-export, not a published SDK symbol; all call sites are
  in-tree and retyped atomically in this change.

## Decisions

### D1: Rename the renderer Concept B to `CloudInitConfig` / `cloud_init.py`

**Decision.** Rename the file `infra/cloud/cloud_config.py` →
`infra/cloud/cloud_init.py` and the class `CloudConfig` → `CloudInitConfig`.
The class becomes a plain `@dataclass(frozen=True)` with no base class (the
`PCloudConfig` Protocol base is dropped — see D2).

Honest name chosen over alternatives:
- `CloudInitConfig` (chosen) — names what it actually is: the cloud-init
  user-data configuration. Matches the `bootcmd` / `package_upgrade` /
  `packages` / `render` / `render_base64` surface. Reads unambiguously next to
  `ConfigCloudAzure` / `ConfigCloudHetzner` (provider configs).
- `UserDataConfig` — technically correct (cloud-init calls it "user-data") but
  less specific; `userdata` is also a Kubernetes/AWS term and could mislead.
- `BootConfig` — too narrow; the class carries `packages` and
  `package_upgrade`, not just `bootcmd`.

**Why not rename Concept A instead** (the `ConfigCloud*` DTOs /
`ConfigCloud` Union / the domain `CloudConfig` Protocol): Concept A's surface
is an order of magnitude wider — the DTOs appear in the INI parser, the
composition root, the orchestrator, `deallocate_nodes`, the domain Protocol's
own spec. Concept B's surface is bounded: 1 file, 5 provider files, 1 manager
file, 1 `__init__.py`, 1 test file, 1 spec Scenario. Renaming B is cheap and
resolves the collision; renaming A would be a separate, much larger change.

### D2: Remove the `PCloudConfig` Protocol (collapse into the concrete class)

**Decision.** Delete `class PCloudConfig(Protocol)` from `protocols.py`.
Retype `CreateNodeCallable.__call__`'s `cloud_config` parameter from
`Optional[PCloudConfig]` to `Optional[CloudInitConfig]`. Retype the five
provider `*_create_node` callables' `cloud_config` parameters from
`PCloudConfig | None` to `CloudInitConfig | None`. Retype
`manager.py:267` `_get_cloud_config_data`'s return annotation from
`PCloudConfig` to `CloudInitConfig`, and the `return CloudConfig(...)` constructor
call at `manager.py:283` to `return CloudInitConfig(...)`. All in one pass.

The Protocol earned its keep only if either (a) there were multiple structural
implementers, or (b) it was used for runtime dispatch. Neither holds:

- (a) Exactly one structural impl (`infra/cloud/cloud_init.CloudInitConfig`,
  formerly `cloud_config.CloudConfig`). Grep `def render_base64` → 2 hits:
  the Protocol declaration and the sole impl.
- (b) NOT `@runtime_checkable`; zero `isinstance(x, PCloudConfig)` calls;
  zero test stubs/fakes. The Protocol is invisible at runtime.

**Variance mechanics — why the one-pass retyping is sound.**

`CreateNodeCallable` is declared
`Protocol[TConfigCloud_contra]` and the assignment
`create_node=az_create_node` at `adapters.py:112` must typecheck. Under the
current shape:

```
CreateNodeCallable.__call__(cloud_config: Optional[PCloudConfig])   ← wide (Protocol)
az_create_node         (cloud_config: PCloudConfig | None)          ← wide (Protocol)
                                                                       ↑ assignable: identical accepted set
```

Under the new shape:

```
CreateNodeCallable.__call__(cloud_config: Optional[CloudInitConfig]) ← narrow (concrete)
az_create_node         (cloud_config: CloudInitConfig | None)        ← narrow (concrete)
                                                                       ↑ assignable: identical accepted set
```

Both sides move together; the `az_create_node` → `CreateNodeCallable` assignment
stays valid because the accepted input sets remain identical to each other on
each side. The retyping NARROWS both sides symmetrically — it does not widen
one and narrow the other (which would violate callable contravariance). Hence
no `# type: ignore[assignment]` and no `cast(CreateNodeCallable, ...)` is
introduced.

**Why this must be one pass, not incremental.** If `CreateNodeCallable.__call__`
were retyped to `Optional[CloudInitConfig]` while a provider `*_create_node`
still accepted `PCloudConfig | None`, the provider's accepted set would be a
SUPERSET of `CreateNodeCallable`'s — assignable (the wider function
substitutes for the narrower contract). But the *reverse* intermediate
(provider retyped to `CloudInitConfig | None` while `CreateNodeCallable` still
accepts `PCloudConfig | None`) would make the provider's accepted set a SUBSET
— a contravariance violation, requiring a `# type: ignore` or `cast` at
`adapters.py:112`. To avoid both intermediate states, all six call-site
signatures (`CreateNodeCallable.__call__` + 5 providers) are retyped in the
same change. The `manager.py:267` return annotation and `manager.py:283`
constructor call are also retyped in the same pass (not for variance — they
are returns, not callable params — but because they reference `PCloudConfig`/
`CloudConfig` and would otherwise leave dangling references to the deleted
Protocol / renamed class).

**Why not keep the Protocol "just in case"** (YAGNI counter-argument): the
Protocol has had exactly one impl for the entire tracked history (verified via
`git log -L` style grep). A future second impl would re-introduce a Protocol,
but that Protocol would be designed against the actual second impl's needs, not
the imagined needs encoded in the current `PCloudConfig`. Keeping a
single-implementer Protocol "for extensibility" is the textbook YAGNI cost:
the Protocol adds a layer of indirection and a self-referential seam
(`PCloudConfig` referenced by `CreateNodeCallable` which is implemented by
providers typed against `PCloudConfig`) with zero current benefit.

### D3: Delete `CloudCapacity` (dead code)

**Decision.** Delete `@dataclass(frozen=True) class CloudCapacity` from
`protocols.py`. Drop the two `__init__.py` re-exports
(`from .protocols import (... CloudCapacity ...)`, `__all__: "CloudCapacity"`).
Update the `SCOPE`/`MODULE_MAP` lines in `protocols.py`'s GRACE contract.

**Death verification.**
- `rg -n 'CloudCapacity\(' yascheduler/` → 0 construction sites outside
  archives (the only matches are in `openspec/changes/archive/**`).
- `rg -n ': CloudCapacity|-> CloudCapacity' yascheduler/` → 0 annotation
  sites in source. (Matches in `tests/` are exclusively
  `CloudCapacityExhaustedError`, a domain exception in
  `domain/exceptions.py:129` — unrelated, NOT a `CloudCapacity` consumer.)
- `Orchestrator._clouds_get_capacity` (the conceptual successor) returns `int`
  (`orchestrator.py:434`), not `CloudCapacity`.

**Lineage.** Pre-`cloud-provisioner-pure` (2026-06-22),
`CloudAPIManager.get_capacity()` returned `CloudCapacity(name, max, current)`.
That change deleted `get_capacity()` and rewrote the capacity computation as
an inline `Orchestrator._clouds_get_capacity() -> int`. The dataclass survived
the deletion (orphaned), then was *migrated* attrs→dataclass in
`migrate-cloud-from-attrs` as busywork (the archive's tasks.md item 1.1
literally migrates a class with no consumers), then survived
`cloud-configs-to-infra-registry` (also mechanically). The FIXME at line 93 is
the first time the question "is this still used?" was posed since
`cloud-provisioner-pure`.

**Public surface.** User-confirmed not public. Not in the AGENTS.md stability
enumeration (CLI commands, `class Yascheduler` public API, INI config format,
DB schema, AiiDA entrypoint). Present in `infra/cloud/__init__.py.__all__` and
in the `package-facades` spec's "Existing re-exports ... preserved" snapshot
(line 455 of the current spec). The spec phrasing is a snapshot, not a vow;
removing a genuinely-dead re-export is a delta-spec edit, not a stability
breach.

### D4: Drop the D3a `isinstance` boundary guard in `az_create_node`

**Decision.** Delete the guard at `az.py:329-337`:

```python
# Boundary guard: narrow the public PCloudConfig-typed parameter to the
# concrete infra CloudConfig that create_node/_render_custom_data expect.
# Azure never sees a non-CloudConfig PCloudConfig impl in this codebase;
# ...
if cloud_config is not None and not isinstance(cloud_config, CloudConfig):
    raise TypeError(
        f"az_create_node expects infra CloudConfig, got "
        f"{type(cloud_config).__name__}"
    )
```

**Why redundant after D1+D2.** The guard existed solely to bridge the public
`az_create_node(cloud_config: PCloudConfig | None)` param to the internal
`create_node(cloud_config: CloudConfig | None)` / `_render_custom_data(...)`
params — i.e., to narrow a Protocol-typed input to the concrete class the
internals expect. With D2, the public param is retyped to `CloudInitConfig |
None` and the internals are retyped to `CloudInitConfig | None` (already done by
D3a's deep work — they were `CloudConfig | None`, now `CloudInitConfig | None`
post-rename). Both sides are the same concrete class; the runtime
discrimination the guard performed is structurally impossible to trigger
(no `PCloudConfig`-typed value can reach `az_create_node` anymore). The guard's
`TypeError` would never fire.

**Defense-in-depth consideration.** `resolve-type-bridge-debt`'s design.md
called the guard "defense-in-depth, not a contract restriction" (risk
mitigation for D3a, lines 419-422). That defense was warranted WHILE the
public param was the wide Protocol; a foreign `PCloudConfig` impl could in
principle have flowed in. With the Protocol removed, there is no foreign impl
to defend against — `PCloudConfig` ceases to exist. The defense's premise
vanishes; the guard becomes dead code that lies about a risk that can no
longer materialize. Keeping it would be the opposite of defense-in-depth: a
runtime check asserting a property (`isinstance(x, CloudInitConfig)`) that the
type system already guarantees at the call site.

### D5: Knowledge-graph node rename `M-CLOUD-CONFIG` → `M-CLOUD-INIT`

**Decision.** In `docs/knowledge-graph.xml`, the existing `<M-CLOUD-CONFIG
NAME="Cloud config dataclass" ...>` node (singular — the renderer, at lines
752-759) is renamed to `<M-CLOUD-INIT ...>`. Updates:

- Tag: `M-CLOUD-CONFIG` → `M-CLOUD-INIT`
- `NAME`: "Cloud config dataclass" → "Cloud-init renderer dataclass"
- `<purpose>`: "...PCloudConfig for cloud-init rendering." →
  "...the concrete cloud-init user-data renderer (bootcmd, packages,
  package_upgrade, render, render_base64)."
- `<path>`: `yascheduler/infra/cloud/cloud_config.py` →
  `yascheduler/infra/cloud/cloud_init.py`
- `<annotations><class-CloudConfig PURPOSE="..."/>` →
  `<class-CloudInitConfig PURPOSE="..."/>`

**No `CrossLink` changes** — `M-CLOUD-CONFIG` had zero CrossLinks (grep-confirmed). But it DOES have one incoming `<depends>` edge: `M-CLOUD-PROVISIONER` (the cloud provisioner module at `infra/cloud/manager.py`) lists `M-CLOUD-CONFIG` in its `<depends>` at line 703 of `docs/knowledge-graph.xml`. That single reference is updated in the same change: line 703's `M-CLOUD-CONFIG` → `M-CLOUD-INIT` (it sits between `M-CLOUD-PROVIDER-SELECTION,` and `M-CLOUD-CONFIGS,` — both untouched). No other `<depends>` list references the singular node (grep-confirmed via `rg -n 'M-CLOUD-CONFIG\b'` with the word boundary, which correctly excludes the plural `M-CLOUD-CONFIGS`). The rename is therefore a relabel plus one incoming-edge update; zero ripple beyond that single depends line.

The `<depends>` of `M-CLOUD-CONFIG` is `none` in the current graph and stays `none` after the rename. (Today the module also imports `from .protocols import PCloudConfig` for its base-class list; after D2 deletes `PCloudConfig`, the renamed `cloud_init.py` imports only stdlib `base64`, `json`, `dataclasses` — so the `none` dependency posture becomes literally true. The current graph entry predates the `PCloudConfig` import and was already `none`; this change makes the graph and the code agree.)

**`M-CLOUD-PROTOCOLS` annotations update.** The node at lines 740-750
(`M-CLOUD-PROTOCOLS`) lists `PCloudConfig`, `CreateNodeCallable`,
`DeleteNodeCallable`, `SupportedPlatformChecker`, `CloudCapacity`, TypeVars in
its annotations. After D2+D3, the `PCloudConfig` and `CloudCapacity` entries
are removed; `CreateNodeCallable` / `DeleteNodeCallable` /
`SupportedPlatformChecker` annotations remain; the TypeVars remain (they are
bound to `ConfigCloud`, which is unaffected).

**`M-CLOUD-CONFIGS` (plural — the DTO module) UNTOUCHED.** The user's decision
#3 was explicit: this is a rename of the singular node, not a new node
alongside. `M-CLOUD-CONFIGS` keeps its `NAME`, `<path>`,
`<depends>M-DOMAIN-PORTS</depends>`, and all `<annotations>` unchanged.

### D6: No new test files; minimal test touch

**Decision.** No new test files created. The rename touches exactly one
existing test file: `tests/unit/test_cloud_provisioner_impl.py` (line 41:
`from yascheduler.infra.cloud.cloud_config import CloudConfig` →
`from yascheduler.infra.cloud.cloud_init import CloudInitConfig`, plus any
`CloudConfig(...)` constructions and `isinstance`/`__mro__` references to the
class in that file).

**Why no new tests.** The change is a pure rename + Protocol collapse +
dead-class deletion — zero new behavior, zero new branches, zero new contract
surface. The existing `test_cloud_provisioner_impl.py` exercises the renderer
through the `CloudConfig(...)` / `render()` / `render_base64()` path; after the
rename it exercises `CloudInitConfig(...)` / `render()` / `render_base64()`
through the identical path. Adding a test that asserts "`CloudInitConfig`
exists" would be tautological; adding a test that asserts "`PCloudConfig` does
not exist" is a grep, already covered by the verification step
(`rg -n 'PCloudConfig\b' yascheduler/` → zero).

**No `test_cloud_config_protocol_inheritance.py` change.** That test (created
by `resolve-type-bridge-debt` task 1.6) tests the DOMAIN `CloudConfig` Protocol
inheritance by the `ConfigCloud*` DTOs — Concept A. It does NOT reference
`infra/cloud/cloud_config.CloudConfig` (Concept B) or `PCloudConfig`. Verified:
line 29 imports `from yascheduler.domain import CloudConfig`, line 30 imports
`ConfigCloud*` from `.cloud_configs`. This change leaves the test untouched.

## Risks / Trade-offs

- **[Risk] A future contributor adds a second `PCloudInitConfig`-shaped class
  and has to re-introduce a Protocol.**
  → Mitigation: the future Protocol would be designed against the second
  impl's actual needs, not the current single-impl shape. Keeping the
  Protocol now "just in case" encodes imaginary requirements; removing it now
  and re-adding it when real is the cheaper path. The `cloud-provisioner`
  delta spec's "Concrete renderer class" Scenario documents that
  `CloudInitConfig` is the single renderer; a second impl would be a visible
  signal to revisit the Protocol decision.

- **[Risk] Variance: if a single provider's `*_create_node` is retyped in a
  different change from `CreateNodeCallable.__call__`, an intermediate state
  has a contravariance violation at `adapters.py:112`.**
  → Mitigation: D2 mandates the six signatures (`CreateNodeCallable.__call__`
  + 5 providers) are retyped in ONE atomic change. The tasks.md enforces this
  by grouping all six retypings into a single task group with no intervening
  `zuban check` gate. There is no incremental landing path.

- **[Risk] Removing the D3a `isinstance` guard re-opens the foreign-impl hole
  that `resolve-type-bridge-debt`'s design.md risk-mitigated.**
  → Mitigation: D4 documents that the guard's premise (a `PCloudConfig`-typed
  value reaching `az_create_node`) is structurally impossible after D2 —
  `PCloudConfig` ceases to exist. The guard becomes dead code that asserts a
  property the type system already guarantees. Keeping dead defense would be
  worse than removing it (the lie about a non-existent risk).

- **[Risk] The `from yascheduler.infra.cloud import CloudConfig` import path
  breaks an external consumer.**
  → Mitigation: `CloudConfig` (the renderer) is not in the AGENTS.md public-API
  stability enumeration (CLI, `Yascheduler` class, INI, DB, AiiDA). Grep
  confirmed zero references outside `yascheduler/` and `tests/`. The
  `package-facades` spec re-export is updated in the same change. If an
  external consumer exists unbeknownst, the error surfaces as an
  `ImportError` with an actionable message (the new name
  `CloudInitConfig` is discoverable via `dir(yascheduler.infra.cloud)`); the
  fix is a one-line import rename on the consumer side.

- **[Risk] The `# type: ignore[arg-type]` at `az.py:235`
  (`dataclass_asdict(vm_image)`) interacts with the rename.**
  → Mitigation: that ignore is on `AzureImageReference` (a `ConfigCloud*`-adjacent
  DTO in `cloud_configs.py`), NOT on `CloudConfig`/`CloudInitConfig`. The rename
  does not touch `AzureImageReference`; the ignore stays as-is. Out of scope.

- **[Trade-off] The one-pass retyping means the change cannot be split into
  smaller reviewable chunks.**
  → Accepted: the alternative (incremental landing with intermediate
  `# type: ignore` placeholders) introduces the very debt this change removes.
  The six retypings are mechanical and reviewable as a single diff; the
  variance argument (D2) is the substance to review.

- **[Trade-off] `CloudInitConfig` is a slightly longer name than `CloudConfig`.**
  → Accepted: the extra 4 characters buy unambiguous disambiguation from the
  domain `CloudConfig` Protocol. The collision cost (real past confusion,
  three FIXMEs) dwarfs the readability cost.

## Migration Plan

This is a pure rename + Protocol-collapse + dead-code-deletion change; no
data, config, or deployment migration. No deprecation window (no external
published API).

1. **Apply D1** (file rename + class rename in `cloud_init.py`). Run
   `uv run ruff check .` — confirm no import errors from the rename.
2. **Apply D2** (delete `PCloudConfig`; retype the 6 signatures
   `CreateNodeCallable.__call__` + 5 providers — all in one task group, no
   intervening gates). Run `uv run zuban check` — confirm zero contravariance
   errors at `adapters.py:112` and zero `PCloudConfig` references anywhere.
3. **Apply D3** (delete `CloudCapacity`; drop the two `__init__.py` re-exports;
   update `protocols.py` GRACE headers). Run
   `rg -n 'CloudCapacity\b' yascheduler/` → zero (excluding
   `CloudCapacityExhaustedError`).
4. **Apply D4** (delete the D3a isinstance guard at `az.py:329-337`). Run
   `uv run pytest -m unit` — confirm `test_cloud_provisioner_impl.py` passes
   with the renamed import.
5. **Apply D5** (knowledge-graph node rename + `M-CLOUD-PROTOCOLS` annotations
   trim). Run `python3 scripts/grace_check.py`.
6. **Update `cloud-provisioner` and `package-facades` delta specs** (per the
   proposal's Modified Capabilities). Run `openspec validate --all --json`.
7. **Final verification**: `uv run pytest -m unit`, `uv run zuban check`,
   `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run lint-imports`, `openspec validate --all --json`,
   `python3 scripts/grace_check.py`,
   `rg -n 'PCloudConfig\b' yascheduler/` → zero,
   `rg -n 'CloudCapacity\b' yascheduler/` → zero (excl.
   `CloudCapacityExhaustedError`).

**Rollback:** `git revert` the change commit. No data rollback (no data
touched). The rollback restores `PCloudConfig`, `CloudCapacity`, the D3a
guard, and the `cloud_config.py` / `CloudConfig` names — i.e., the
pre-change debt state. No regression beyond restoring the status quo ante.

## Open Questions

None. The five decisions are self-contained; the variance mechanics (D2) are
mechanical; the dead-code proofs (D3) are grep-verified; the redundancy
argument (D4) follows deductively from D2; the knowledge-graph rename (D5) has
minimal graph ripple (one incoming `<depends>` edge from `M-CLOUD-PROVISIONER` at line 703, updated in the same change; zero CrossLinks). The sequencing constraint
(after `resolve-type-bridge-debt` archive) is satisfied (confirmed at
`openspec/changes/archive/2026-06-26-resolve-type-bridge-debt/`).