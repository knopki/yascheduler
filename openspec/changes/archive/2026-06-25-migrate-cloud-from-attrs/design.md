## Context

`yascheduler/infra/cloud/` uses `attrs` (`@define(frozen=True)`) for four
record classes — `CloudAdapter`, `CloudConfig`, `CloudCapacity`,
`CloudProvisionerImpl` — across four files, plus `providers/az.py` which
imports `attrs.asdict` and `attrs.evolve`. The project is incrementally
migrating away from `attrs` toward stdlib `dataclasses`. Two precedents
already executed:

- `queue-dataclass-migration` — `UMessage` (frozen, custom id-only eq):
  added manual `__eq__`/`__hash__`, `eq=False`, manual `__slots__`, 3 canary
  tests, spec deltas on `testing-infrastructure` + `testing-unit`.
- `migrate-ssh-platform-from-attrs` — `RemoteMachineAdapter` +
  `ProcessInfo`: pure mechanical migration, no spec delta, no `__slots__`.

This change is the third migration step, targeting the cloud adapter layer.
The cloud classes are simpler than `UMessage` (no custom equality invariant)
and use only the attrs features that dataclasses replace 1:1 (no `validators`,
`converters`, `Attribute`, `fields()`, `__attrs_post_init__`, `on_setattr`,
`metadata` — verified by grep across `yascheduler/infra/cloud/`). The one
mechanical subtlety is `asdict`, addressed below.

`# FIXME: migrate from attrs to dataclasses` markers already exist at
`infra/cloud/adapters.py:28` and `config/config.py:21`. This change clears
the first; the second belongs to a future `config/*` migration change.

## Goals / Non-Goals

**Goals:**
- Replace `attrs.define`/`field`/`asdict`/`evolve` with `dataclasses.dataclass`/`field`/`asdict`/`replace` across the 5 cloud files + 1 facade.
- Preserve exact behavior: frozen semantics, field defaults, construction patterns, `render()` output, eq/hash semantics.
- Update GRACE-lite metadata (FILE VERSION, CHANGE_SUMMARY, MODULE_MAP wording) on all touched files.
- Add one canary test guarding `CloudConfig.render()` JSON output.
- Add one spec delta codifying the render contract.

**Non-Goals:**
- Do NOT introduce `__slots__` (Python 3.9 minimum; `slots=True` needs 3.10; both precedents avoid it; cloud classes are either singletons or runtime objects with marginal memory benefit).
- Do NOT add custom `__eq__`/`__hash__` — stdlib frozen-dataclass defaults (all-field eq, all-field hash) match attrs `@define(frozen=True)` defaults. No test asserts custom eq/hash on cloud dataclasses (unlike `UMessage`).
- Do NOT remove `attrs>=22.2.0` from `pyproject.toml` — `config/*` (8 files) and `az.py` still need it.
- Do NOT touch `yascheduler/config/*`, `AzureImageReference`, or any file outside `yascheduler/infra/cloud/` and `tests/unit/test_cloud_provisioner_impl.py`.
- Do NOT change public API, CLI, INI config, DB schema, AiiDA entrypoint.
- Do NOT edit `docs/knowledge-graph.xml` (M-CLOUD-* records unchanged; only CHANGE_SUMMARY in source files — precedent `queue-dataclass-migration`).
- Do NOT fix the other stale import paths in `cloud-providers/spec.md` "Provider code relocated" (lines 16/20/24) — out of scope.

## Decisions

### 1. Mechanical mapping per file

Identical pattern to `migrate-ssh-platform-from-attrs`, applied per file:

**`adapters.py`** (v1.1.1 → v1.2.0):
| Before | After |
|---|---|
| `from attrs import define, field` | `from dataclasses import dataclass, field` |
| `@define(frozen=True)` | `@dataclass(frozen=True)` |
| `name: str = field()` | `name: str` |
| `supported_platform_checks: tuple[...] = field()` | `supported_platform_checks: tuple[...]` |
| `create_node: CreateNodeCallable[...] = field()` | `create_node: CreateNodeCallable[...]` |
| `delete_node: DeleteNodeCallable[...] = field()` | `delete_node: DeleteNodeCallable[...]` |
| `op_limit: int = field(default=1)` | `op_limit: int = field(default=1)` |
| `create_node_conn_timeout: int = field(default=10)` | `create_node_conn_timeout: int = field(default=10)` |
| `create_node_timeout: int = field(default=300)` | `create_node_timeout: int = field(default=300)` |

