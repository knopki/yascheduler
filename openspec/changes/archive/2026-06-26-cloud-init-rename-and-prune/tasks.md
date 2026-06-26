## 1. D1 — Rename renderer file and class (Concept B)

- [x] 1.1 In `yascheduler/infra/cloud/`, rename the file `cloud_config.py`
  → `cloud_init.py` (use `git mv` to preserve history). Verify the old file
  path no longer exists.
- [x] 1.2 In the renamed `yascheduler/infra/cloud/cloud_init.py`, change the
  class header `class CloudConfig(PCloudConfig):` →
  `class CloudInitConfig:` (drop the `PCloudConfig` base class — D2 deletes
  the Protocol; the class becomes a plain `@dataclass(frozen=True)`). Update
  the docstring if it mentions the inheritance.
- [x] 1.3 In `cloud_init.py`, update the GRACE `MODULE_CONTRACT` block:
  - `# FILE:` line → `yascheduler/infra/cloud/cloud_init.py`
  - `VERSION:` bump (1.2.0 → 1.3.0)
  - `PURPOSE:` → "CloudInitConfig — concrete cloud-init user-data renderer."
  - `SCOPE:` → "CloudInitConfig frozen dataclass (bootcmd, package_upgrade,
    packages, render, render_base64)."
  - `DEPENDS:` → `none` (the `from .protocols import PCloudConfig` import
    drops in task 1.5; the module then imports only stdlib `base64`, `json`,
    `dataclasses`).
  - `LINKS:` → `M-CLOUD-INIT, M-CLOUD-PROVISIONER` (was `M-CLOUD-CONFIG`).
- [x] 1.4 In `cloud_init.py`, update the `MODULE_MAP` block: change
  `CloudConfig - Frozen dataclass implementing PCloudConfig protocol` →
  `CloudInitConfig - Frozen dataclass; concrete cloud-init user-data
  renderer`.
- [x] 1.5 In `cloud_init.py`, drop the `from .protocols import PCloudConfig`
  import (line 28) — the base class is gone, the import is unused. (This is
  the D2-driven import drop; doing it here keeps the rename self-contained.)
- [x] 1.6 In `cloud_init.py`, update the `START_CHANGE_SUMMARY` block: add a
  new `LAST_CHANGE` entry referencing this proposal:
  `v1.3.0 - Rename file cloud_config.py → cloud_init.py and class CloudConfig
  → CloudInitConfig; drop PCloudConfig base class (Protocol removed in
  cloud-init-rename-and-prune / D1+D2); disambiguate from the ConfigCloud*
  provider-config DTOs in cloud_configs.py and from the domain CloudConfig
  Protocol in domain/ports.py`. Move the prior `LAST_CHANGE` to
  `PREVIOUS_CHANGE`.
- [x] 1.7 Remove the FIXME comment at the top of the file (line 19:
  `# FIXME: very bad naming of module and class (we already have cloud
  configs)`) — the rename resolves it.

## 2. D2 — Delete PCloudConfig and retype all references in ONE PASS

**All tasks in this group MUST land together (no intervening `zuban check`
gates).** Per design D2, an intermediate state with one side retyped and the
other not is a callable-contravariance violation at `adapters.py:112`. The
six call-site signatures + the manager return annotation + the constructor
call are retyped as one atomic change.

- [x] 2.1 In `yascheduler/infra/cloud/protocols.py`:
  - delete the `# FIXME: is this really needed? how many consumers?` comment
    above `PCloudConfig` (line 48).
  - delete the entire `class PCloudConfig(Protocol):` block (lines 49-64).
  - retype `CreateNodeCallable.__call__`'s `cloud_config` parameter from
    `Optional[PCloudConfig]` → `Optional[CloudInitConfig]`.
  - add an import `from .cloud_init import CloudInitConfig` (the Protocol
    references the concrete class now, not the reverse — this breaks the
    would-be circular import cleanly since `cloud_init.py` no longer imports
    from `protocols.py` after task 1.5).
  - update the `SCOPE` line in the `MODULE_CONTRACT`: drop `PCloudConfig`
    from the enumerated surface.
  - update the `MODULE_MAP`: drop the `PCloudConfig - Cloud config init
    protocol` entry.
  - update the `START_CHANGE_SUMMARY` `LAST_CHANGE` entry referencing this
    proposal.
- [x] 2.2 In `yascheduler/infra/cloud/__init__.py`:
  - change `from .cloud_config import CloudConfig` →
    `from .cloud_init import CloudInitConfig`.
  - drop `PCloudConfig` from the `from .protocols import (...)` block.
  - in `__all__`, drop `"PCloudConfig"` and rename `"CloudConfig"` →
    `"CloudInitConfig"`.
