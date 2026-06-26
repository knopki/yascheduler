## Why

Three FIXMEs in the cloud protocols area mark accumulated debt that the
recently-archived `resolve-type-bridge-debt` change surfaced but did not
address (it was scoped to the *domain* `CloudConfig` Protocol and
entrypoints-side casts, not the *infra* `PCloudConfig` Protocol or the
renderer naming):

1. `infra/cloud/protocols.py:48` — `# FIXME: is this really needed? how many
   consumers?` on `PCloudConfig`.
2. `infra/cloud/protocols.py:93` — `# FIXME: dead code?` on `CloudCapacity`.
3. `infra/cloud/cloud_config.py:19` — `# FIXME: very bad naming of module and
   class (we already have cloud configs)`.

The third names the root cause: a name collision between two genuinely
different concepts living in adjacent modules that differ by one letter.

- `infra/cloud/cloud_config.py` (singular) holds `class CloudConfig`, the
  cloud-init user-data renderer (`bootcmd`, `package_upgrade`, `packages`,
  `render`, `render_base64`).
- `infra/cloud/cloud_configs.py` (plural) holds the cloud *provider config*
  DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI`).
- `domain/ports.py` holds a third, unrelated `CloudConfig` Protocol capturing
  the 6-field provider-config surface.

Three concepts share two names; the singular/plural filename pair has already
caused real confusion (each prior refactor — `cloud-configs-to-infra-registry`,
`migrate-cloud-from-attrs` — touched both files mechanically without anyone
asking whether the renderer Protocol was still needed). Why now: the
predecessor change has cleared the deep az.py retyping, leaving only a
surface-level rename + Protocol collapse, so the cleanup is cheap and the
window is open.

## What Changes

- **Rename Concept B (the cloud-init renderer):** the file
  `yascheduler/infra/cloud/cloud_config.py` is renamed to
  `yascheduler/infra/cloud/cloud_init.py`, and `class CloudConfig` becomes
  `class CloudInitConfig` (a plain frozen dataclass; the
  `PCloudConfig` base class is dropped).
- **Remove the `PCloudConfig` Protocol** from
  `yascheduler/infra/cloud/protocols.py`. The single-implementer Protocol
  (one structural impl, not `@runtime_checkable`, zero `isinstance` calls,
  zero runtime dispatch) collapses into its sole concrete class.
  `CreateNodeCallable.__call__`'s `cloud_config` parameter is retyped from
  `Optional[PCloudConfig]` to `Optional[CloudInitConfig]`; the five provider
  `*_create_node` callables' `cloud_config` parameters are retyped from
  `PCloudConfig | None` to `CloudInitConfig | None` in the same pass.
- **Delete the `CloudCapacity` dataclass** from
  `yascheduler/infra/cloud/protocols.py`. Last consumer removed in the
  archived `cloud-provisioner-pure` change (2026-06-22); confirmed dead by
  grep (`CloudCapacity(` → 0 construction sites, `: CloudCapacity` /
  `-> CloudCapacity` → 0 annotation sites outside archives). Not part of the
  AGENTS.md public-API stability surface.
- **Drop the `isinstance` boundary guard** at
  `yascheduler/infra/cloud/providers/az.py:333` (with its preceding comment
  block at lines 329-332) introduced by `resolve-type-bridge-debt` D3a. The
  guard bridged a public `PCloudConfig | None` param to an internal
  `CloudConfig | None` param; when both sides become the same concrete class,
  the guard is redundant.
- **Re-export surface updates:** `yascheduler/infra/cloud/__init__.py` drops
  the `PCloudConfig` and `CloudCapacity` re-exports and renames the
  `CloudConfig` re-export to `CloudInitConfig`.
- **Drop `PCloudConfig` from `TYPE_CHECKING` import blocks** in
  `manager.py`, `az.py`, `hetzner.py`, `upcloud.py`, and `vastai.py` (each
  currently imports `PCloudConfig` under `TYPE_CHECKING`). Covered by the
  verification grep `rg -n 'PCloudConfig\b' yascheduler/` → zero matches.
- No behavioral change. No public CLI/API/INI/DB/AiiDA change. No new
  dependency. The only runtime-visible effect is the renamed import path
  `from yascheduler.infra.cloud import CloudInitConfig` (previously
  `CloudConfig` from the same package).

## Capabilities

### New Capabilities

None. This is a rename + dead-code-removal hygiene change; no new
behavioral capability is introduced.

### Modified Capabilities

- `cloud-provisioner`: the "CloudProvisionerImpl owns cloud-init rendering
  and SSH key management" Requirement's scenario currently references
  `CloudConfig(bootcmd=..., packages=...).render()` and
  `infra/cloud/cloud_config.py`. Both are renamed:
  `CloudConfig` → `CloudInitConfig`, file path
  `infra/cloud/cloud_config.py` → `infra/cloud/cloud_init.py`. Additionally,
  a new Scenario codifies that `az_create_node`'s `cloud_config` parameter is
  typed `CloudInitConfig | None` (was `PCloudConfig | None`) and that no
  `isinstance` boundary guard is present (the guard added by
  `resolve-type-bridge-debt` D3a is removed, since the Protocol/typing seam
  that necessitated it no longer exists).
- `package-facades`: the `infra/cloud/__init__.py` re-export list loses
  `PCloudConfig` and `CloudCapacity` and gains `CloudInitConfig` (renamed
  from `CloudConfig`). The "Existing re-exports ... preserved" snapshot at
  lines 455-456 of the current spec is updated to reflect the renamed and
  removed symbols.

## Impact

- **Code**:
  - `yascheduler/infra/cloud/cloud_config.py` → renamed to
    `yascheduler/infra/cloud/cloud_init.py`; `class CloudConfig` →
    `class CloudInitConfig`; `PCloudConfig` base class dropped from the
    class header; `MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY` headers
    updated.
  - `yascheduler/infra/cloud/protocols.py`: delete `PCloudConfig` class;
    retype `CreateNodeCallable.__call__` `cloud_config` parameter to
    `Optional[CloudInitConfig]`; delete `CloudCapacity` dataclass; update
    `SCOPE`, `MODULE_MAP`, `CHANGE_SUMMARY` headers; the `from .cloud_configs
    import ConfigCloud` import stays (still needed for the `TConfigCloud_*`
    TypeVars).
  - `yascheduler/infra/cloud/__init__.py`: re-export `CloudInitConfig` (from
    `.cloud_init`) instead of `CloudConfig` (from `.cloud_config`); drop
    `PCloudConfig` and `CloudCapacity` from the import block and `__all__`.
  - `yascheduler/infra/cloud/manager.py`: retype
    `_get_cloud_config_data` return annotation `PCloudConfig` →
    `CloudInitConfig`; update the `return CloudConfig(...)` constructor call
    at line 283 to `CloudInitConfig(...)`; update the import and the contract
    comment.
  - `yascheduler/infra/cloud/providers/az.py`: change
    `from yascheduler.infra.cloud import CloudConfig` → `CloudInitConfig`;
    retype `_render_custom_data`, `create_node`, `create_vm_params`
    `cloud_config` params `CloudConfig | None` → `CloudInitConfig | None`;
    retype `az_create_node` public param `PCloudConfig | None` →
    `CloudInitConfig | None`; delete the `isinstance(cloud_config,
    CloudConfig)` boundary guard at lines 329-337 (redundant when both sides
    are the same concrete class); update contract comments and
    `CHANGE_SUMMARY`.
  - `yascheduler/infra/cloud/providers/hetzner.py`: retype
    `create_node` `cloud_config` param `PCloudConfig | None` →
    `CloudInitConfig | None`; update the import and contract comment.
  - `yascheduler/infra/cloud/providers/upcloud.py`: retype `create_node` and
    the second `cloud_config`-bearing function params
    `PCloudConfig | None` → `CloudInitConfig | None`; update import and
    contract comments.
  - `yascheduler/infra/cloud/providers/vastai.py`: retype `create_node`
    `cloud_config` param `PCloudConfig | None` → `CloudInitConfig | None`;
    update import and contract comment.
  - `tests/unit/test_cloud_provisioner_impl.py`: update the import at line
    41 (`from yascheduler.infra.cloud.cloud_config import CloudConfig` →
    `from yascheduler.infra.cloud.cloud_init import CloudInitConfig`) and
    any references to the renamed class in that file.
- **APIs**: One import-path/identifier change for the cloud-init renderer:
  `from yascheduler.infra.cloud import CloudConfig` /
  `from yascheduler.infra.cloud.cloud_config import CloudConfig` → the same
  with `CloudInitConfig` / `.cloud_init`. Not in the AGENTS.md public-API
  stability surface (CLI commands, `class Yascheduler` public API, INI, DB
  schema, AiiDA entrypoint). Two facade re-exports (`PCloudConfig`,
  `CloudCapacity`) are removed outright; neither is referenced by any
  consumer outside the `yascheduler/` source tree (grep-confirmed).
- **Layers contract**: No change. `infra → domain` edge count unchanged
  (the renderer does not import from domain). The renamed module
  `cloud_init.py` keeps the same dependency posture `cloud_config.py` had.
- **Dependencies**: None. No package added, removed, or version-bumped.
- **Specs**: Two delta specs — `cloud-provisioner` (renamed identifier + file
  path in one Scenario; one new Scenario codifying the dropped
  `isinstance` guard), and `package-facades` (re-export list updated).
- **Tests**: One existing test file touched for the rename import
  (`tests/unit/test_cloud_provisioner_impl.py`). No new test files: the
  renamed class is exercised through the existing
  `test_cloud_provisioner_impl.py` path. No integration/e2e changes (this is
  a static-typing + rename change; DB/SSH/cloud paths untouched).
- **Knowledge graph** (`docs/knowledge-graph.xml`): the `M-CLOUD-CONFIG`
  node (singular — the renderer) is renamed to `M-CLOUD-INIT`; its `<path>`
  updated to `yascheduler/infra/cloud/cloud_init.py`; its `class-CloudConfig`
  annotation renamed to `class-CloudInitConfig`. The single incoming
  `<depends>` edge (from `M-CLOUD-PROVISIONER` at line 703) is updated in the
  same change to reference `M-CLOUD-INIT`. `M-CLOUD-CONFIGS` (plural — the
  DTO module) is untouched. The
  `M-CLOUD-PROTOCOLS` node's annotations lose the `PCloudConfig` and
  `CloudCapacity` entries.
- **Verification**:
  - `uv run pytest -m unit` passes (incl. the renamed import in
    `test_cloud_provisioner_impl.py`).
  - `uv run zuban check`, `uv run ruff check .`,
    `uv run ruff format --check .`, `uv run lint-imports` — all clean.
  - `rg -n 'PCloudConfig\b' yascheduler/` returns zero matches.
  - `rg -n 'CloudCapacity\b' yascheduler/` returns zero matches (excluding
    the unrelated `CloudCapacityExhaustedError` domain exception).
  - `openspec validate --all --json` passes after the two delta specs are
    added.
  - `python3 scripts/grace_check.py` passes (updated `MODULE_MAP` /
    `CHANGE_SUMMARY` in touched files; renamed `M-CLOUD-INIT` node).