The 4 bare `field()` calls become bare annotations (cleaner; `dataclasses.field()` with no args is redundant). Remove the `# FIXME: migrate from attrs to dataclasses` marker at line 28. Update MODULE_MAP line 11 ("Frozen attrs class" → "Frozen dataclass").

**`cloud_config.py`** (v1.0.1 → v1.1.0):
| Before | After |
|---|---|
| `from attrs import asdict, define, field` | `from dataclasses import asdict, dataclass, field` |
| `@define(frozen=True)` | `@dataclass(frozen=True)` |
| `bootcmd: tuple[Union[str, list[str]], ...] = field(factory=tuple)` | `bootcmd: tuple[Union[str, list[str]], ...] = field(default_factory=tuple)` |
| `package_upgrade: bool = field(default=False)` | `package_upgrade: bool = field(default=False)` |
| `packages: list[str] = field(factory=list)` | `packages: list[str] = field(default_factory=list)` |
| `json.dumps(asdict(self))  # type: ignore[arg-type]` | `json.dumps(asdict(self))` — try without ignore; restore if zuban fails |

Update MODULE_MAP line 12 ("Frozen attrs class" → "Frozen dataclass").

**`protocols.py`** (v1.0.1 → v1.1.0):
| Before | After |
|---|---|
| `from attr import define` (typo, no 's') | (removed entirely) |
| `@define(frozen=True)` (CloudCapacity) | `@dataclass(frozen=True)` |
| `name: str` / `max: int` / `current: int` (bare) | unchanged (already bare) |

CloudCapacity is the simplest case: 3 required fields, no defaults, no methods. The `from attr import define` line (line 35) is a pre-existing typo (`attr` without `s` is the legacy package; `define` exists there as an alias but the import is wrong-by-convention) — removing it is a free fix bundled with the migration.

**`manager.py`** (v2.1.0 → v2.2.0):
| Before | After |
|---|---|
| `from attrs import define, field` | `from dataclasses import dataclass, field` |
| `@define(frozen=True)` | `@dataclass(frozen=True)` |
| 7× `X: Y = field()` | 7× `X: Y` (bare) |
| `ssh_key_lock: asyncio.Lock = field(factory=asyncio.Lock, init=False)` | `ssh_key_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)` |

`ssh_key_lock` is `init=False` so it is not part of the constructor signature — construction-site call patterns in `di.py` and tests are unaffected. Tests already work around the Py 3.9 asyncio.Lock-needs-event-loop quirk (`test_cloud_provisioner_impl.py:206-211`); `default_factory` is called in `__init__` identically to attrs `factory`, so behavior is unchanged.

**`providers/az.py`** (v1.6.1 → v1.7.0) — HYBRID:
| Before | After |
|---|---|
| `from attrs import asdict, evolve` | `from attrs import asdict` + `from dataclasses import replace` |
| `evolve(cloud_config, bootcmd=[*my_boot_cmds, *cloud_config.bootcmd])` (line 205) | `replace(cloud_config, bootcmd=[*my_boot_cmds, *cloud_config.bootcmd])  # type: ignore[misc]` |
| `asdict(vm_image)` (line 231) | `asdict(vm_image)` — STAYS `attrs.asdict` (`vm_image: AzureImageReference` is in `config/cloud.py`, out of scope, remains attrs) |

Rationale for the hybrid: `evolve()` only works on attrs classes, and `CloudConfig` becomes a dataclass, so `evolve` MUST go. But `asdict(vm_image)` operates on `AzureImageReference`, an attrs class NOT in this change's scope — switching to `dataclasses.asdict` there would raise `TypeError` at runtime. The deliberate hybrid keeps `attrs` in `az.py` for exactly the one call that needs it.

