# Explore Brief — move-cloud-package-upgrade

## Problem

`cloud_package_upgrade: bool = True` was added to `LocalSettings` (domain/settings.py:58)
in the `add-hetzner-live-e2e` change. It controls cloud-init's `package_upgrade`
flag on freshly-provisioned VMs — a cloud-only concern with nothing to do with
the local daemon. The field even carries a `# FIXME: this is stupid and "local"`
comment. It is consumed by exactly one site:
`CloudProvisionerImpl._get_cloud_config_data` (infra/cloud/manager.py:320), which
reads `self.local_config.cloud_package_upgrade`.

## Goal

Relocate the knob from `[local]` / `LocalSettings` to the per-provider cloud
config (`[clouds] {prefix}_package_upgrade` / `ConfigCloud*` DTOs), where it
belongs semantically alongside `max_nodes`, `idle_tolerance`, `connect_grace`.

## Rejected alternatives

1. **Keep on LocalSettings, just rename.** Rejected — the layer is wrong, not
   the name. Cloud-init concerns don't belong on the local-daemon DTO.
2. **Per-provider field only on some DTOs.** Rejected — all 4 providers use
   cloud-init (`_get_cloud_config_data` builds a `CloudInitConfig` for every
   adapter), so the knob is universally meaningful.
3. **Backward-compat shim accepting legacy `[local] cloud_package_upgrade`.**
   Rejected — the field is pre-release (added in this same renovation, not
   shipped). YAGNI; a clean break is cheaper than carrying a deprecation path.
4. **Put `package_upgrade` on the `CloudConfig` domain Protocol.** Rejected —
   the Protocol captures the application-facing surface (the 7 fields
   `deallocate_nodes` / `orchestrator` / never-connected cleanup read).
   `package_upgrade` is read only by infra (`CloudProvisionerImpl`), so it
   belongs on the concrete DTOs like `token` / `vm_size` / `server_type`, not
   on the Protocol.

## Final approach — full mapping

### Field name and location

| Aspect | Value |
|---|---|
| DTO field | `package_upgrade: bool = True` |
| DTOs carrying it | `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI` (all 4) |
| INI section | `[clouds]` |
| INI keys | `az_package_upgrade`, `hetzner_package_upgrade`, `upcloud_package_upgrade`, `vastai_package_upgrade` |
| Parser | `sec.getboolean(fmt("package_upgrade"), fallback=True)` in each `_parse_{prefix}_section` |
| Domain Protocol | NOT touched (`CloudConfig` Protocol stays the 7-field app surface) |
| Default | `True` (preserves pre-change cloud-init behavior) |

Rationale for the name `package_upgrade` (not `cloud_package_upgrade`): every
other `[clouds]` field sheds the `cloud_` qualifier (the `{prefix}_` already
conveys "cloud"), and `package_upgrade` matches `CloudInitConfig.package_upgrade`
and the cloud-init schema field 1:1.

### Removals

- `LocalSettings.cloud_package_upgrade` field (domain/settings.py:58).
- `[local] cloud_package_upgrade` parsing in `_parse_local_section`
  (config_parser.py:616).
- `_local_valid_fields()` introspection drops the key automatically once the
  field is removed (it derives from `dataclasses.fields(LocalSettings)`).

### Consumer change

`CloudProvisionerImpl._get_cloud_config_data`:
- Signature: `(self, adapter, config)` — add the resolved per-cloud `config: ConfigCloud`.
- Body: `package_upgrade=config.package_upgrade` instead of
  `self.local_config.cloud_package_upgrade`.
- Caller `allocate` (manager.py:170) already resolves `config = self.configs.get(provider)`
  one statement earlier; pass it through: `cloud_config=await self._get_cloud_config_data(adapter, config)`.

### Auto-registration (no manual field-list edits)

`cloud_valid_fields(prefix)` introspects `dataclasses.fields(dto_cls)` minus
excludes, so adding `package_upgrade` to each DTO automatically registers
`{prefix}_package_upgrade` as a known key — `warn_unknown_fields` will NOT warn.
`_ALL_CLOUD_VALID_FIELDS` (the union passed to every parser) follows
automatically. No edit to `_CLOUD_FIELD_RULES` needed unless `package_upgrade`
matches an exclude rule (it does not).

## Cross-module data flow

```
[clouds] hetzner_package_upgrade=false
  -> parse_clouds -> _parse_hetzner_section (getboolean)
  -> ConfigCloudHetzner(package_upgrade=False)
  -> Config.clouds
  -> di -> CloudProvisionerImpl.configs["hetzner"]
  -> allocate("hetzner") resolves config=configs["hetzner"]
  -> _get_cloud_config_data(adapter, config)
  -> CloudInitConfig(package_upgrade=config.package_upgrade=False)
  -> adapter.create_node(cloud_config=...)
```

## Tests to update / add

- `tests/unit/test_cloud_provisioner_impl.py`:
  `test_cloud_config_package_upgrade_sourced_from_local_config` → rename and
  re-source: pass a `ConfigCloudHetzner(package_upgrade=False)` via the new
  `config` arg to `_get_cloud_config_data`; assert `CloudInitConfig.package_upgrade is False`.
  The existing `test_cloud_config_with_engine_packages` (MagicMock local_config)
  must pass a real-ish config DTO now.
- `tests/e2e/test_hetzner_live.py`: move `cloud_package_upgrade = false` out of
  `[local]` into `[clouds]` as `hetzner_package_upgrade = false`.
- `tests/unit/test_config.py` (new cases): `{prefix}_package_upgrade=false`
  parses to `ConfigCloud*.package_upgrade is False`; absent key defaults to `True`.

## Affected specs (delta files)

- `config-value-objects`: remove `cloud_package_upgrade` from LocalSettings
  requirement + its `[local]` parse scenarios.
- `cloud-config`: add `package_upgrade: bool = True` to all 4 DTO requirements +
  per-prefix `{prefix}_package_upgrade` parse scenarios. Explicitly note NOT on
  the CloudConfig Protocol.
- `cloud-provisioner`: re-source `package_upgrade` from the per-cloud config DTO
  in `_get_cloud_config_data` (signature gains `config`).

## Open questions

- None blocking. Backward compat is a deliberate non-goal (pre-release).
