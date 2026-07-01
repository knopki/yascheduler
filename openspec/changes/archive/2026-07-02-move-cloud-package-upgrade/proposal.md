## Why

The `cloud_package_upgrade` knob controls cloud-init's `apt-get upgrade` on
freshly-provisioned cloud VMs — a cloud-only concern. It was added to
`LocalSettings` / the `[local]` INI section in the `add-hetzner-live-e2e`
change, which is the wrong layer: it has nothing to do with the local daemon.
The field carries a `# FIXME: this is stupid and "local"` comment marking it as
known-bad, and it is consumed by exactly one site
(`CloudProvisionerImpl._get_cloud_config_data`). It belongs in the per-provider
cloud config alongside `max_nodes` / `idle_tolerance` / `connect_grace`. The
field is pre-release (added in this same renovation, never shipped), so now is
the cheap moment to relocate it before anyone depends on the `[local]` key.

## What Changes

- **BREAKING** (pre-release INI key move): the `[local] cloud_package_upgrade`
  key is removed. Operators set the knob per provider under `[clouds]` as
  `{prefix}_package_upgrade` (e.g. `hetzner_package_upgrade`, `az_package_upgrade`,
  `upcloud_package_upgrade`, `vastai_package_upgrade`). A legacy
  `[local] cloud_package_upgrade` key, if present, will now emit an "unknown
  field" `ConfigWarning` (no error) — deliberate clean break, no deprecation
  shim, because the field is unreleased.
- Remove the `cloud_package_upgrade: bool = True` field from `LocalSettings`
  (`yascheduler/domain/settings.py`).
- Add a `package_upgrade: bool = True` field to all four `ConfigCloud*` DTOs
  (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI`) in `yascheduler/infra/cloud/cloud_configs.py`. Default
  `True` preserves pre-change cloud-init behavior.
- The `CloudConfig` domain Protocol (`yascheduler/domain/ports.py`) is **not**
  changed — `package_upgrade` is read only by infra
  (`CloudProvisionerImpl`), so it stays on the concrete DTOs like `token` /
  `vm_size`, not on the application-facing Protocol.
- Each per-prefix parser (`_parse_azure_section`, `_parse_hetzner_section`,
  `_parse_upcloud_section`, `_parse_vastai_section` in
  `yascheduler/entrypoints/config_parser.py`) reads
  `{prefix}_package_upgrade` via `sec.getboolean(..., fallback=True)`.
  `cloud_valid_fields(prefix)` auto-introspects the DTO, so the new key is
  registered as valid with no manual field-list edit and no "unknown field"
  warning.
- `CloudProvisionerImpl._get_cloud_config_data` gains a `config: ConfigCloud`
  parameter and sources `CloudInitConfig.package_upgrade` from
  `config.package_upgrade` instead of `self.local_config.cloud_package_upgrade`.
  Its sole caller (`allocate`) already resolves the per-cloud config one
  statement earlier and passes it through.
- Update tests that reference the old key/field: `tests/e2e/test_hetzner_live.py`
  (move the key into `[clouds]`) and `tests/unit/test_cloud_provisioner_impl.py`
  (re-source the propagation assertion through the new `config` argument); add
  parser unit cases for `{prefix}_package_upgrade`: explicit `false` parses to
  `False`, and an absent key defaults to `True` (the cloud-init
  behavior-preservation regression guard).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `config-value-objects`: remove the `cloud_package_upgrade` field from the
  `LocalSettings` value object requirement and drop the `[local]`
  `cloud_package_upgrade` parsing requirement and its scenarios.
- `cloud-config`: add a `package_upgrade: bool = True` field to each of the four
  `ConfigCloud*` DTO requirements and a per-prefix `{prefix}_package_upgrade`
  INI-parsing requirement. Explicitly keep the field OFF the `CloudConfig`
  Protocol (infra-only consumer).
- `cloud-provisioner`: change `_get_cloud_config_data` to source
  `CloudInitConfig.package_upgrade` from the per-cloud `config` DTO (new
  parameter) instead of `self.local_config.cloud_package_upgrade`.

## Impact

- **Code**: `yascheduler/domain/settings.py`,
  `yascheduler/infra/cloud/cloud_configs.py`,
  `yascheduler/infra/cloud/manager.py`,
  `yascheduler/entrypoints/config_parser.py` (+ MODULE_CONTRACT / VERSION /
  CHANGE_SUMMARY bumps per GRACE-lite).
- **INI config format**: breaking (pre-release) — `[local] cloud_package_upgrade`
  → `[clouds] {prefix}_package_upgrade`. No migration shim. `AGENTS.md` lists
  the INI config format under "Public interface stability"; this break is
  exempted because the field is pre-release (added in this same renovation,
  never shipped), so no external consumer can depend on the `[local]` key yet.
- **Public API**: `LocalSettings` loses a field; each `ConfigCloud*` DTO gains a
  field; `CloudProvisionerImpl._get_cloud_config_data` gains a parameter
  (private method, single internal caller). No CLI, DB schema, AiiDA, or
  `[engine.*]` change.
- **Dependencies**: none added.
- **Tests**: `tests/e2e/test_hetzner_live.py`, `tests/unit/test_cloud_provisioner_impl.py`,
  `tests/unit/test_config.py` (+ GRACE-lite markup refresh).
- **Knowledge graph**: `M-DOMAIN-SETTINGS` and `M-CLOUD-CONFIGS` annotations
  updated (field moves between them). `M-CLOUD-MANAGER`'s `_get_cloud_config_data`
  contract `LINKS` shifts from `M-DOMAIN-SETTINGS` to `M-CLOUD-CONFIGS` and the
  manager's `<depends>`/`CrossLink` edges follow; the method is private but
  GRACE-lite rule 3 still applies because dependencies changed.
