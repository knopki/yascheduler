# Explore Brief — cloud-configs-to-infra-registry (P3)

> Umbrella: `docs/config-layer-split-plan.md` §4 P3.
> Predecessors: `ssh-keys-extraction-vastai-parser-fix` (P1, archived);
> `engine-to-domain-frozen` (P2, proposal written, not yet archived).

## Rejected alternatives

1. **Keep `ConfigCloud*` in `yascheduler/config/`** — rejected: `infra/cloud/protocols.py`
   already runtime-imports `ConfigCloud` from `yascheduler.config`, a layer-crossing that
   only works because `yascheduler.config` is exempt from the R3 layers contract. The
   cloud adapter DTOs belong to the cloud subpackage; relocating them makes the
   `protocols.py` import intra-package and removes the upward dependency.
2. **Keep `from_config_parser_section` as classmethods on the DTOs.** Rejected — same
   reasoning as P2's D2: DTOs must not import `ConfigParser`/`SectionProxy`. Parsing is an
   adapter concern and moves to `entrypoints/config_parser.py` alongside the engine
   parsers added in P2. `config/utils.py` (`make_default_field`, `opt_str_val`,
   `warn_unknown_fields`) stays in `config/` until P4 removes the last consumers
   (`ConfigDb`, `ConfigLocal`, `ConfigRemote`); P3's cloud parsers import it from there.
3. **Hardcode the cloud variant list in `Config.from_config_parser` (keep the
   `cloud_variants` tuple).** Rejected — the P1 fix that appended `ConfigCloudVastAI`
   to the tuple is a band-aid; the open/closed fix is a registry that each provider
   registers its parser into. A future provider (e.g., a new `[cloud.foo]` section) then
   requires zero edits to the aggregate root — only a registry entry in the cloud
   subpackage.
4. **Make `CloudConfig` a nominal (subclassed) Protocol.** Rejected — precedent in
   `domain/ports.py` (`OccupancyConfig`, `TaskExecutionEngine`) is structural
   (`@runtime_checkable` Protocol, no explicit inheritance). The cloud DTOs satisfy it
   structurally; application-layer consumers (`deallocate_nodes`, `orchestrator`) type
   against the domain Protocol, keeping `application → infra` TYPE_CHECKING-only.
5. **Fold cloud parser registration into each provider module's import-time side
   effects.** Rejected — import-time registration is implicit and order-dependent
   (provider modules must be imported before the registry is queried). Instead, the
   registry is built as a module-level constant in `infra/cloud/cloud_configs.py`
   (mapping `prefix → parser callable`), so a single import of the configs module
   populates it; the composition root imports the module explicitly. This is explicit,
   testable, and order-independent.
6. **Merge P3 into P4.** Rejected — the "no oversized proposals" constraint. P3
   touches cloud DTOs + parser registry + `CloudConfig` Protocol; P4 touches the
   `Config` aggregate + `ConfigLocal`/`ConfigRemote`/`ConfigDb` relocation + parser
   consolidation. Combining them exceeds the size budget. P3 is self-contained and
   testable alone (the registry + DTO relocation does not depend on the aggregate
   moving).

## Final approach: complete label / mapping tables

### Module relocation table

