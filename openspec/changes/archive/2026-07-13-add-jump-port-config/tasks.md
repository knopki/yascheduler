## 1. [remote] jump_port configurable end-to-end through yasetnode

- [x] 1.1 Add `jump_port: int = 22` field to `RemoteDefaults` in `yascheduler/domain/settings.py`
- [x] 1.2 Add `jump_port` parsing with range validation (1–65535, `ValueError` on `< 1`, `> 65535`, or non-integer) to `_parse_remote_section` in `yascheduler/entrypoints/config_parser.py`, following the existing `getint` + range-check idiom used for `max_nodes` / `idle_tolerance`
- [x] 1.3 Add `jump_port` to `_remote_valid_fields()` in `yascheduler/entrypoints/config_parser.py` so unknown-field warnings do not fire on the new key
- [x] 1.4 Replace the hardcoded `jump_port=22` with `config.remote.jump_port` in `_add_node` in `yascheduler/entrypoints/cli/manage_node.py`
- [x] 1.5 Add/extend unit tests covering: `RemoteDefaults.jump_port` default 22; `[remote] jump_port` round-trips through `parse_config`; range rejection of 0, 65536, and non-integer values; `_add_node` stamps the resolved `jump_port` onto the `NewNode`
- [x] 1.6 Update GRACE-lite artifacts for the edited files: refresh `MODULE_MAP` / `CHANGE_SUMMARY` anchors in `yascheduler/domain/settings.py` and `yascheduler/entrypoints/config_parser.py`; add a `jump_port` annotation to the `RemoteDefaults` entry in `docs/knowledge-graph.xml` if its annotation surface is tracked there

## 2. [clouds.*] {prefix}_jump_port configurable through the cloud allocator

- [x] 2.1 Add `jump_port: int` to the `CloudConfig` Protocol in `yascheduler/domain/ports.py` (8-field surface)
- [x] 2.2 Add `jump_port: int = 22` to all four `ConfigCloud*` DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`) in `yascheduler/infra/cloud/cloud_configs.py`
- [x] 2.3 Add `{prefix}_jump_port` parsing with range validation (1–65535, `ValueError` on violation) to each of the four per-prefix parsers (`_parse_azure_section`, `_parse_hetzner_section`, `_parse_upcloud_section`, `_parse_vastai_section`) in `yascheduler/entrypoints/config_parser.py`
- [x] 2.4 Update the `_CLOUD_FIELD_RULES` tables (`_AZ_EXCLUDES`/`_AZ_INCLUDES`, `_HETZNER_EXCLUDES`/`_HETZNER_INCLUDES`, `_UPCLOUD_EXCLUDES`/`_UPCLOUD_INCLUDES`, `_VASTAI_EXCLUDES`/`_VASTAI_INCLUDES`) in `yascheduler/entrypoints/config_parser.py` so the four `{prefix}_jump_port` keys auto-register without unknown-field warnings
- [x] 2.5 Replace the hardcoded `jump_port = 22` in `_setup_vm` in `yascheduler/infra/cloud/manager.py` with atomic-leg resolution: `CloudConfig.jump_port` when the cloud leg is authoritative (both `jump_host` AND `jump_username` set), otherwise `config.remote.jump_port`
- [x] 2.6 Add/extend unit tests covering: cloud-wins (host+username+port all from `CloudConfig`); fallback (all three from `config.remote.*` when `CloudConfig` lacks both); no-mixing (a `CloudConfig` setting only `jump_host` falls back to remote for ALL three fields); per-prefix parse + range validation edge cases (0, 65536, non-integer) for at least two providers
- [x] 2.7 Update GRACE-lite artifacts: refresh `MODULE_MAP` / `CHANGE_SUMMARY` in `yascheduler/domain/ports.py`, `yascheduler/infra/cloud/cloud_configs.py`, `yascheduler/entrypoints/config_parser.py`, and `yascheduler/infra/cloud/manager.py`; update the `CloudConfig` and `ConfigCloud*` annotations in `docs/knowledge-graph.xml` to reflect the new `jump_port` field
