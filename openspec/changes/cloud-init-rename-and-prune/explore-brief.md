# Explore Brief — cloud-init-rename-and-prune

## Origin

Three FIXMEs in the cloud protocols area, exposed during the
`resolve-type-bridge-debt` work (now partially archived):

1. `infra/cloud/protocols.py:48` — `# FIXME: is this really needed? how many
   consumers?` on `PCloudConfig` Protocol.
2. `infra/cloud/protocols.py:93` — `# FIXME: dead code?` on `CloudCapacity`
   dataclass.
3. `infra/cloud/cloud_config.py:19` — `# FIXME: very bad naming of module and
   class (we already have cloud configs)`.

The third FIXME names the root cause: a name collision between two genuinely
different concepts living in adjacent modules.

## Root cause: name collision

Three distinct things, two names, one letter of filename difference:

```
CONCEPT A (cloud PROVIDER connection config):
  infra/cloud/cloud_configs.py    ConfigCloudAzure, ConfigCloudHetzner,
                                  ConfigCloudUpcloud, ConfigCloudVastAI
  domain/ports.py                 CloudConfig (Protocol, @runtime_checkable)
  infra/cloud/cloud_configs.py    ConfigCloud = Union[...]

CONCEPT B (cloud-init user-data renderer):
  infra/cloud/protocols.py:49      PCloudConfig (Protocol, NOT @runtime_checkable)
  infra/cloud/cloud_config.py:32  CloudConfig (dataclass, sole PCloudConfig impl)

ORPHAN:
  infra/cloud/protocols.py:95      CloudCapacity (dead dataclass)
```

`cloud_config.py` (singular) and `cloud_configs.py` (plural) differ by one
letter; the singular file holds a class `CloudConfig` which is NOT one of the
things in the plural file. Plus the domain layer has its own unrelated
`CloudConfig` Protocol. Three concepts share two names.

## Investigation findings

### PCloudConfig — single-implementer, zero runtime polymorphism

- Sole structural implementer: `infra/cloud/cloud_config.CloudConfig`.
- NOT `@runtime_checkable` → `isinstance(x, PCloudConfig)` would raise
  `TypeError` at runtime. Zero `isinstance` calls exist (confirmed by grep).
- Zero test stubs/fakes implementing it.
- 16 occurrences total: 1 definition, 1 base-class use (runtime), 1
  `CreateNodeCallable.__call__` param, 8 provider param annotations (static),
  1 manager return annotation, 2 facade re-exports, ~6 contract comments.
- Runtime flow: `_get_cloud_config_data` returns concrete `CloudConfig`; passes
  through provider `create_node` typed as `PCloudConfig | None`; reaches
  `_render_custom_data`. Zero branching on the Protocol.
- The "necessity" is a closed loop: `PCloudConfig` is needed because
  `CreateNodeCallable.__call__` references it; nothing else references the
  Protocol for runtime behavior.

### CloudCapacity — confirmed dead

- Defined: `protocols.py:95` (fields: `name`, `max`, `current`).
- Constructed: nowhere (rg `CloudCapacity\(` → 0 hits outside archives).
- Annotated: nowhere (no `: CloudCapacity` or `-> CloudCapacity` in source).
- Tests: only `CloudCapacityExhaustedError` (unrelated exception).
- Lineage: pre-`cloud-provisioner-pure` (2026-06-22), `clouds.get_capacity()`
  returned `CloudCapacity`; that change deleted `get_capacity()` and rewrote
  `_clouds_get_capacity` to return `int`. The dataclass was migrated
  attrs→dataclass in `migrate-cloud-from-attrs` (busywork) and survived the
  config relocation — never re-queried for necessity. The FIXME is the first
  such query.
- Not public: user-confirmed. Not in the AGENTS.md stability surface
  enumeration (CLI, `Yascheduler` class API, INI, DB schema, AiiDA). Listed in
  `infra/cloud/__init__.py` `__all__` and in the `package-facades` spec's
  "Existing re-exports ... preserved" snapshot — but those are snapshots, not
  vows. Removal is a delta-spec edit.

### Naming — the real fix

Renaming Concept B (the renderer) is the honest path. Concept A (provider
configs) is too widely referenced to rename cheaply; Concept B has a small,
bounded surface. Honest names: `CloudInitConfig` / `PCloudInitConfig` /
`cloud_init.py`. Removing `PCloudConfig` simultaneously (since the Protocol
adds zero value) collapses the self-referential closed loop and leaves a
single concrete class with an honest name.