| Symbol                       | Current module                  | Target module                            | Form change                                                  |
|------------------------------|----------------------------------|------------------------------------------|--------------------------------------------------------------|
| `AzureImageReference`        | `yascheduler/config/cloud.py`    | `yascheduler/infra/cloud/cloud_configs.py` | attrs frozen → `@dataclass(frozen=True)`; keep `from_urn` classmethod (pure, no INI) |
| `ConfigCloudAzure`           | `yascheduler/config/cloud.py`    | `yascheduler/infra/cloud/cloud_configs.py` | attrs frozen → `@dataclass(frozen=True)`; drop `from_config_parser_section`, `get_valid_config_parser_fields` |
| `ConfigCloudHetzner`         | `yascheduler/config/cloud.py`    | `yascheduler/infra/cloud/cloud_configs.py` | same                                                          |
| `ConfigCloudUpcloud`         | `yascheduler/config/cloud.py`    | `yascheduler/infra/cloud/cloud_configs.py` | same                                                          |
| `ConfigCloudVastAI`          | `yascheduler/config/cloud.py`    | `yascheduler/infra/cloud/cloud_configs.py` | same                                                          |
| `ConfigCloud` (Union alias)  | `yascheduler/config/cloud.py`    | `yascheduler/infra/cloud/cloud_configs.py` | Union alias over the 4 frozen dataclasses                     |
| `_check_az_user` validator   | `yascheduler/config/cloud.py`    | `entrypoints/config_parser.py`            | Parser-side helper (prefixed `_`)                            |
| `_fmt_key` helper            | `yascheduler/config/cloud.py`    | `entrypoints/config_parser.py`            | Parser-side helper (prefixed `_`)                            |
| `ConfigCloud*.from_config_parser_section` | classmethods on each DTO | `entrypoints/config_parser.py::parse_cloud_section` | Single dispatcher: `parse_cloud_section(sec, prefix) -> CloudConfig` dispatches by prefix via `CLOUD_CONFIG_PARSERS` registry |
| `ConfigCloud*.get_valid_config_parser_fields` | classmethods on each DTO | `entrypoints/config_parser.py::cloud_valid_fields` | Per-prefix field list helper used by `warn_unknown_fields`    |
| `cloud_variants` tuple in `Config.from_config_parser` | `yascheduler/config/config.py` | **deleted**                              | Replaced by registry iteration in the cloud-assembly step    |
| `CloudConfig` Protocol       | (does not exist)                | `yascheduler/domain/ports.py`             | New structural `@runtime_checkable` Protocol; fields: `prefix: str`, `max_nodes: int`, `idle_tolerance: int`, `username: str`, `jump_username: str \| None`, `jump_host: str \| None` |
| `CLOUD_CONFIG_PARSERS` registry | (does not exist)             | `entrypoints/config_parser.py`            | `dict[str, Callable[[SectionProxy], CloudConfig]]` — one entry per provider prefix. Registry lives at the composition-root layer (Decision b) so `infra → entrypoints` stays R3-legal; the DTOs live in `infra/cloud/cloud_configs.py`, the parsers + registry live in `entrypoints/config_parser.py`. |

### `CloudConfig` Protocol field set

| Field            | Type             | Source field on current DTOs            | Rationale (consumer usage)                               |
|------------------|------------------|-----------------------------------------|----------------------------------------------------------|
| `prefix`         | `str`            | `ConfigCloud*.prefix` (class attr)      | `deallocate_nodes` groups nodes by `ccfg.prefix`; `orchestrator._clouds_get_capacity` sums `c.prefix`; `di.make_daemon` filters `cfg.prefix` |
| `max_nodes`      | `int`            | `ConfigCloud*.max_nodes`                | `deallocate_nodes` (no), `orchestrator._clouds_get_capacity` (yes), `provider_selection_pure` (yes), `di.make_daemon` (yes) |
| `idle_tolerance` | `int`            | `ConfigCloud*.idle_tolerance`           | `deallocate_nodes` (yes — `(now - idle) >= ccfg.idle_tolerance`) |
| `username`       | `str`            | `ConfigCloud*.username`                 | `CloudProvisionerImpl._connect_to_vm` (`config.username`); `di.make_daemon` inherits username into `[clouds]` section |
| `jump_username`  | `str \| None`    | `ConfigCloud*.jump_username`            | `CloudProvisionerImpl._connect_to_vm` (`getattr(config, "jump_username", None)`); `orchestrator._connect_machine_consumer` (`cloud.jump_username`) |
| `jump_host`      | `str \| None`    | `ConfigCloud*.jump_host`                | `CloudProvisionerImpl._connect_to_vm`; `orchestrator._connect_machine_consumer` |

Application consumers (`deallocate_nodes`, `orchestrator`) access **only** these 6
fields. `CloudProvisionerImpl` (infra) accesses the same 6 plus provider-specific
fields (`tenant_id`, `token`, `login`, `api_key`, …) via the concrete DTO type — it
stays typed against `ConfigCloud*` (infra→infra, legal).

### Consumer call sites (production, runtime + TYPE_CHECKING)

