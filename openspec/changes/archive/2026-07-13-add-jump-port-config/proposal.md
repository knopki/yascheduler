## Why

`Node.jump_port` and the DB column `yascheduler_nodes.jump_port` (with `CHECK 0 < jump_port < 65536`, migration 012) have long been in place, but no INI key feeds them. Both stamping sites — `yasetnode add` and the cloud allocator — hardcode `jump_port=22`, so an operator whose bastion listens on a non-standard port cannot configure yascheduler to reach it. `docs/TODO-jump_port.md` records exactly this gap. The previous change (`node-ncpus-as-config`) deliberately deferred `jump_port` from the `CloudConfig` surface (its `cloud/spec.md` states "`jump_port` SHALL be `22` ... `CloudConfig` does not carry a `jump_port` field in this change"); this change closes that deferral.

## What Changes

- `RemoteDefaults` gains a `jump_port: int` field (default `22`), parsed from a new `jump_port` key in the `[remote]` INI section.
- The `CloudConfig` domain Protocol gains a `jump_port: int` field; the four `ConfigCloud*` DTOs (`Azure`, `Hetzner`, `Upcloud`, `VastAI`) each gain `jump_port: int = 22`.
- Each `[clouds.*]` per-prefix parser accepts a new `{prefix}_jump_port` key (e.g. `az_jump_port`, `hetzner_jump_port`, `upcloud_jump_port`, `vastai_jump_port`); the valid-field tables (`_remote_valid_fields`, the four `_CLOUD_FIELD_RULES` excludes/includes) are extended so unknown-field warnings do not fire on the new keys.
- `yasetnode add` (`manage_node._add_node`) stamps `NewNode.jump_port` from `config.remote.jump_port` instead of the hardcoded `22`.
- The cloud allocator (`CloudProvisionerImpl._setup_vm`) resolves `jump_port` from the matching `CloudConfig` when its jump leg is authoritative (i.e. it already sets both `jump_host` and `jump_username`), and otherwise from `config.remote.jump_port` — preserving the existing "atomic jump leg from one source" rule. The hardcoded `jump_port = 22` is removed.
- Parse-time range validation (1–65535) mirrors the DB `CHECK` constraint, failing fast at `parse_config` rather than at insert time. This follows the existing parser-validation idiom (e.g. `max_nodes`, `idle_tolerance`) rather than introducing `__post_init__` validation on `RemoteDefaults`.

## Capabilities

### New Capabilities

_(none — this change extends existing config and node-identity surfaces; no new subsystem is introduced.)_

### Modified Capabilities

- `config-value-objects`: `RemoteDefaults` requirement extends to include the `jump_port: int` field (default `22`).
- `cloud`: `CloudConfig` Protocol gains a `jump_port: int` field; each `ConfigCloud*` DTO gains `jump_port: int = 22`; the per-prefix parser registry accepts `{prefix}_jump_port`; the `CloudProvisionerImpl` jump-stamping rule (currently "`jump_port` SHALL be `22`") is replaced with "resolved from the matching `CloudConfig.jump_port` when its jump leg is authoritative, otherwise `config.remote.jump_port`".
- `cli`: the `yasetnode add` path stamps `NewNode.jump_port` from `config.remote.jump_port` instead of a hardcoded `22`.
- `domain-entities`: the Node/NewNode jump-stamping rules extend from `jump_host` / `jump_username` to also cover `jump_port`, on both the static (`yasetnode`) and cloud (allocator) paths.

## Impact

- **Code (6 source files)**:
  - `yascheduler/domain/settings.py` — add `RemoteDefaults.jump_port`.
  - `yascheduler/domain/ports.py` — add `CloudConfig.jump_port`.
  - `yascheduler/infra/cloud/cloud_configs.py` — add `jump_port: int = 22` to all four `ConfigCloud*` DTOs.
  - `yascheduler/entrypoints/config_parser.py` — parse `jump_port` in `_parse_remote_section` and `{prefix}_jump_port` in the four per-prefix parsers; extend `_remote_valid_fields` and `_CLOUD_FIELD_RULES` (`_AZ_EXCLUDES`/`_HETZNER_EXCLUDES`/`_UPCLOUD_EXCLUDES`/`_VASTAI_EXCLUDES` and their `_INCLUDES`); add range validation (1–65535) following the existing `getint` + range-check idiom.
  - `yascheduler/entrypoints/cli/manage_node.py` — `_add_node` reads `config.remote.jump_port` (replaces `jump_port=22` literal).
  - `yascheduler/infra/cloud/manager.py` — `_setup_vm` resolves `jump_port` from the authoritative jump-leg source (CloudConfig or `config.remote`) inside the existing `RESOLVE_JUMP` block (replaces `jump_port = 22` literal).
- **INI config**: two new keys are accepted — `jump_port` under `[remote]`, and `{prefix}_jump_port` under `[clouds]` for each of the four providers. Default behavior (key absent) is unchanged (`22`).
- **DB**: no schema change — the `jump_port` column and its `CHECK (jump_port > 0 AND jump_port < 65536)` constraint already exist.
- **Tests**: extend `parse_config` round-trip coverage to include `jump_port` in `[remote]` and `{prefix}_jump_port` in `[clouds.*]`; update `_add_node` and `_setup_vm` stamping tests to assert the resolved value flows through (and that the hardcoded-`22` constant is gone); add parse-time range-validation edge cases (0, 65536, non-integer).
- **Public surface**: no breaking change. `RemoteDefaults`, `CloudConfig`, and the `ConfigCloud*` DTOs gain a field with the same default the code already effectively used; existing INI files behave identically. CLI commands, the `Yascheduler` public API, the INI section/format, and the DB schema are untouched.
- **No new dependencies.**
