## Why

`ConfigCloud*` (Azure, Hetzner, UpCloud, VastAI) and `AzureImageReference` are cloud
adapter DTOs misplaced in `yascheduler/config/cloud.py`. `infra/cloud/protocols.py`
runtime-imports `ConfigCloud` *upward* from `yascheduler.config` — a layer crossing
that only works because `yascheduler.config` is exempt from the R3 layers contract.
Separately, `Config.from_config_parser` hardcodes the cloud variant list as a tuple
(`(ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI)`);
the P1 fix that appended `ConfigCloudVastAI` is a band-aid, not an open/closed
solution — adding a provider still requires editing the aggregate root. This is the
third step (P3) of the config-layer split plan
(`docs/config-layer-split-plan.md`): relocate the cloud DTOs into
`yascheduler/infra/cloud/cloud_configs.py`, separate INI parsing into
`entrypoints/config_parser.py` (extending the P2 parser module), introduce a
`CLOUD_CONFIG_PARSERS` registry that makes cloud assembly open/closed, and add a
structural `CloudConfig` Protocol to `domain/ports.py` so application-layer consumers
type against the domain contract, not the infra DTOs. Predecessors: P1
(`ssh-keys-extraction-vastai-parser-fix`) is archived; P2
(`engine-to-domain-frozen`) is proposed — P3 composes with P2 (each removes its own
`config/` re-exports; the parser module gains cloud parsers alongside the engine
parsers P2 added).

## What Changes

- Move `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI`, `AzureImageReference`, and the `ConfigCloud` Union alias from
  `yascheduler/config/cloud.py` to a new
  `yascheduler/infra/cloud/cloud_configs.py` as `@dataclass(frozen=True)` (drop
  attrs). `AzureImageReference.from_urn` is retained (pure URN parsing, no INI
  dependency). Drop `from_config_parser_section` and `get_valid_config_parser_fields`
  from each DTO. **BREAKING** for direct `from yascheduler.config.cloud import ...` and
  `from yascheduler.config import ConfigCloud*` imports; the canonical path becomes
  `from yascheduler.infra.cloud import ConfigCloud*`.
- Move the per-provider `from_config_parser_section` classmethods and
  `get_valid_config_parser_fields` classmethods, plus the `_check_az_user`,
  `_fmt_key` helpers, into `entrypoints/config_parser.py` as free functions
  (`parse_cloud_section`, `parse_clouds`, `cloud_valid_fields`, per-prefix
  `_parse_azure_section` / `_parse_hetzner_section` / `_parse_upcloud_section` /
  `_parse_vastai_section`). Validation (`validators.ge(0)`, `validators.ge(1)`,
  `opt_str_val`, `_check_az_user`) runs parser-side, not in dataclass `__post_init__`.
  `warn_unknown_fields` and `make_default_field` stay in `config/utils.py` (P4 removes
  them when the last consumers move). **BREAKING** for direct
  `ConfigCloudX.from_config_parser_section(...)` calls; the canonical path becomes
  `parse_cloud_section(sec, prefix)` / `parse_clouds(cfg, remote)`.
- Introduce `CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]]` in
  `entrypoints/config_parser.py` mapping each provider prefix (`az`, `hetzner`,
  `upcloud`, `vastai`) to its parser function. Adding a provider = adding one parser
  function + one registry entry; the aggregate root no longer hardcodes the variant
  list. (Note: the umbrella plan `docs/config-layer-split-plan.md` §4 P3 places the
  registry in `infra/cloud/`; the explore-brief Decision (b) moves it to
  `entrypoints/config_parser.py` to keep the `infra → entrypoints` dependency direction
  R3-legal — the registry references parser functions, which are composition-root
  concerns. This proposal follows Decision (b).)
- Update `Config.from_config_parser` (`yascheduler/config/config.py`) to delegate cloud
  assembly to `parse_clouds(cfg, remote)` from `entrypoints/config_parser.py` via a
  lazy import inside `from_config_parser` (same pattern as P2's engine-assembly seam —
  the composition-root parser module is the single seam between INI and domain/infra
  types; `Config` stays constructible in one call until P4). The `cloud_variants`
  tuple and the `cloud_prefixes` / `cloud_variants_match` / username-inheritance block
  move into `parse_clouds`. Document the lazy-import TODO referencing P4.
- Add a structural `@runtime_checkable` `CloudConfig` Protocol to
  `yascheduler/domain/ports.py` with fields `prefix: str`, `max_nodes: int`,
  `idle_tolerance: int`, `username: str`, `jump_username: str | None`,
  `jump_host: str | None` — the exact surface application-layer consumers
  (`deallocate_nodes`, `orchestrator`) read. Precedent: `OccupancyConfig` and
  `TaskExecutionEngine` already live in `domain/ports.py` as structural Protocols. The
  cloud DTOs satisfy `CloudConfig` structurally (no explicit inheritance).