**`__init__.py`** (v1.5.1 → v1.6.0) — metadata only:
- Bump version, add CHANGE_SUMMARY entry, refresh MODULE_MAP wording ("Frozen attrs class" → "Frozen dataclass" at line 12). No import changes, `__all__` unchanged.

### 2. The `asdict` divergence — empirically verified

The only place where `attrs.asdict` and `dataclasses.asdict` could diverge is `cloud_config.py:41` (`json.dumps(asdict(self))`). Ran a comparison script on the `CloudConfig` shape:

```
attrs.asdict(AC) → {"bootcmd": ("a",["b"]), "packages": ["vim"], "pkg_up": False}
dc.asdict(DC)    → {"bootcmd": ("a",["b"]), "packages": ["vim"], "pkg_up": False}
json.dumps(...)  → byte-identical (tuple and list serialize identically)
```

`render()` output is byte-identical across implementations. No behavioral risk. The canary test guards against future regressions. (Decision: switch to `dataclasses.asdict` in `cloud_config.py`; keep `attrs.asdict` in `az.py` for the out-of-scope `AzureImageReference`.)

### 3. `replace()` type error in `az.py` (from pre-proposal review)

`dataclasses.replace` is typed `def replace(obj: _DataclassT, /, **changes) -> _DataclassT` where `_DataclassT` is bound to `DataclassInstance`. The call site `evolve(cloud_config, bootcmd=[...])` → `replace(cloud_config, ...)` receives `cloud_config: PCloudConfig` (a Protocol), which does NOT satisfy `_DataclassT`. Zuban emits:

```
error: Argument 1 to "replace" has incompatible type "PCloudConfig"; expected a dataclass [misc]
```

The prior `attrs.evolve` was untyped `(*args: Any, **changes: Any)` so no error existed — this is a NEW error introduced by the migration. Fix: `# type: ignore[misc]` on the `replace()` call. `PCloudConfig` stays a Protocol (callers pass arbitrary `PCloudConfig`-shaped values; the only concrete impl `CloudConfig` becomes a dataclass and remains the runtime instance). Narrowing the type would be a larger, out-of-scope change to the protocol contract.

### 4. Canary test placement and shape

Add `test_cloud_config_render_serializes` to the existing `TestCloudConfigGeneration` class in `tests/unit/test_cloud_provisioner_impl.py` (precedent: `queue-dataclass-migration` added canaries to the existing test file, not a new one).

```python
@pytest.mark.asyncio
async def test_cloud_config_render_serializes(self) -> None:
    """CloudConfig.render() produces stable #cloud-config JSON (asdict canary)."""
    cc = CloudConfig(
        bootcmd=("echo hi", ["mkdir", "/x"]),
        package_upgrade=True,
        packages=["vim", "htop"],
    )
    rendered = cc.render()
    assert rendered.startswith("#cloud-config\n")
    payload = json.loads(rendered[len("#cloud-config\n"):])
    assert payload["bootcmd"] == ["echo hi", ["mkdir", "/x"]]
    assert payload["packages"] == ["vim", "htop"]
    assert payload["package_upgrade"] is True
```

`render_base64()` just base64-encodes `render()` output — covering `render()` covers both. One test suffices. The test does NOT exercise `replace()` in `az.py`, but `replace` internally calls `__init__`, which the canary already exercises via `CloudConfig(...)` construction.

### 5. Spec delta — MODIFIED on "Support modules relocated"

Target: `openspec/specs/cloud-providers/spec.md`. Operation: `MODIFIED` (full updated requirement block, per OpenSpec delta rules).

Two edits to the existing "Support modules relocated" requirement:
1. Fix the stale import path in the existing scenario: `adapters.cloud.adapters` → `yascheduler.infra.cloud.adapters` (the path has been wrong since `rename-adapters-to-infra`; this change naturally corrects it within the same requirement section).
2. Add a new scenario codifying the `CloudConfig.render()` contract that the canary enforces: byte-identical JSON output across the attrs→dataclass migration.

