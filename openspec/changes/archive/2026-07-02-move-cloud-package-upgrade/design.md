## Context

`cloud_package_upgrade: bool = True` was added to `LocalSettings`
(`yascheduler/domain/settings.py:58`) in the `add-hetzner-live-e2e` change to let
operators and the live e2e test skip cloud-init's slow `apt-get upgrade` on fresh
VMs. It is consumed by exactly one site —
`CloudProvisionerImpl._get_cloud_config_data` (`yascheduler/infra/cloud/manager.py:320`)
— which builds the `CloudInitConfig` passed to each provider's `create_node`
callable. The field carries a `# FIXME: this is stupid and "local"` comment.

The knob is semantically a cloud concern: it controls a cloud-init flag on
cloud VMs and has nothing to do with the local daemon. Every other knob that
influences cloud provisioning (`max_nodes`, `idle_tolerance`, `connect_grace`,
`server_type`, `vm_size`, ...) lives on the per-provider `ConfigCloud*` DTOs in
`yascheduler/infra/cloud/cloud_configs.py`, parsed from the `[clouds]` INI
section under `{prefix}_*` keys. `_get_cloud_config_data`'s sole caller
(`CloudProvisionerImpl.allocate`, manager.py:149) already resolves
`config = self.configs.get(provider)` at line 155, two statements before the
call — so the per-cloud DTO is already in hand at the consume site.

The field is pre-release (added in this same renovation, never shipped), so there
is no external consumer of the `[local] cloud_package_upgrade` INI key.

## Goals / Non-Goals

**Goals:**
- Relocate the knob to its correct layer: `ConfigCloud*` DTOs + `[clouds]
  {prefix}_package_upgrade`, matching the `connect_grace` / `idle_tolerance`
  precedent.
- Keep the default behavior identical (`package_upgrade is True` when unset), so
  cloud-init behavior on existing deployments is unchanged.
- Make the knob per-provider (operators can opt out of `apt-get upgrade` on one
  cloud and not another), which the `[local]` global could not express.
- Touch only the layers that must change: `domain/settings.py`,
  `infra/cloud/cloud_configs.py`, `infra/cloud/manager.py`,
  `entrypoints/config_parser.py`, and the three affected specs/tests.

**Non-Goals:**
- No backward-compatibility / deprecation shim for the legacy
  `[local] cloud_package_upgrade` key (pre-release; clean break).
- No change to the `CloudConfig` domain Protocol — it stays the 7-field
  application-facing surface (`prefix`, `max_nodes`, `idle_tolerance`,
  `connect_grace`, `username`, `jump_username`, `jump_host`). The new field is
  read only by infra, so it lives on the concrete DTOs like `token` / `vm_size`.
- No change to `CloudInitConfig`, the `CreateNodeCallable` signature, the CLI,
  the DB schema, AiiDA, or `[engine.*]`.

## Decisions

### Decision 1: Field name `package_upgrade`, not `cloud_package_upgrade`

On the DTO and in the INI key the field is `package_upgrade`, giving INI keys
`az_package_upgrade`, `hetzner_package_upgrade`, `upcloud_package_upgrade`,
`vastai_package_upgrade`.

**Rationale:** every existing `[clouds]` field sheds the `cloud_` qualifier —
the `{prefix}_` segment already conveys "cloud" (`hetzner_max_nodes`, not
`hetzner_cloud_max_nodes`). `package_upgrade` also matches
`CloudInitConfig.package_upgrade` and the cloud-init schema field 1:1, so the
name documents exactly what it does.

**Alternatives rejected:**
- Keep `cloud_package_upgrade`: redundant under `[clouds]` and diverges from the
  cloud-init field name the DTO ultimately feeds.

### Decision 2: Add to all four `ConfigCloud*` DTOs, not a subset

`package_upgrade: bool = True` is added to `ConfigCloudAzure`,
`ConfigCloudHetzner`, `ConfigCloudUpcloud`, and `ConfigCloudVastAI`.

**Rationale:** `_get_cloud_config_data` builds a `CloudInitConfig` for every
adapter (it is the single shared cloud-config builder), so the knob is
universally meaningful. Putting it on only some DTOs would force
`getattr(config, "package_upgrade", True)` fallbacks in the consumer and
fragment the contract.

### Decision 3: NOT on the `CloudConfig` Protocol

The `CloudConfig` Protocol in `yascheduler/domain/ports.py` is unchanged.