## Final approach (chosen over alternatives)

### Rename + Protocol removal + dead-class deletion, in ONE change

```
Part 1 — RENAME Concept B:
  cloud_config.py → cloud_init.py (file rename)
  class CloudConfig → class CloudInitConfig (no base class)
  manager.py:267 return type → CloudInitConfig
  az.py:78 import + ~4 annotations
  hetzner.py import + 1 annotation
  upcloud.py import + 2 annotations
  vastai.py import + 1 annotation
  __init__.py re-export CloudConfig → CloudInitConfig
  test_cloud_provisioner_impl.py:41 import + isinstance guard
  package-facades spec: rename re-export

Part 2 — REMOVE PCloudConfig:
  protocols.py:49 delete class
  protocols.py:75 CreateNodeCallable.__call__ → Optional[CloudInitConfig]
  cloud_init.py base class (PCloudConfig) dropped (done in Part 1)
  az.py:322 az_create_node public param → CloudInitConfig | None
  az.py:333-337 delete the isinstance guard (redundant: both sides concrete)
  hetzner/upcloud/vastai annotations → CloudInitConfig | None
  __init__.py:63,83 delete PCloudConfig re-export
  package-facades spec: drop PCloudConfig from re-export list

Part 3 — DELETE CloudCapacity:
  protocols.py:93-100 delete class
  __init__.py:60,72 delete re-export ×2
  protocols.py GRACE: update SCOPE/MODULE_MAP lines
  package-facades spec: drop CloudCapacity from re-export list
```

### Variance mechanics (why this works)

Replacing `Optional[PCloudConfig]` with `Optional[CloudInitConfig]` in
`CreateNodeCallable.__call__` narrows the accepted set. Symmetrically retyping
all 5 provider `*_create_node` callables' `cloud_config` param to
`Optional[CloudInitConfig]` keeps the `create_node=az_create_node` assignment
valid (identical accepted sets, no contravariance violation). This is a
coordinated retyping — must land in one pass, not incrementally.

The `isinstance` boundary guard at `az.py:333` (added by
`resolve-type-bridge-debt` D3a as a bridge between the public `PCloudConfig`
param and the internal `CloudConfig` param) becomes redundant when both sides
are the concrete class. Deleting the Protocol deletes the seam → deletes the
guard.

### Why one combined change (not three)

- Renaming Concept B without removing the Protocol leaves a self-referential
  `PCloudInitConfig`-references-`PCloudInitConfig` seam — rename incomplete.
- Removing the Protocol without renaming leaves `cloud_config.py` /
  `CloudConfig` colliding with the domain Protocol — the root FIXME unsolved.
- The rename makes the Protocol removal readable; the Protocol removal makes
  the rename complete. They reinforce each other.
- `CloudCapacity` deletion is the smallest standalone win and rides along
  cheaply while `protocols.py` and `__init__.py` are open.

## Decided parameters

| Parameter | Value |
|---|---|
| `Optional` style | any (project already mixes both; not load-bearing) |
| Spec delta location | add requirement to existing `cloud-provisioner` capability profile |
| Knowledge graph M-node | rename `M-CLOUD-CONFIG` (singular, the renderer) → `M-CLOUD-INIT`; do NOT add a new node alongside. `M-CLOUD-CONFIGS` (plural, the DTO module) is untouched. |
| Sequencing | AFTER `resolve-type-bridge-debt` archive (already done — confirmed at `openspec/changes/archive/2026-06-26-resolve-type-bridge-debt/`) |

## Cross-module data flow (final shape)

```
_get_cloud_config_data (manager.py) -> CloudInitConfig  (concrete)
        │
        ▼
az_create_node(cloud_config: CloudInitConfig | None)   (concrete param)
  └─ no isinstance guard (both sides concrete)
        │
        ▼
create_node / create_vm_params / _render_custom_data
  (cloud_config: CloudInitConfig | None)  (concrete param)
        │
        ▼
dataclasses.replace(cloud_config, bootcmd=...) -> CloudInitConfig  (concrete return)
        │
        ▼
.render_base64() -> str   (no # type: ignore needed)
```

Zero Protocol indirection in the flow. The `PCloudConfig → Concrete` retyping
also removes the need for the D3a boundary guard — a side-benefit cleanup
landed by this change.

## Open questions

None remaining. The three architectural decisions (rename Concept B; remove
`PCloudConfig`; delete `CloudCapacity`) are mutually reinforcing and sequenced
behind an archived predecessor. The variance mechanics are mechanical but
must be coordinated in one pass.