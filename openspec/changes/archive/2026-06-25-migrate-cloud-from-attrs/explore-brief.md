# Explore Brief — migrate-cloud-from-attrs

## Decision context

`yascheduler/infra/cloud/` uses `attrs` (`@define(frozen=True)`) for four
record classes and one provider module. The project is incrementally
migrating away from `attrs` toward stdlib `dataclasses`; two precedents
already exist (`queue-dataclass-migration`, `migrate-ssh-platform-from-attrs`).
Two `# FIXME: migrate from attrs to dataclasses` markers are already in
`infra/cloud/adapters.py:28` and `config/config.py:21`. This change migrates
the cloud layer as the next step.

## Scope

- **In scope**: 5 files in `yascheduler/infra/cloud/` migrate fully
  (`adapters.py`, `cloud_config.py`, `protocols.py`, `manager.py`,
  `__init__.py`); `providers/az.py` becomes hybrid; one canary unit test in
  `tests/unit/test_cloud_provisioner_impl.py`; one spec delta on
  `openspec/specs/cloud-providers/spec.md`.
- **Out of scope**: `yascheduler/config/*` (8 attrs files — separate future
  change, heavier attrs usage: `validators`, `converters`, `Attribute`,
  `fields()`); `AzureImageReference` in `config/cloud.py` (stays attrs);
  removing `attrs>=22.2.0` from `pyproject.toml`; bumping `requires-python`;
  any public-API change; DB schema; CLI; AiiDA entrypoint.

## Rejected alternatives

- **Migrate everything including `config/*` in one change**: rejected —
  `config/utils.py`, `config/cloud.py`, `config/engine.py` are heavily
  coupled to attrs (`validators`, `converters`, `Attribute`, `fields()`,
  `asdict`, `evolve`); one change has too much blast radius and too many
  semantic pitfalls per module. Do it as separate changes per package.
  (Same rejection as `queue-dataclass-migration` precedent.)