**Rationale:** the Protocol's stated purpose is "minimal surface application
consumers read" — the 7 fields read by `deallocate_nodes`, `orchestrator`, and
the never-connected-node cleanup path. `package_upgrade` is read only by
`CloudProvisionerImpl` (infra), which types its `configs` against the concrete
`ConfigCloud` Union. It therefore sits in the same category as `token`,
`vm_size`, `server_type`, `api_key` — infra-only fields declared on the concrete
DTOs, not on the Protocol.

**Typing consequence (must follow):** the new `config` parameter on
`_get_cloud_config_data` MUST be typed `ConfigCloud` (the infra Union), not
`CloudConfig` (the domain Protocol), otherwise `config.package_upgrade` does not
type-resolve. This is enforced in the cloud-provisioner delta spec scenario.

### Decision 4: Re-source via a new `config` parameter on `_get_cloud_config_data`

Signature changes from `_get_cloud_config_data(self, adapter: CloudAdapter)` to
`_get_cloud_config_data(self, adapter: CloudAdapter, config: ConfigCloud)`, and
the body reads `package_upgrade=config.package_upgrade`.

**Rationale:** the caller `allocate` already resolves `config` at manager.py:155
and threads it through to `create_node` (line 168 `cfg=config`) and `delete_node`
(line 204/219 `cfg=config`). Passing it to `_get_cloud_config_data` is one extra
keyword arg at the single call site (manager.py:170) and keeps the method pure
w.r.t. `self.local_config` for this concern. Alternatives rejected:
- Read `self.configs[adapter.name]` inside the method: re-resolves what the
  caller already has and couples the helper to the dict layout.
- Pass `package_upgrade: bool` scalar: loses the config's identity and is less
  future-proof if another cloud-init field becomes per-provider later.

### Decision 5: Per-provider INI parsing, auto-registered

Each `_parse_{prefix}_section` reads
`sec.getboolean(fmt("package_upgrade"), fallback=True)` and passes it to the DTO
constructor. No edit to `cloud_valid_fields` or `_CLOUD_FIELD_RULES` is needed:
`cloud_valid_fields(prefix)` derives keys from
`dataclasses.fields(dto_cls) minus excludes`, so adding the field auto-registers
`{prefix}_package_upgrade` as a known key, and `_ALL_CLOUD_VALID_FIELDS` (the
union passed to `warn_unknown_fields`) follows automatically. No "unknown field"
warning for the new key.

**Removal side-effect (intended):** once `LocalSettings` loses
`cloud_package_upgrade`, `_local_valid_fields()` (which introspects
`dataclasses.fields(LocalSettings)`) drops the key. A leftover
`[local] cloud_package_upgrade` in an INI will then surface as an "unknown
field" `ConfigWarning` — not an error. This is the deliberate clean-break
signal.

### Decision 6: Default `True` on all four DTOs

Preserves the pre-change default (`LocalSettings.cloud_package_upgrade` was
`True`), so deployments that do not set the key see identical cloud-init
behavior.

## Risks / Trade-offs

- **[Breaking INI key move]** → Mitigated by pre-release status (no shipped
  consumer depends on `[local] cloud_package_upgrade`) and by the
  "unknown field" `ConfigWarning` that surfaces a leftover legacy key as a
  migration hint. No silent breakage: parsing succeeds, behavior is the default
  `True`, and the warning points at the stale key.
- **[Per-provider divergence surprises operators]** → A provider without the key
  defaults to `True` (upgrade runs); the divergence is opt-in and documented in
  the spec scenarios. This is strictly more expressive than the prior global
  knob.
- **[Protocol divergence grows]** → Adding a field to the DTOs but not the
  Protocol widens the (already large) set of infra-only fields (`token`,
  `vm_size`, ...). Accepted: that is the designed Protocol boundary, not drift.
- **[Forgetting the `config` arg at the call site]** → Single internal caller
  (`allocate`); covered by a unit test that asserts `False` propagates and by
  the type checker (`config: ConfigCloud` param is required).
- **[`CloudInitConfig.package_upgrade` defaults to `False`, DTOs to `True`]** →
  No runtime effect: `_get_cloud_config_data` always passes the DTO value
  explicitly, so the two defaults never interact. Noted only because a reader
  may briefly wonder about it.

## Migration Plan

No runtime migration. For the in-tree config and tests:

1. Move any `[local] cloud_package_upgrade = ...` to `[clouds]` as
   `{prefix}_package_upgrade = ...` (only `tests/e2e/test_hetzner_live.py` sets
   it today, as `cloud_package_upgrade = false`).
2. Re-run `uv run pytest -m unit -m integration -m e2e` (the e2e suite is the
   behavior-preservation guard for the live cloud path).

Rollback: revert the four source files and the tests; no persisted state is
touched by this change.

## Open Questions

None blocking. Backward compatibility is a deliberate non-goal.