| File                                      | Current import / usage                       | After P3                                                              |
|-------------------------------------------|---------------------------------------------|-----------------------------------------------------------------------|
| `infra/cloud/protocols.py:37`             | `from yascheduler.config import ConfigCloud` (runtime) | `from .cloud_configs import ConfigCloud` (intra-package)            |
| `infra/cloud/protocols.py:41-45`          | `TypeVar(bound=ConfigCloud)` ×3              | unchanged (bound to the relocated `ConfigCloud` union)                |
| `infra/cloud/adapters.py:40`              | `from yascheduler.config import ConfigCloud` (TYPE_CHECKING) | `from .cloud_configs import ConfigCloud` (TYPE_CHECKING, intra-package) |
| `infra/cloud/provider_selection.py:27`    | `from yascheduler.config import ConfigCloud` (TYPE_CHECKING) | `from .cloud_configs import ConfigCloud` (TYPE_CHECKING, intra-package) |
| `infra/cloud/manager.py:49-54`            | `from yascheduler.config import (ConfigCloud, ConfigLocal, ConfigRemote, EngineRepository)` (TYPE_CHECKING) | `ConfigCloud` → `from .cloud_configs import ConfigCloud`; `ConfigLocal`/`ConfigRemote` stay (P4); `EngineRepository` → `yascheduler.domain` (P2 already migrated or this proposal assumes P2 done) |
| `infra/cloud/providers/az.py:84-86`       | `from yascheduler.config import AzureImageReference, ConfigCloudAzure` (TYPE_CHECKING) | `from yascheduler.infra.cloud import AzureImageReference, ConfigCloudAzure` (R2 facade import — the relative `from ..cloud_configs import ...` is banned by the R1 no-parent-traversal rule, and the deep `from yascheduler.infra.cloud.cloud_configs import ...` bypasses the facade violating R2) |
| `infra/cloud/providers/hetzner.py:53`     | `from yascheduler.config import ConfigCloudHetzner` (TYPE_CHECKING) | `from yascheduler.infra.cloud import ConfigCloudHetzner` (R2 facade)    |
| `infra/cloud/providers/upcloud.py:48`     | `from yascheduler.config import ConfigCloudUpcloud` (TYPE_CHECKING) | `from yascheduler.infra.cloud import ConfigCloudUpcloud` (R2 facade)  |
| `infra/cloud/providers/vastai.py:48`      | `from yascheduler.config import ConfigCloudVastAI` (TYPE_CHECKING) | `from yascheduler.infra.cloud import ConfigCloudVastAI` (R2 facade)   |
| `application/deallocate_nodes.py:31`      | `from yascheduler.config import ConfigCloud` (TYPE_CHECKING) | `from yascheduler.domain import CloudConfig` (TYPE_CHECKING)        |
| `application/orchestrator.py:54`          | `from yascheduler.config import Config, ConfigCloud, EngineRepository` (TYPE_CHECKING) | `Config` stays (P4); `ConfigCloud` → `from yascheduler.domain import CloudConfig`; `EngineRepository` → `yascheduler.domain` (P2) |
| `entrypoints/di.py:61`                    | `from yascheduler.config import Config, ConfigCloud, EngineRepository` (TYPE_CHECKING) | `Config` stays; `ConfigCloud` → `from yascheduler.domain import CloudConfig`; `EngineRepository` → `yascheduler.domain` (P2) |
| `config/config.py:32-38`                  | `from .cloud import (ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI)` (runtime) | **deleted** — the `cloud_variants` tuple and cloud assembly move out of `Config.from_config_parser`. `Config.from_config_parser` delegates cloud assembly to `parse_clouds(cfg, remote)` from `entrypoints/config_parser.py` (lazy import, same pattern as P2 engine assembly) OR the composition root builds clouds separately. **Decision D3 below picks the lazy-import path** to keep `Config` constructible in one call (matches P2's engine-assembly decision). |
| `config/__init__.py:42-49`                | re-exports `AzureImageReference`, `ConfigCloud*` | **removed** from facade re-exports; `yascheduler.infra.cloud` facade gains them |

### `CLOUD_CONFIG_PARSERS` registry shape

```python
# yascheduler/entrypoints/config_parser.py (Decision b: registry at composition root)
from configparser import SectionProxy
from typing import Callable

from yascheduler.domain import CloudConfig

# After the per-prefix parser function definitions:
CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]] = {
    "az": _parse_azure_section,
    "hetzner": _parse_hetzner_section,
    "upcloud": _parse_upcloud_section,
    "vastai": _parse_vastai_section,
}
```

The parser functions live in `entrypoints/config_parser.py` (adapter concern, no INI
on the DTOs); the registry maps `prefix → parser callable`. The registry is the seam
between the INI source and the domain/infra types for the cloud path. Adding a provider
= adding one parser function + one registry entry; zero edits to the aggregate root.

**Module placement tension:** the registry references parser functions that live in
`entrypoints/config_parser.py`, but the registry itself is most naturally consumed by
the composition root (`entrypoints/di.py` / `entrypoints/config_parser.py`). Two
options:

- **(a)** Registry in `infra/cloud/cloud_configs.py`, importing the parser functions from
  `entrypoints/config_parser.py` — violates R3 (`infra → entrypoints`).
- **(b)** Registry in `entrypoints/config_parser.py`, importing the DTO classes from
  `infra/cloud/cloud_configs.py` — R3-legal (`entrypoints → infra`). The registry is
  built at the composition-root layer, where INI parsing belongs.

**Decision: (b).** The registry lives in `entrypoints/config_parser.py`. The cloud
subpackage owns the DTOs and the `ConfigCloud` Union; the entrypoints layer owns the
parsers and the registry that maps prefixes to them. This keeps the dependency direction
legal and matches the P2 decision that parsers live at the composition root.

The cloud subpackage re-exports the DTOs + Union via `infra/cloud/__init__.py` so
consumers can `from yascheduler.infra.cloud import ConfigCloudAzure, ...`.

### Cross-module data flows

**Cloud config build path (runtime, after P3):**
`entrypoints/config_parser.py::parse_config` (or `Config.from_config_parser` via lazy
import) → `parse_clouds(cfg, remote)` → iterates `CLOUD_CONFIG_PARSERS` → for each
prefix present in `[clouds]` options, dispatches to the per-provider parser → builds
`list[CloudConfig]` (concrete DTO instances) → assigned to `Config.clouds`.

**Provider selection path (runtime):**
`application/allocate_task` → `clouds.select_provider(platforms, counts)` →
`select_provider_pure(adapters, configs, …)` → reads `config.max_nodes`,
`config.priority` (concrete DTO fields, not the Protocol — infra stays typed against
the concrete DTOs).

After P3: `configs: dict[str, ConfigCloud]` in `CloudProvisionerImpl` is typed against
the relocated `ConfigCloud` union (infra→infra). No change to selection logic.

**Deallocate path (runtime):**
`application/deallocate_nodes(uow_factory, config_clouds, idle_machines)` →
`for ccfg in config_clouds: ccfg.prefix; ccfg.idle_tolerance` → typed against
`CloudConfig` Protocol (domain) instead of `ConfigCloud` (infra). Structural
satisfaction — no runtime change.

**Cloud provisioner connect path (runtime):**
`infra/cloud/manager.py::_connect_to_vm(ip, adapter, config: ConfigCloud)` →
`config.username`, `getattr(config, "jump_host", None)`, `getattr(config,
"jump_username", None)`. After P3, `config` is typed as the concrete DTO (infra→infra);
the `getattr` fallbacks can become direct attribute access since all 4 DTOs now have
`jump_host`/`jump_username` as declared fields (they already do today).

### Config facade delta (`yascheduler/config/__init__.py`)

After P3 the facade no longer re-exports `AzureImageReference`, `ConfigCloud`,
`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`.
The physical file `config/cloud.py` is **deleted**. The facade keeps re-exporting
`Config`, `ConfigDb`, `ConfigLocal`, `ConfigRemote` (those move in P4). If P2 is not
yet implemented at P3 time, the facade also still re-exports `Engine`/`EngineRepository`/
`Deploy*` (P2 removes them) — P3 and P2 compose: each removes its own re-exports.

### `infra/cloud/__init__.py` facade delta

After P3 the cloud facade gains re-exports: `AzureImageReference`, `ConfigCloud`,
`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`
from `.cloud_configs`. Consumers that today import `from yascheduler.config import
ConfigCloud*` switch to `from yascheduler.infra.cloud import ConfigCloud*` (R2-compliant
facade import).

### Test migration map

| Test file                              | Current pattern                              | After P3                                                              |
|---------------------------------------|---------------------------------------------|-----------------------------------------------------------------------|
| `tests/unit/test_config.py:46-58`     | `from yascheduler.config.cloud import (ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference)` | `from yascheduler.infra.cloud import (...)`; `Config`, `ConfigDb`, `ConfigLocal`, `ConfigRemote` stay from `yascheduler.config` (P4 moves them) |
| `tests/unit/test_config.py` cloud-parsing tests | `ConfigCloudAzure.from_config_parser_section(...)` direct calls | Migrate to `parse_cloud_section(sec, "az")` or the per-prefix parser from `entrypoints/config_parser.py`; assert frozen + no parser method on the DTO |
| `tests/unit/test_provider_selection.py:32` | `from yascheduler.config.cloud import ConfigCloud` | `from yascheduler.infra.cloud import ConfigCloud`                    |
| `tests/unit/test_application_use_cases.py:52` | `from yascheduler.config.cloud import ConfigCloudAzure` | `from yascheduler.infra.cloud import ConfigCloudAzure`               |
| `tests/unit/test_di.py:31`            | `from yascheduler.config import (ConfigCloud, ...)` | `ConfigCloud` → `from yascheduler.infra.cloud import ConfigCloud`; other config symbols stay until P4 |
| `tests/unit/test_application_orchestrator.py:54` | `from yascheduler.config import (...)` including `ConfigCloud` | `ConfigCloud` → `from yascheduler.domain import CloudConfig` (TYPE_CHECKING); the mock `config_clouds`/`active_clouds` lists can stay as concrete DTOs or `MagicMock(spec=CloudConfig)` — audit in tasks |
| Any `from yascheduler.config import ConfigCloud` in tests | grep hit | `from yascheduler.infra.cloud import ConfigCloud` (infra DTO) or `from yascheduler.domain import CloudConfig` (domain Protocol) depending on whether the test needs the concrete union or the Protocol |

### Knowledge graph delta

- `M-CONFIG-CLOUD` **removed**.
- `M-CLOUD-CONFIGS` **added** (TYPE=DATA_LAYER, STATUS=implemented): path
  `src/yascheduler/infra/cloud/cloud_configs.py`; purpose "Cloud provider config DTOs
  (Azure, Hetzner, UpCloud, VastAI) and the ConfigCloud union"; depends
  `M-CLOUD-PROTOCOLS`; annotations `class-ConfigCloudAzure`, `class-ConfigCloudHetzner`,
  `class-ConfigCloudUpcloud`, `class-ConfigCloudVastAI`, `class-AzureImageReference`,
  `type-ConfigCloud`.
- `M-DOMAIN-PORTS` annotation: add `protocol-CloudConfig PURPOSE="Structural contract
  for cloud provider config (prefix, max_nodes, idle_tolerance, username, jump_*)."`.
- `M-ENTRYPOINTS-CONFIG-PARSER` (created by P2) gains `const-CLOUD_CONFIG_PARSERS`
  annotation and the `parse_clouds` / `parse_cloud_section` / `cloud_valid_fields`
  function annotations.
- CrossLinks: edges from `M-CLOUD-PROVISIONER`, `M-CLOUD-ADAPTERS-NEW`,
  `M-CLOUD-PROVIDER-SELECTION`, `M-CLOUD-PROVIDERS-*`, `M-APPLICATION-DEALLOCATE`,
  `M-APPLICATION-ORCHESTRATOR`, `M-ENTRYPOINTS-DI` that targeted `M-CONFIG-CLOUD`
  repoint to `M-CLOUD-CONFIGS` (for infra DTO consumers) or `M-DOMAIN-PORTS` (for
  application Protocol consumers).
- `M-CONFIG` (`config/config.py`) DEPENDS loses `M-CONFIG-CLOUD`; the cloud-assembly
  seam becomes a lazy import of `parse_clouds` from `M-ENTRYPOINTS-CONFIG-PARSER` (same
  pattern as P2's engine-assembly seam).

### Layers contract delta

- `infra/cloud/protocols.py` runtime import of `ConfigCloud` was an
  outside-layer-set exemption (`yascheduler.config` exempt from R3). After P3 the
  import is intra-package (`from .cloud_configs import ConfigCloud`) — the exemption is
  no longer needed for this edge.
- `application → infra` for cloud configs: `deallocate_nodes` and `orchestrator` switch
  their TYPE_CHECKING import from `yascheduler.config.ConfigCloud` to
  `yascheduler.domain.CloudConfig` — application→domain, R3-legal. No new
  `application → infra` runtime edge.
- `yascheduler.config` remains in the outside-layer-set exemption list (P4 removes it);
  P3 shrinks its surface (cloud re-exports gone) but does not remove the package.

## Open questions

None remaining — all architectural questions (Q5–Q9) are locked in
`docs/config-layer-split-plan.md` §3, and the registry-placement decision (D-b above)
is resolved here: registry lives in `entrypoints/config_parser.py` (R3-legal
direction). The only implementation-time discovery risk is the
`MagicMock(spec=ConfigCloud)` audit in tests (does any test rely on
`from_config_parser_section` or `get_valid_config_parser_fields` being on the DTO?);
tasks include an explicit grep for that.