- [x] 2.3 In `yascheduler/infra/cloud/manager.py`:
  - retype `_get_cloud_config_data` return annotation (line 267):
    `PCloudConfig` → `CloudInitConfig`.
  - change the `return CloudConfig(...)` constructor call (line 283) →
    `return CloudInitConfig(...)`.
  - update the import (under `TYPE_CHECKING` at line 54): drop `PCloudConfig`,
    add `CloudInitConfig`.
  - update the contract comment for `_get_cloud_config_data` (lines 260-266):
    `OUTPUTS: { PCloudConfig - ... }` →
    `OUTPUTS: { CloudInitConfig - ... }`.
- [x] 2.4 In `yascheduler/infra/cloud/providers/az.py`:
  - change `from yascheduler.infra.cloud import CloudConfig` (line 78) →
    `from yascheduler.infra.cloud import CloudInitConfig`.
  - under `TYPE_CHECKING` (lines 84-88), drop the `PCloudConfig` import.
  - retype `_render_custom_data` `cloud_config` param (line 198):
    `CloudConfig | None` → `CloudInitConfig | None`.
  - retype `create_node` `cloud_config` param (line 231):
    `CloudConfig | None` → `CloudInitConfig | None`.
  - retype `create_vm_params` `cloud_config` param (line 283):
    `CloudConfig | None` → `CloudInitConfig | None`.
  - retype `az_create_node` public `cloud_config` param (line 322):
    `PCloudConfig | None` → `CloudInitConfig | None`.
  - update the 4 contract comments' `INPUTS:` lines that reference
    `Optional[PCloudConfig]` or `Optional[CloudConfig]` →
    `Optional[CloudInitConfig]`.
  - bump `VERSION` (1.9.0 → 1.10.0) and add a `CHANGE_SUMMARY` `LAST_CHANGE`
    entry referencing this proposal.
- [x] 2.5 In `yascheduler/infra/cloud/providers/hetzner.py`:
  - under `TYPE_CHECKING` (line 53), change the import: drop `PCloudConfig`,
    add `CloudInitConfig` (or add `from yascheduler.infra.cloud import
    CloudInitConfig` if `PCloudConfig` was the only symbol imported there).
  - retype `create_node` `cloud_config` param (line 116):
    `PCloudConfig | None` → `CloudInitConfig | None`.
  - update the `INPUTS:` contract comment referencing
    `Optional[PCloudConfig]` → `Optional[CloudInitConfig]`.
  - bump `VERSION` and add a `CHANGE_SUMMARY` `LAST_CHANGE` entry.
- [x] 2.6 In `yascheduler/infra/cloud/providers/upcloud.py`:
  - under `TYPE_CHECKING` (line 48), change the import: drop `PCloudConfig`,
    add `CloudInitConfig`.
  - retype `create_node` `cloud_config` param (line 79):
    `PCloudConfig | None` → `CloudInitConfig | None`.
  - retype the second `cloud_config`-bearing function param (line 119):
    `PCloudConfig | None` → `CloudInitConfig | None`.
  - update both `INPUTS:` contract comments.
  - bump `VERSION` and add a `CHANGE_SUMMARY` `LAST_CHANGE` entry.
- [x] 2.7 In `yascheduler/infra/cloud/providers/vastai.py`:
  - under `TYPE_CHECKING` (line 48), change the import: drop `PCloudConfig`,
    add `CloudInitConfig`.
  - retype `create_node` `cloud_config` param (line 209):
    `PCloudConfig | None` → `CloudInitConfig | None`.
  - update the `INPUTS:` contract comment.
  - bump `VERSION` and add a `CHANGE_SUMMARY` `LAST_CHANGE` entry.
- [x] 2.8 In `tests/unit/test_cloud_provisioner_impl.py`:
  - change the import at line 41
    (`from yascheduler.infra.cloud.cloud_config import CloudConfig`) →
    `from yascheduler.infra.cloud.cloud_init import CloudInitConfig`.
  - rename any `CloudConfig(...)` constructor calls in the test file →
    `CloudInitConfig(...)`.
  - rename any `isinstance(..., CloudConfig)` checks →
    `isinstance(..., CloudInitConfig)`.
  - rename any `__mro__`-introspection strings or class references that name
    `CloudConfig` (the infra renderer) → `CloudInitConfig`. Do NOT touch
    references to the domain `CloudConfig` Protocol (imported from
    `yascheduler.domain` at line 29) — those are Concept A, unaffected.