- Update `application/deallocate_nodes.py` and `application/orchestrator.py`
  TYPE_CHECKING imports: `from yascheduler.config import ConfigCloud` →
  `from yascheduler.domain import CloudConfig`. The `config_clouds` /
  `active_clouds` parameters change type from `Sequence[ConfigCloud]` to
  `Sequence[CloudConfig]`. No runtime change (structural satisfaction).
- Update `infra/cloud/protocols.py:37` runtime import `from yascheduler.config import
  ConfigCloud` → `from .cloud_configs import ConfigCloud` (intra-package). The three
  `TypeVar(bound=ConfigCloud)` declarations continue to bind to the relocated Union.
- Update `infra/cloud/adapters.py:40`, `infra/cloud/provider_selection.py:27`,
  `infra/cloud/manager.py:49-54` TYPE_CHECKING imports of `ConfigCloud` → intra-package
  `from .cloud_configs import ConfigCloud` (or `from yascheduler.infra.cloud import
  ConfigCloud` for the manager, which sits at the subpackage root).
- Update `infra/cloud/providers/{az,hetzner,upcloud,vastai}.py` TYPE_CHECKING imports
  of `ConfigCloud*` / `AzureImageReference` → `from yascheduler.infra.cloud import ...`
  (facade import, R2-compliant) or intra-package relative (`from ..cloud_configs
  import ...`). Prefer the facade import for consistency with existing provider-module
  style (`from yascheduler.infra.cloud import get_rnd_name`).
- Delete `yascheduler/config/cloud.py`. Update `yascheduler/config/__init__.py` to drop
  `AzureImageReference`, `ConfigCloud`, `ConfigCloudAzure`, `ConfigCloudHetzner`,
  `ConfigCloudUpcloud`, `ConfigCloudVastAI` from `__all__` and the `from .cloud import
  (...)` block. Update `config/config.py` to drop the `from .cloud import (...)` block.
- Update `yascheduler/infra/cloud/__init__.py` to re-export `AzureImageReference`,
  `ConfigCloud`, `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI` from `.cloud_configs` (the cloud subpackage facade becomes the
  canonical import path for the DTOs).
- Migrate tests: `from yascheduler.config.cloud import ...` →
  `from yascheduler.infra.cloud import ...`; `ConfigCloudX.from_config_parser_section`
  direct calls → `parse_cloud_section`; `from yascheduler.config import ConfigCloud`
  → `from yascheduler.infra.cloud import ConfigCloud` (for the union) or
  `from yascheduler.domain import CloudConfig` (for the Protocol, in application tests).

## Capabilities

### New Capabilities
- `cloud-config-dtos`: Cloud provider configuration DTOs (`ConfigCloudAzure`,
  `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`,
  `AzureImageReference`, `ConfigCloud` union) as frozen stdlib dataclasses in
  `yascheduler/infra/cloud/cloud_configs.py`, with no INI parsing on the DTOs and no
  attrs dependency. Covers the field set, the `AzureImageReference.from_urn` pure
  parser, and importability from `yascheduler.infra.cloud`.
- `cloud-config-protocol`: The `CloudConfig` structural Protocol in
  `yascheduler/domain/ports.py` capturing the 6-field surface
  (`prefix`, `max_nodes`, `idle_tolerance`, `username`, `jump_username`,
  `jump_host`) that application-layer consumers type against, satisfied structurally
  by every `ConfigCloud*` DTO.
- `cloud-config-parsers`: The `CLOUD_CONFIG_PARSERS` registry and the
  `parse_cloud_section` / `parse_clouds` / `cloud_valid_fields` functions in
  `entrypoints/config_parser.py`, covering per-prefix dispatch, validation, and
  open/closed registration of new providers without editing the aggregate root.

### Modified Capabilities
- `cloud-providers`: The provider modules (`infra/cloud/providers/{az,hetzner,upcloud,vastai}.py`)
  import their config DTOs from `yascheduler.infra.cloud` instead of
  `yascheduler.config`; the DTOs are frozen dataclasses, not attrs classes. The
  `ConfigCloudX.from_config_parser_section` classmethods are removed; INI parsing is
  invoked via the registry from the composition root.
- `cloud-provisioner`: `CloudProvisionerImpl.configs: dict[str, ConfigCloud]` is typed
  against the relocated union (intra-package import); the `_connect_to_vm` `getattr`
  fallbacks for `jump_host`/`jump_username` can become direct attribute access since
  all DTOs declare those fields.
- `package-facades`: The `yascheduler.config` facade stops re-exporting
  `AzureImageReference`, `ConfigCloud`, `ConfigCloudAzure`, `ConfigCloudHetzner`,
  `ConfigCloudUpcloud`, `ConfigCloudVastAI`; the `yascheduler.infra.cloud` facade
  gains those re-exports from `.cloud_configs`. The `infra/cloud/protocols.py`
  runtime import of `ConfigCloud` becomes intra-package (no longer an
  outside-layer-set exemption edge).
