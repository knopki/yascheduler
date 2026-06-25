## Why

`yascheduler/infra/cloud/` uses `attrs` (`@define(frozen=True)`) for four
record classes and one provider module. The project is incrementally
migrating away from `attrs` toward stdlib `dataclasses` — two precedents
already exist (`queue-dataclass-migration`, `migrate-ssh-platform-from-attrs`)
— and two `# FIXME: migrate from attrs to dataclasses` markers are already
in the codebase (`infra/cloud/adapters.py:28`, `config/config.py:21`). This
change migrates the cloud layer as the next step, eliminating `attrs`
from `yascheduler/infra/cloud/` except where it must remain for an
out-of-scope attrs class.

## What Changes

- Migrate `CloudAdapter`, `CloudConfig`, `CloudCapacity`,
  `CloudProvisionerImpl` from `attrs.define(frozen=True)` to
  `dataclasses.dataclass(frozen=True)` in 4 files:
  `adapters.py`, `cloud_config.py`, `protocols.py`, `manager.py`.
- Mechanical mappings (precedent-consistent):
  - `from attrs import define, field` → `from dataclasses import dataclass, field`
  - `@define(frozen=True)` → `@dataclass(frozen=True)`
  - bare `field()` → bare annotation
  - `field(factory=tuple)` → `field(default_factory=tuple)`
  - `field(default=X)` → `field(default=X)` (unchanged)
  - `field(factory=asyncio.Lock, init=False)` → `field(default_factory=asyncio.Lock, init=False)`
- `cloud_config.py`: switch `attrs.asdict(self)` → `dataclasses.asdict(self)`
  in `render()`. The existing `# type: ignore[arg-type]` on this line may
  become removable — verify with `uv run zuban check` and restore if it fails.
- `providers/az.py` becomes **hybrid**: replace `attrs.evolve(cloud_config,
  bootcmd=...)` with `dataclasses.replace(cloud_config, bootcmd=...)` (CloudConfig
  becomes a dataclass); KEEP `attrs.asdict(vm_image)` (needed for
  `AzureImageReference` from `config/cloud.py`, which stays attrs and is out
  of scope). Add `# type: ignore[misc]` on the `replace()` call (see Impact).
- `protocols.py`: remove the existing `from attr import define` typo import
  (no 's'); class migrates so the import is gone entirely.
- Remove the `# FIXME: migrate from attrs to dataclasses` marker in
  `adapters.py:28`.
- Update GRACE-lite metadata on all 6 touched files: bump minor versions
  (1.1.1→1.2.0, etc.), add `CHANGE_SUMMARY` entries, refresh `MODULE_MAP`
  wording ("Frozen attrs class" → "Frozen dataclass") in `adapters.py`,
  `cloud_config.py`, and `infra/cloud/__init__.py`.
- Add one canary unit test `test_cloud_config_render_serializes` to the
  existing `TestCloudConfigGeneration` class in
  `tests/unit/test_cloud_provisioner_impl.py`, guarding the `render()`
  JSON output against `asdict`-implementation regression.
- One spec delta: `MODIFIED` on the "Support modules relocated" requirement
  in `openspec/specs/cloud-providers/spec.md`. The other stale import paths in
  "Provider code relocated" (`adapters.cloud.providers.*`) are not part of this
  change — they were stale before it and will be addressed in a follow-up.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `cloud-providers`: The "Support modules relocated" requirement is
  modified — fix a stale import path (`adapters.cloud.adapters` →
  `yascheduler.infra.cloud.adapters`) and add a new scenario codifying the
  `CloudConfig.render()` contract (byte-identical JSON output across the
  attrs→dataclass migration, enforced by the new canary test).

## Impact

**Affected code:**
- `yascheduler/infra/cloud/adapters.py` — `CloudAdapter` migrated
- `yascheduler/infra/cloud/cloud_config.py` — `CloudConfig` migrated; `asdict` switches to `dataclasses.asdict`
- `yascheduler/infra/cloud/protocols.py` — `CloudCapacity` migrated; `from attr import define` typo removed
- `yascheduler/infra/cloud/manager.py` — `CloudProvisionerImpl` migrated
- `yascheduler/infra/cloud/providers/az.py` — hybrid: `evolve`→`replace`, `asdict` stays attrs
- `yascheduler/infra/cloud/__init__.py` — metadata-only (MODULE_MAP wording, CHANGE_SUMMARY, version)
- `tests/unit/test_cloud_provisioner_impl.py` — +1 canary test in `TestCloudConfigGeneration`

**Public API stability:** No change. `infra/cloud/__init__.py` `__all__` is
unchanged — same class names, same signatures, same re-exports. These are
internal adapter-layer symbols (not part of the AGENTS.md-stabilized public
surface: CLI commands, `Yascheduler` client API, INI config, DB schema,
AiiDA entrypoint). No BREAKING changes.

**Dependencies:** `attrs>=22.2.0` STAYS in `pyproject.toml`. After this
change, `attrs` is still required by all of `yascheduler/config/*` (8 files,
future change) and by `providers/az.py` (`asdict` for `AzureImageReference`).

**Type-check impact:** One new `# type: ignore[misc]` is added in
`az.py` on the `replace(cloud_config, ...)` call. `dataclasses.replace` is
typed `def replace(obj: _DataclassT, /, **changes) -> _DataclassT` with
`_DataclassT` bound to `DataclassInstance`; the call site receives
`cloud_config: PCloudConfig` (a Protocol), which does not satisfy the
bound. The prior `attrs.evolve` call was untyped `(*args: Any, **changes:
Any)` so no error existed. The new ignore is the minimal, localized fix;
`PCloudConfig` stays a Protocol because callers pass arbitrary
`PCloudConfig`-shaped values (the only concrete impl, `CloudConfig`,
becomes a dataclass and remains the runtime instance).

**Knowledge graph:** No edit to `docs/knowledge-graph.xml`. `M-CLOUD-*`
records unchanged (same classes, names, dependencies). Only
`CHANGE_SUMMARY` entries in source files. (Precedent:
`queue-dataclass-migration` — "No graph edit required".)

**Behavior:** No observable behavior change. Empirically verified
`attrs.asdict` and `dataclasses.asdict` produce byte-identical `render()`
output for the `CloudConfig` shape; stdlib frozen-dataclass eq/hash defaults
match attrs frozen defaults; no test asserts custom eq/hash on cloud
dataclasses.