- [x] 2.9 Verify no PCloudConfig references remain: run
  `rg -n 'PCloudConfig\b' yascheduler/` → expect zero matches.
- [x] 2.10 Verify no CloudConfig-renderer references remain in source (only
  domain Protocol allowed): run
  `rg -n '\bCloudConfig\b' yascheduler/infra/cloud/` and confirm every
  remaining match is either a comment/docstring referring to the rename
  history OR is in `cloud_configs.py` (the DTO module — unrelated ConfigCloud*
  classes that do NOT match `\bCloudConfig\b` exactly anyway). Run
  `rg -n 'cloud_config\b' yascheduler/` → expect zero matches in import
  statements (all should be `cloud_init`).

## 3. D3 — Delete CloudCapacity (dead code)

- [x] 3.1 In `yascheduler/infra/cloud/protocols.py`, delete the entire
  `# FIXME: dead code?` comment (line 93) and the
  `@dataclass(frozen=True) class CloudCapacity:` block (lines 94-100).
- [x] 3.2 In `yascheduler/infra/cloud/protocols.py`, update the `SCOPE` line
  in the `MODULE_CONTRACT`: drop `CloudCapacity` from the enumerated
  surface.
- [x] 3.3 In `yascheduler/infra/cloud/protocols.py`, update the `MODULE_MAP`:
  drop the `CloudCapacity - Cloud capacity dataclass` entry.
- [x] 3.4 In `yascheduler/infra/cloud/protocols.py`, drop the now-unused
  `from dataclasses import dataclass` import IF `dataclass` is no longer
  used by any other symbol in the file. (Note: `protocols.py` no longer
  defines any `@dataclass` after `CloudCapacity` is removed — the TypeVars
  and Protocols don't use it. If `dataclass` is unused, drop it; otherwise
  leave a comment explaining what still uses it. Run
  `rg -n '@dataclass|dataclass\(' yascheduler/infra/cloud/protocols.py` to
  verify zero usages before dropping.)
- [x] 3.5 In `yascheduler/infra/cloud/__init__.py`, drop `CloudCapacity` from
  the `from .protocols import (...)` block (line 60) and from `__all__`
  (line 72).
- [x] 3.6 In `yascheduler/infra/cloud/__init__.py`, update the
  `MODULE_MAP` line `CloudCapacity - Cloud capacity dataclass` →
  (delete it).
- [x] 3.7 Verify no CloudCapacity references remain: run
  `rg -n 'CloudCapacity\b' yascheduler/` → expect zero matches. (The
  unrelated `CloudCapacityExhaustedError` in `domain/exceptions.py` is a
  different identifier — it does NOT match `CloudCapacity\b` alone because
  the `\b` word boundary requires a non-word char after `CloudCapacity`, and
  `E` is a word char, so `CloudCapacityExhaustedError` does NOT match
  `CloudCapacity\b`. Confirm this by running
  `rg -n 'CloudCapacity\b' yascheduler/domain/exceptions.py` → expect zero
  matches.)

## 4. D4 — Drop the D3a isinstance boundary guard in az_create_node