- `domain-ports`: The `CloudConfig` structural Protocol is added alongside the
  existing `OccupancyConfig` and `TaskExecutionEngine` Protocols.
- `testing-unit`: The config-parsing requirement loses
  `ConfigCloudX.from_config_parser_section` direct calls; cloud round-trip parsing
  of `[clouds]` sections is asserted against `parse_clouds` /
  `parse_cloud_section` from `entrypoints/config_parser.py`, and the DTOs are asserted
  frozen with no parser methods. The VastAI round-trip assertion added in P1 migrates
  to the registry-based path.

## Impact

- **Code**: New `yascheduler/infra/cloud/cloud_configs.py`; deleted
  `yascheduler/config/cloud.py`; modified `yascheduler/config/__init__.py`,
  `yascheduler/config/config.py` (cloud assembly delegation), `yascheduler/infra/cloud/__init__.py`
  (DTO re-exports), `yascheduler/infra/cloud/protocols.py` (intra-package import),
  `yascheduler/infra/cloud/adapters.py`,
  `yascheduler/infra/cloud/provider_selection.py`,
  `yascheduler/infra/cloud/manager.py` (TYPE_CHECKING import switch),
  `yascheduler/infra/cloud/providers/{az,hetzner,upcloud,vastai}.py` (TYPE_CHECKING
  import switch), `yascheduler/domain/ports.py` (`CloudConfig` Protocol added),
  `yascheduler/application/deallocate_nodes.py`,
  `yascheduler/application/orchestrator.py` (TYPE_CHECKING `ConfigCloud` →
  `CloudConfig`), `entrypoints/config_parser.py` (cloud parsers + registry; created by
  P2 or extended here if P2 not yet implemented), `entrypoints/di.py` (TYPE_CHECKING
  `ConfigCloud` → `CloudConfig`).
- **APIs**: Direct `from yascheduler.config.cloud import ...` and
  `from yascheduler.config import ConfigCloud*` / `AzureImageReference` break; the
  canonical path becomes `from yascheduler.infra.cloud import ...`.
  `ConfigCloudX.from_config_parser_section` / `ConfigCloudX.get_valid_config_parser_fields`
  break; the canonical path becomes
  `from yascheduler.entrypoints.config_parser import parse_cloud_section, parse_clouds, cloud_valid_fields`.
  The `cloud_variants` tuple in `Config.from_config_parser` is removed (replaced by
  registry iteration). No public API surface (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`,
  `PID_FILE`, `from yascheduler import Yascheduler`, `from yascheduler.client import
  Yascheduler`) is affected.
- **Layers contract**: `yascheduler.config` remains in the outside-layer-set exemption
  list in the `package-facades` spec (P4 removes the package entirely and drops the
  exemption). P3 shrinks the exemption surface by one runtime edge —
  `infra/cloud/protocols.py → yascheduler.config.ConfigCloud` becomes an intra-package
  import — but does not remove the exemption. The `forbidden` contract
  ("Shared kernel has no config imports") is untouched (it stays until P4 makes it
  vacuous).
- **Dependencies**: `attrs` usage in `config/cloud.py` removed (the file is deleted);
  `attrs` remains a project dependency until P5 (`config/config.py`, `config/db.py`,
  `config/remote.py` still use attrs; they move in P4).
- **Specs**: New `cloud-config-dtos`, `cloud-config-protocol`, `cloud-config-parsers`
  capability specs. Delta specs for `cloud-providers`, `cloud-provisioner`,
  `package-facades`, `domain-ports`, `testing-unit`.
- **Tests**: `tests/unit/test_config.py` cloud-parsing tests migrate to
  `parse_cloud_section` / `parse_clouds` and assert frozen + no parser methods;
  `tests/unit/test_provider_selection.py`, `tests/unit/test_application_use_cases.py`,
  `tests/unit/test_di.py`, `tests/unit/test_application_orchestrator.py` switch
  `ConfigCloud*` imports to `yascheduler.infra.cloud` (DTO) or `yascheduler.domain`
  (Protocol). Audit `MagicMock(spec=ConfigCloud)` sites for reliance on the removed
  parser classmethods.
- **Knowledge graph**: `M-CONFIG-CLOUD` removed; `M-CLOUD-CONFIGS` added
  (TYPE=DATA_LAYER); `M-DOMAIN-PORTS` gains the `protocol-CloudConfig` annotation;
  `M-ENTRYPOINTS-CONFIG-PARSER` gains the registry + parser function annotations;
  CrossLinks from `M-CLOUD-*`, `M-APPLICATION-*`, `M-ENTRYPOINTS-DI` that targeted
  `M-CONFIG-CLOUD` repoint to `M-CLOUD-CONFIGS` (infra DTO consumers) or
  `M-DOMAIN-PORTS` (application Protocol consumers).