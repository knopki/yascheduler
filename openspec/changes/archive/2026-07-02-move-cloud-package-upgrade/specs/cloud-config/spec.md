## ADDED Requirements

### Requirement: Per-provider package_upgrade cloud-init field

The system SHALL declare a `package_upgrade: bool` dataclass field (default `True`) on each of the four cloud-provider config DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`) in `yascheduler/infra/cloud/cloud_configs.py`. The field controls the cloud-init `package_upgrade` flag on freshly-provisioned VMs for that provider (it flows into `CloudInitConfig.package_upgrade` via `CloudProvisionerImpl._get_cloud_config_data`). The default `True` preserves the pre-change cloud-init behavior (an `apt-get upgrade` runs on first boot).

The field SHALL be declared on the concrete DTOs only. It SHALL NOT be added to the `CloudConfig` domain Protocol (`yascheduler/domain/ports.py`): the Protocol captures the 7-field application-facing surface (`prefix`, `max_nodes`, `idle_tolerance`, `connect_grace`, `username`, `jump_username`, `jump_host`) read by `deallocate_nodes`, `orchestrator`, and the never-connected-node cleanup path. `package_upgrade` is read only by infra (`CloudProvisionerImpl`), so it sits in the same category as `token`, `vm_size`, `server_type`, and `api_key` — infra-only fields on the concrete DTOs.

Each per-prefix parser (`_parse_azure_section`, `_parse_hetzner_section`, `_parse_upcloud_section`, `_parse_vastai_section` in `yascheduler/entrypoints/config_parser.py`) SHALL read the optional `{prefix}_package_upgrade` key (e.g. `hetzner_package_upgrade`, `az_package_upgrade`) via `sec.getboolean(fmt("package_upgrade"), fallback=True)` and pass the result to the DTO constructor. Because `cloud_valid_fields(prefix)` derives the valid key set from `dataclasses.fields(dto_cls)` minus excludes, the new `{prefix}_package_upgrade` key SHALL be auto-registered as a known field — no edit to `_CLOUD_FIELD_RULES` is required, `_ALL_CLOUD_VALID_FIELDS` follows automatically, and `warn_unknown_fields` SHALL NOT warn about the key.

#### Scenario: package_upgrade defaults to True on all four DTOs
- **WHEN** each of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI` is constructed without a `package_upgrade` argument
- **THEN** the resulting instance has `package_upgrade is True` (preserving the pre-change cloud-init behavior)

#### Scenario: package_upgrade accepts False
- **WHEN** `ConfigCloudHetzner(package_upgrade=False)` is constructed
- **THEN** the resulting instance has `package_upgrade is False`

#### Scenario: package_upgrade is NOT on the CloudConfig Protocol
- **WHEN** the `CloudConfig` Protocol in `yascheduler/domain/ports.py` is introspected for a `package_upgrade` attribute
- **THEN** no such attribute is declared (the field lives on the concrete DTOs only, like `token`/`vm_size`)

#### Scenario: [clouds] package_upgrade parsed per provider
- **WHEN** `parse_clouds(cfg, remote)` parses a `[clouds]` section containing `hetzner_package_upgrade = false` and no other `{prefix}_package_upgrade` keys
- **THEN** the returned `ConfigCloudHetzner` has `package_upgrade is False`
- **AND** the returned `ConfigCloudAzure`/`ConfigCloudUpcloud`/`ConfigCloudVastAI` (if their prefixes are present) each have `package_upgrade is True` (the per-provider default)

#### Scenario: absent package_upgrade key defaults to True
- **WHEN** `parse_clouds(cfg, remote)` parses a `[clouds]` section whose `{prefix}_*` keys do not include any `{prefix}_package_upgrade`
- **THEN** every returned `ConfigCloud*` DTO has `package_upgrade is True`

#### Scenario: package_upgrade key does not warn as unknown
- **WHEN** `parse_clouds(cfg, remote)` parses a `[clouds]` section containing `hetzner_package_upgrade = false`
- **THEN** `warn_unknown_fields` does NOT emit a `ConfigWarning` for `hetzner_package_upgrade` (it is auto-registered via `cloud_valid_fields("hetzner")` introspection of the DTO field)
