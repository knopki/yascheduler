# Explore Brief — Narrow Config.clouds Type

## Problem

`yascheduler/entrypoints/di.py` carries 2 `cast(...)` calls at the
entrypoints→infra boundary:

- `cfg = cast("ConfigCloud", cfg)` (di.py:165)
- `active_clouds = cast("list[ConfigCloud]", [...])` (di.py:194-201)

Both are Protocol→Union downcasts. Root cause: `Config.clouds` is typed
`Sequence[CloudConfig]` (domain Protocol) but its only producer (`parse_clouds`)
returns `list[ConfigCloud]` (infra Union), and the composition root's infra sinks
(`resolve_adapter`, `CloudProvisionerImpl.configs`, `active_clouds`) consume the
concrete Union.

## Rejected alternatives

- **B (widen infra sinks to Protocol)**: `resolve_adapter`, `manager.py`,
  `provider_selection.py` read provider-specific fields (`token`, `api_key`,
  `vm_size`). Widening forces casts *inside* infra where it is currently clean.
  Rejected — moves debt deeper.
- **C (typed accessor on parser)**: two fields for one dataset. Over-engineering.

## Chosen approach (A1)

Narrow `Config.clouds: Sequence[CloudConfig]` → `Sequence[ConfigCloud]`.
Import `ConfigCloud` from `yascheduler.infra.cloud.cloud_configs` under
`TYPE_CHECKING` in `config.py`. Both downcasts in `di.py` become redundant and
drop; `cast` import drops from `di.py`.

## Why A1 is viable now (and was rejected before)

Prior archived proposal `2026-06-26-resolve-type-bridge-debt` rejected A1 in
`design.md:137-142` because `list[ConfigCloud] → Sequence[CloudConfig]` failed
under **writable-vs-frozen mismatch** (writable Protocol attributes vs frozen
dataclass DTOs). That same proposal's D1 (4 DTOs explicitly inherit the
`CloudConfig` Protocol) removed the mismatch and unlocked the upcast — proven by
the proposal removing 2 upcast casts (`cast("Sequence[CloudConfig]",
config.clouds)`, `cast("Sequence[CloudConfig]", active_clouds)`). The team did not
return to A1; the 2 downcasts stayed as "honest boundary casts".

Post-D1 the covariance + inheritance that makes the upcast work also makes
`Sequence[ConfigCloud] → Sequence[CloudConfig]` work — same mechanism. A1 became
viable the moment D1 landed.

## Empirical verification (this explore session)

- Isolated repro (`/tmp/opencode/repro_a1/repro_a1_clean.py`), `mypy --strict` +
  `pyright`, no `# type: ignore`: 0 errors across 4 key call shapes.
- Real-tree spike: applied A1 to `config.py`, removed both casts + `cast` import
  in `di.py`:
  - `uv run zuban check` → Success (148 files)
  - `uv run ruff check .` → All checks passed
  - `uv run ruff format --check .` → 147 files formatted
  - `uv run lint-imports` → KEPT (new `entrypoints → infra.cloud` edge permitted;
    `entrypoints > infra`)
  - `uv run pytest -m unit` → 647 passed, 0 failed
- Tree restored via `git checkout`; zuban green on clean tree.

## Mapping table — callers of `config.clouds`

| Caller | Reads | Typed against | After A1 |
| --- | --- | --- | --- |
| `Orchestrator.__init__` (`config_clouds=`) | `.prefix`, `.jump_host`, `.jump_username`, `.max_nodes`, `.idle_tolerance` | `Sequence[CloudConfig]` | unchanged; `Sequence[ConfigCloud]` assignable via covariance+inheritance |
| `Orchestrator._connect_machine_consumer` | `.prefix`, `.jump_host`, `.jump_username` | via `self._config_clouds` | unchanged |
| `Orchestrator._deallocator_producer` → `deallocate_nodes(config_clouds=)` | `.prefix`, `.idle_tolerance` | `Sequence[CloudConfig]` | unchanged (covariance) |
| `di.py make_daemon` (both branches) | `.max_nodes`, `.prefix` + feeds to `resolve_adapter`, `_configs`, `active_clouds` | infra Union | **casts removed** |
| `cli/check_status.py` | `.prefix`, `.jump_host`, `.jump_username` | inferred | unchanged (Protocol fields still present on Union members) |

## Cross-module data flow

```
parse_config (entrypoints/config_parser.py)
   └─ parse_clouds() -> list[ConfigCloud]
       └─ Config(clouds=list[ConfigCloud])        [A1: typed Sequence[ConfigCloud]]
           └─ make_daemon (entrypoints/di.py)
               ├─ for cfg in config.clouds        [cfg: ConfigCloud, no cast]
               │   ├─ resolve_adapter(cfg)         [sink: ConfigCloud] ✓
               │   ├─ _configs[name] = cfg          [dict[str, ConfigCloud]] ✓
               │   └─ active_clouds.append(cfg)    [list[ConfigCloud]] ✓
               ├─ active_clouds = [cfg for cfg in ...]  [list[ConfigCloud], no cast]
               └─ Orchestrator(config_clouds=config.clouds, active_clouds=active_clouds)
                   [sinks: Sequence[CloudConfig]]  ✓ covariance+inheritance
```

## Open questions

1. Does the prior `cloud-config-protocol` delta spec's "No cast bridges in
   composition root" Scenario (scoped to upcasts, with downcasts documented as
   honest boundary casts) need updating? **Yes** — a new delta must broaden it
   to "No cast bridges at all in composition root" and remove the "honest
   boundary cast" carve-out for these 2 sites.
2. Should `test_di.py` gain a regression assert that `cast(` is absent from
   `di.py` source? **Yes** — cheap guard against silent reintroduction.
3. Does `M-ENTRYPOINTS-CONFIG` `<depends>` need a new entry? **No** —
   `M-CLOUD-CONFIGS` is already in its `<depends>`; only the *type* of one field
   changes, not the structural relationship. CHANGE_SUMMARY update only.
4. Is `Config.clouds` part of any stabilized public surface (CLI/INI/DB/AiiDA)?
   **No** — `Config` is internal composition-root aggregate; AGENTS.md's
   stability list does not cover it. No public-API impact.