- [x] 4.1 In `yascheduler/infra/cloud/providers/az.py`, delete the comment
  block at lines 329-332 (the "Boundary guard: narrow the public
  PCloudConfig-typed parameter..." explanation).
- [x] 4.2 In `az.py`, delete the `if cloud_config is not None and not
  isinstance(cloud_config, CloudConfig):` block (lines 333-337), including
  the `raise TypeError(...)` body.
- [x] 4.3 Verify zero `isinstance(cloud_config, ...)` calls remain in
  `az_create_node`: run
  `rg -n 'isinstance\(cloud_config' yascheduler/infra/cloud/providers/az.py`
  → expect zero matches.

## 5. D5 — Knowledge graph node rename and annotations trim

- [x] 5.1 In `docs/knowledge-graph.xml`, rename the `<M-CLOUD-CONFIG ...>`
  node (singular, the renderer — lines 752-759) → `<M-CLOUD-INIT ...>`:
  - tag: `M-CLOUD-CONFIG` → `M-CLOUD-INIT`
  - `NAME="Cloud config dataclass"` → `NAME="Cloud-init renderer dataclass"`
  - `<purpose>` text: update to "...the concrete cloud-init user-data
    renderer (bootcmd, packages, package_upgrade, render, render_base64)."
  - `<path>`: `yascheduler/infra/cloud/cloud_config.py` →
    `yascheduler/infra/cloud/cloud_init.py`
  - `<annotations><class-CloudConfig PURPOSE="Cloud config dataclass" />`
    → `<class-CloudInitConfig PURPOSE="Cloud-init user-data renderer
    dataclass" />`
  - **Also update the single incoming `<depends>` edge:** in the
    `M-CLOUD-PROVISIONER` node's `<depends>` list (line 703), change
    `M-CLOUD-CONFIG` → `M-CLOUD-INIT`. The reference sits between
    `M-CLOUD-PROVIDER-SELECTION,` and `M-CLOUD-CONFIGS,` (the plural DTO
    module — do NOT touch `M-CLOUD-CONFIGS`). This is the only `<depends>`
    list referencing the singular node (grep-confirmed).
- [x] 5.2 In `docs/knowledge-graph.xml`, update the `<M-CLOUD-PROTOCOLS>`
  node (lines 740-750) `<annotations>` block: drop the `<PCloudConfig>` and
  `<CloudCapacity>` annotation entries (delete those two lines). Leave
  `<CreateNodeCallable>`, `<DeleteNodeCallable>`,
  `<SupportedPlatformChecker>`, and the TypeVar entries unchanged.
- [x] 5.3 Verify no references to the old `M-CLOUD-CONFIG` (singular) tag
  remain anywhere in the graph: run
  `rg -n 'M-CLOUD-CONFIG\b' docs/knowledge-graph.xml` → expect ZERO matches
  (the singular node was renamed to `M-CLOUD-INIT`; the incoming depends
  edge at line 703 was updated in task 5.1). The `\b` word boundary correctly
  excludes the plural `M-CLOUD-CONFIGS`, which is untouched and remains at
  its current match count. Also confirm zero `CrossLink` references to the
  singular node: `rg -n 'CrossLink.*M-CLOUD-CONFIG\b' docs/knowledge-graph.xml`
  → expect zero matches.
- [x] 5.4 Verify `M-CLOUD-CONFIGS` (plural) is unchanged: run
  `rg -n 'M-CLOUD-CONFIGS' docs/knowledge-graph.xml` → expect the same
  match count as before this change (the plural DTO module node is not
  touched).

## 6. Spec validation and final verification

- [x] 6.1 Run `openspec validate cloud-init-rename-and-prune --json` →
  confirm `valid: true` and no broken deltas. If validate fails, the most
  likely cause is a header mismatch in a MODIFIED block (the delta's
  `### Requirement:` line must exactly match the existing main spec's
  header). Fix and re-run.
- [x] 6.2 Run `uv run pytest -m unit` → confirm the full unit suite passes,
  including the renamed import in `tests/unit/test_cloud_provisioner_impl.py`.
  If a test fails because it imports `CloudConfig` (the infra renderer) by
  the old name, fix the test import per task 2.8.
- [x] 6.3 Run `uv run zuban check` → confirm zero type errors. If a
  contravariance error surfaces at `adapters.py:112` (`create_node =
  az_create_node`), it means the six signatures in task group 2 were NOT
  all retyped together — re-check that every `PCloudConfig | None` /
  `Optional[PCloudConfig]` in the six call sites is now `CloudInitConfig |
  None` / `Optional[CloudInitConfig]`.
- [x] 6.4 Run `uv run ruff check .` and `uv run ruff format --check .` →
  confirm clean.
- [x] 6.5 Run `uv run lint-imports` → confirm the "Clean architecture
  layers" contract reports `KEPT`. The renamed module `cloud_init.py`
  inherits `cloud_config.py`'s dependency posture (stdlib-only after D2);
  the layers contract is unchanged.
- [x] 6.6 Run the final debt-presence greps:
  - `rg -n 'PCloudConfig\b' yascheduler/` → expect zero matches.
  - `rg -n 'class CloudCapacity' yascheduler/` → expect zero matches.
  - `rg -n 'CloudCapacity\b' yascheduler/` → expect zero matches
    (`CloudCapacityExhaustedError` does not match `CloudCapacity\b` per
    task 3.7's word-boundary analysis).
  - `rg -n '# FIXME' yascheduler/infra/cloud/protocols.py
    yascheduler/infra/cloud/cloud_init.py` → expect zero matches (all three
    FIXMEs resolved: protocols.py:48 PCloudConfig, protocols.py:93
    CloudCapacity, cloud_init.py:19 naming).
- [x] 6.7 Run `openspec validate --all --json` → confirm `valid: true`
  across all changes and main specs.
- [x] 6.8 Run `python3 scripts/grace_check.py` → confirm exit 0 (XML +
  source checks pass; the renamed `M-CLOUD-INIT` node, trimmed
  `M-CLOUD-PROTOCOLS` annotations, and refreshed `CHANGE_SUMMARY` entries
  in touched files all validate).