The other stale paths in "Provider code relocated" (lines 16/20/24: `adapters.cloud.providers.*`) are deliberately left out — they were stale before this change, are not caused by it, and will be addressed in a follow-up.

### 6. Version bumps — minor, precedent-consistent

All 6 touched files get a minor version bump (PATCH→MINOR), consistent with both precedents (`queue.py` 1.7.0→1.8.0; `ssh/platform/adapters.py` 1.0.1→1.1.0). A migration with no observable behavior change still merits a minor bump as a marker that the implementation substrate changed.

| File | Before | After |
|---|---|---|
| `adapters.py` | 1.1.1 | 1.2.0 |
| `cloud_config.py` | 1.0.1 | 1.1.0 |
| `protocols.py` | 1.0.1 | 1.1.0 |
| `manager.py` | 2.1.0 | 2.2.0 |
| `providers/az.py` | 1.6.1 | 1.7.0 |
| `__init__.py` | 1.5.1 | 1.6.0 |

### 7. No `__slots__`, no custom eq/hash — decisions S4/S5 from precedents

Adopted verbatim from `migrate-ssh-platform-from-attrs` design.md decisions 4 and 5. Stdlib frozen-dataclass `__eq__` compares all fields; `__hash__` is based on all fields (frozen=True enables hashing). This matches attrs `@define(frozen=True)`. No cloud dataclass has a custom equality invariant (unlike `UMessage`'s id-only eq), and no test asserts eq/hash on them — verified by reading `test_cloud_provisioner_impl.py` and `test_provider_selection.py`.

## Risks / Trade-offs

- **Risk: `asdict` behavioral divergence** → Mitigation: empirically verified byte-identical for the `CloudConfig` shape; canary test guards regression. The `az.py` `asdict(vm_image)` call stays on `attrs.asdict` precisely because `vm_image` is an out-of-scope attrs class — no divergence risk there.
- **Risk: `replace()` zuban type error** → Mitigation: `# type: ignore[misc]` on the single call site. Narrow, localized, documented. Narrowing `PCloudConfig` would be a larger protocol-contract change, out of scope.
- **Risk: `type: ignore[arg-type]` removability in `cloud_config.py:41`** → Mitigation: try removing; restore if `uv run zuban check` fails. `dataclasses.asdict` on a frozen dataclass returns `dict[str, Any]` which `json.dumps` accepts — the ignore is likely removable, but decided at apply time.
- **Risk: test construction breakage** → Mitigation: verified `make_provisioner()` uses kwarg construction (`CloudProvisionerImpl(adapters=..., ...)`) — signature identical post-migration; `MagicMock(spec=CloudAdapter)` works on dataclass classes; Py 3.9 asyncio.Lock workaround in tests is unaffected by `default_factory` vs `factory`.
- **Risk: keeping `attrs` as a dependency means two active class-definition systems** → Trade-off: acceptable — this is incremental cleanup, not a comprehensive migration. `config/*` is a future change.
- **Risk: spec delta scope-creep (fixing stale path)** → Mitigation: the stale path is in the SAME requirement being modified; fixing it is a natural part of the MODIFIED operation, not a separate concern. Other stale paths in a DIFFERENT requirement are deliberately left out.

## Migration Plan

Single-step, no rollout/rollback complexity — internal adapter-layer change with no external surface.

1. Apply mechanical edits to the 5 source files + 1 facade (per Decision 1).
2. Add canary test to `tests/unit/test_cloud_provisioner_impl.py`.
3. Update GRACE-lite metadata (versions, CHANGE_SUMMARY, MODULE_MAP wording) on all 6 files.
4. Write spec delta to `openspec/changes/migrate-cloud-from-attrs/specs/cloud-providers/spec.md`.
5. Run static checks: `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`, `uv run pytest -m unit`, `python3 scripts/grace_check.py`, `openspec validate --all --json`.

Rollback: `git revert` the change commit. No data migration, no config migration, no deployed-state concerns.

## Open Questions

None. All decisions captured during explore mode (Q1–Q11 resolved with the user) and the pre-proposal k-reviewer-fast review (the `replace()` type error).