- **Leave `az.py` fully attrs (don't touch evolve there)**: rejected —
  `evolve()` in `az.py` operates on `CloudConfig`, which this change migrates
  to a dataclass; `attrs.evolve` works on attrs classes only. Must switch to
  `dataclasses.replace`. `az.py` becomes a deliberate hybrid (keeps
  `attrs.asdict` for the out-of-scope `AzureImageReference`).
- **`@dataclass(frozen=True, slots=True)`**: rejected — `slots=True`
  requires Python 3.10; project minimum is `>=3.9`. Both precedents avoid
  `__slots__` for these migration targets (singletons / runtime objects,
  marginal gain, compat cost). No `__slots__` added here either.
- **Custom `__eq__`/`__hash__`**: rejected — unlike `UMessage` (id-only eq),
  no cloud dataclass has a custom equality invariant. Stdlib frozen-dataclass
  defaults (all-field `__eq__`, all-field `__hash__`) match attrs
  `@define(frozen=True)` defaults. No tests assert eq/hash on cloud dataclasses.

## Final approach — labels / dimensions

- **Migration target**: 4 classes (`CloudAdapter`, `CloudConfig`,
  `CloudCapacity`, `CloudProvisionerImpl`) across 4 files; 1 hybrid file
  (`providers/az.py`); 1 facade file (`__init__.py`) metadata-only.
- **Decorator**: `@dataclass(frozen=True)` everywhere a class is migrated.
- **No `__slots__`**: Py 3.9 minimum; no precedent; no measurable gain.
- **`asdict` split**: `cloud_config.py` switches to `dataclasses.asdict`
  (CloudConfig becomes a dataclass). `az.py` KEEPS `attrs.asdict` — needed
  for `AzureImageReference` (config/cloud.py, out of scope, stays attrs).
- **`evolve` → `replace`**: single call site in `az.py:205`.
- **`attr` typo fix**: `protocols.py:35` `from attr import define` (no 's')
  removed entirely (class migrates; import gone).
- **`pyproject.toml`**: `attrs>=22.2.0` STAYS — still needed by `config/*`
  and `az.py`.
- **Knowledge graph**: NO edit. `M-CLOUD-*` records unchanged (same classes,
  names, deps). Only `CHANGE_SUMMARY` entries in source files (precedent:
  `queue-dataclass-migration` — "No graph edit required").
- **Version bumps**: minor bump all 6 touched files (1.1.1→1.2.0 etc.),
  consistent with both precedents (`queue.py` 1.7.0→1.8.0;
  `ssh/platform/adapters.py` 1.0.1→1.1.0).

## Mechanical mapping (per file)

| Before (attrs)                                | After (dataclasses)                              |
| ---------------------------------------------- | ------------------------------------------------ |
| `from attrs import define, field`              | `from dataclasses import dataclass, field`       |
| `from attr import define` (typo, protocols.py) | (removed)                                        |
| `@define(frozen=True)`                         | `@dataclass(frozen=True)`                        |
| `field()` (no args)                            | bare annotation                                  |
| `field(factory=tuple)`                         | `field(default_factory=tuple)`                   |
| `field(default=False)`                         | `field(default=False)`                           |
| `field(factory=asyncio.Lock, init=False)`      | `field(default_factory=asyncio.Lock, init=False)` |
| `evolve(obj, **kw)` (az.py)                     | `replace(obj, **kw)` + `# type: ignore[misc]`    |
| `attrs.asdict(self)` (cloud_config.py)         | `dataclasses.asdict(self)`                       |
| `attrs.asdict(vm_image)` (az.py)               | STAYS `attrs.asdict` (AzureImageReference)      |

## The asdict divergence — empirically verified

Ran a script comparing `attrs.asdict` vs `dataclasses.asdict` on the
`CloudConfig` shape (`bootcmd: tuple[Union[str, list[str]], ...]`,
`packages: list[str]`, `package_upgrade: bool`):

```
attrs.asdict(AC) → {"bootcmd": ("a",["b"]), "packages": ["vim"], "pkg_up": False}
dc.asdict(DC)    → {"bootcmd": ("a",["b"]), "packages": ["vim"], "pkg_up": False}
json.dumps(...)  → byte-identical (tuple and list serialize the same)
```

`render()` output is byte-identical across implementations. No behavioral
risk in `cloud_config.py:41` (`json.dumps(asdict(self))`). The canary test
guards against future regressions of this property.

## Cross-module data flow

```
  yascheduler/entrypoints/di.py
    │ constructs CloudProvisionerImpl(adapters=..., configs=..., ...)  [kwarg-only, signature preserved]
    ▼
  yascheduler/infra/cloud/manager.py     ← CloudProvisionerImpl MIGRATED (attrs → dataclass)
    │
    ├── .cloud_config.CloudConfig        ← MIGRATED (attrs → dataclass); dataclasses.asdict now
    ├── .adapters.CloudAdapter           ← MIGRATED (attrs → dataclass)
    └── .protocols.CloudCapacity          ← MIGRATED (attrs → dataclass)

  yascheduler/infra/cloud/providers/az.py  ← HYBRID after migration:
    ├── replace(cloud_config, bootcmd=...)  ← dataclasses.replace (CloudConfig is dataclass)
    │   # type: ignore[misc]  ← cloud_config: PCloudConfig (Protocol) doesn't satisfy _DataclassT bound
    └── asdict(vm_image)                   ← STAYS attrs.asdict (AzureImageReference in config/cloud.py)

  tests/unit/test_cloud_provisioner_impl.py
    ├── make_provisioner() constructs CloudProvisionerImpl(**kwargs)  [unchanged]
    ├── TestSelectProvider uses MagicMock(spec=CloudAdapter)          [spec works on dataclass]
    └── TestCloudConfigGeneration + NEW test_cloud_config_render_serializes  [canary]

  No other module imports the migrated classes by deep path; facade
  `yascheduler/infra/cloud/__init__.py` re-exports preserved (__all__ unchanged).
```

## Canary test (T1)

Add `test_cloud_config_render_serializes` to the existing
`TestCloudConfigGeneration` class in
`tests/unit/test_cloud_provisioner_impl.py` (NOT a new file):

- Construct `CloudConfig(bootcmd=("echo hi", ["mkdir", "/x"]),
  package_upgrade=True, packages=["vim", "htop"])`.
- Call `render()`.
- Assert the result starts with `"#cloud-config\n"`.
- `json.loads` the payload after the prefix.
- Assert `bootcmd == ["echo hi", ["mkdir", "/x"]]` (JSON-normalized tuple→list).
- Assert `packages == ["vim", "htop"]`.
- Assert `package_upgrade is True`.

Guards against `asdict`-implementation regression (the only path where the
attrs↔dataclasses divergence could surface). `render_base64()` just
base64-encodes `render()` output — covering `render()` covers both.

## Spec delta

Target: `openspec/specs/cloud-providers/spec.md`.
Operation: `MODIFIED` on "Support modules relocated" requirement.

- Fix stale import path (was stale before this change, same requirement
  section, naturally part of the MODIFICATION):
  `WHEN CloudAdapter is imported from adapters.cloud.adapters`
  → `WHEN CloudAdapter is imported from yascheduler.infra.cloud.adapters`
- Add a new scenario codifying the render contract the canary enforces:
  `WHEN CloudConfig.render() is called on a frozen dataclass instance`
  `THEN the output is a "#cloud-config\n"-prefixed JSON of all fields`
  `AND is byte-identical to the prior attrs-backed implementation`

The other stale paths in "Provider code relocated" (lines 16/20/24:
`adapters.cloud.providers.*`) are deliberately left out — they were stale
before this change and are not caused by it.

## Known risks / pitfalls

1. **`replace()` type error in `az.py`** (caught by k-reviewer-fast pre-proposal
   review): `dataclasses.replace` is typed
   `def replace(obj: _DataclassT, /, **changes) -> _DataclassT` where
   `_DataclassT` is bound to `DataclassInstance`. The call site
   `evolve(cloud_config, bootcmd=[...])` → `replace(cloud_config, ...)` has
   `cloud_config: PCloudConfig` (a Protocol), which does NOT satisfy
   `_DataclassT`. Zuban emits
   `error: Argument 1 to "replace" has incompatible type "PCloudConfig";
   expected a dataclass [misc]`. **Fix**: add `# type: ignore[misc]` to the
   `replace()` call. (Current `evolve()` call is untyped `(*args: Any,
   **changes: Any)` so no error today — this is a NEW error introduced by
   the migration, not a pre-existing one.)
2. **`type: ignore[arg-type]` in `cloud_config.py:41`**: try removing after
   switching to `dataclasses.asdict`; restore if `uv run zuban check` fails.
   Empirical expectation: `dataclasses.asdict(self)` on a frozen dataclass
   returns `dict[str, Any]` which `json.dumps` accepts cleanly — the ignore
   may become removable. Implementation detail, decided at apply time.
3. **`az.py:231` `asdict(vm_image)` type-ignore stays**: `vm_image` is
   `AzureImageReference` (attrs, out of scope); `attrs.asdict` remains; the
   existing `# type: ignore[arg-type]` is unchanged.

## Static checks after implementation

- `uv run zuban check` (must be green; `type: ignore[misc]` on az.py
  `replace()` call is the one new ignore)
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run lint-imports` (verifies `from attrs import` is GONE from the 4
  fully-migrated files; PRESENT in `az.py` as `from attrs import asdict`)
- `uv run pytest -m unit` (canary + existing tests pass)
- `python3 scripts/grace_check.py` (markup valid, file sizes within limits)
- `openspec validate --all --json` (spec delta valid)

## Open questions

None. All decisions captured above and confirmed with the user during
explore mode (Q1–Q11 resolved).