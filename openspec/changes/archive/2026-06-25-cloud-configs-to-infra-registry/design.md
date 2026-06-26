## Context

`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`,
`AzureImageReference`, and the `ConfigCloud` Union live in
`yascheduler/config/cloud.py` as frozen attrs classes carrying
`from_config_parser_section` / `get_valid_config_parser_fields` classmethods.
`infra/cloud/protocols.py` runtime-imports `ConfigCloud` from `yascheduler.config` — a
layer crossing that only works because `yascheduler.config` is exempt from the R3
layers contract. `Config.from_config_parser` hardcodes the cloud variant list as a
tuple (`(ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI)`);
P1's append of `ConfigCloudVastAI` was a band-aid, not an open/closed solution.

Predecessor P1 (`ssh-keys-extraction-vastai-parser-fix`) extracted
`get_private_keys()` into `infra/ssh/keys.py::list_private_keys` and introduced the
`list_private_keys_fn` callable on `Orchestrator.__init__`. P2
(`engine-to-domain-frozen`) creates `entrypoints/config_parser.py` with the engine
parsers (`parse_engine_section`, `parse_engines`, `engine_valid_fields`) and moves
`Engine`/`EngineRepository`/`Deploy*` to `domain/engine.py`. P3 extends the same parser
module with cloud parsers and the registry; it does not touch the engine path or the
`list_private_keys_fn` callable.

This change is governed by `docs/config-layer-split-plan.md` §4 (P3) and §3 (locked
decisions Q5–Q9). The explore-brief
(`openspec/changes/cloud-configs-to-infra-registry/explore-brief.md`) is the frozen
checklist of relocation targets, the `CloudConfig` Protocol field set, the consumer
call-site table, the registry placement decision, and the test migration map.

Constraints:
- R3 layers contract (`entrypoints → infra → application → domain → shared`).
  After P3, `infra/cloud/protocols.py → ConfigCloud` is intra-package (R3-legal, no
  exemption needed for this edge). `application → domain` TYPE_CHECKING imports of
  `CloudConfig` are R3-legal. `entrypoints → infra` import of the DTOs is R3-legal.
- GRACE-lite: new `yascheduler/infra/cloud/cloud_configs.py` carries a MODULE_CONTRACT,
  MODULE_MAP, and CHANGE_SUMMARY; `domain/ports.py` gains a `START_CONTRACT: CloudConfig`
  block; `entrypoints/config_parser.py` (created by P2 or here) gains the cloud parser
  functions and the registry; `docs/knowledge-graph.xml` gets `M-CLOUD-CONFIGS` and loses
  `M-CONFIG-CLOUD`.
- `ConfigCloud*` field sets are preserved (no field removals); only the form
  (frozen attrs → frozen dataclass) and the parser location change.
- `CloudConfig` Protocol surface is exactly the 6 fields application-layer consumers
  read (`prefix`, `max_nodes`, `idle_tolerance`, `username`, `jump_username`,
  `jump_host`) — no more, no less. Provider-specific fields (`tenant_id`, `token`,
  `login`, `api_key`, `server_type`, `image_name`, `vm_size`, `disk_gb`, `min_vram_mb`,
  `num_gpus`, `max_price_per_hr`, `onstart_script`, `docker_options`, `env`,
  `resource_group`, `location`, `vnet`, `subnet`, `nsg`, `vm_image`, `priority`,
  `client_id`, `client_secret`, `subscription_id`) stay on the concrete DTOs and are
  accessed only by infra-layer consumers (`CloudProvisionerImpl`, provider modules).

## Goals / Non-Goals

**Goals:**
- The 5 cloud DTOs (`ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`,
  `ConfigCloudVastAI`, `AzureImageReference`) and the `ConfigCloud` Union are relocated
  to `yascheduler/infra/cloud/cloud_configs.py` as `@dataclass(frozen=True)` with no INI
  parsing methods and no attrs dependency. `AzureImageReference.from_urn` is retained
  (pure URN parsing, no `ConfigParser` dependency).
- The per-provider `from_config_parser_section` / `get_valid_config_parser_fields`
  classmethods and the `_check_az_user` / `_fmt_key` helpers move to
  `entrypoints/config_parser.py` as free functions (`parse_cloud_section`,
  `parse_clouds`, `cloud_valid_fields`, `_parse_azure_section`,
  `_parse_hetzner_section`, `_parse_upcloud_section`, `_parse_vastai_section`).
- `CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]]` lives in
  `entrypoints/config_parser.py`, mapping each prefix to its parser function. Adding a
  provider = one parser function + one registry entry; no aggregate-root edit.
- `Config.from_config_parser` delegates cloud assembly to `parse_clouds(cfg, remote)`
  via a lazy import inside the method (same pattern as P2's engine-assembly seam); the
  `cloud_variants` tuple, the `cloud_prefixes` derivation, the username-inheritance loop,
  and the `cloud_variants_match` filter move into `parse_clouds`.
- A structural `@runtime_checkable` `CloudConfig` Protocol is added to
  `domain/ports.py` with the 6-field surface. `deallocate_nodes` and `orchestrator`
  TYPE_CHECKING imports switch from `yascheduler.config.ConfigCloud` to
  `yascheduler.domain.CloudConfig`; the `config_clouds` / `active_clouds` parameter
  types change from `Sequence[ConfigCloud]` to `Sequence[CloudConfig]`.
- `infra/cloud/protocols.py` runtime import becomes intra-package
  (`from .cloud_configs import ConfigCloud`); the three `TypeVar(bound=ConfigCloud)`
  declarations continue to bind to the relocated Union.
- `infra/cloud/{adapters,provider_selection,manager}.py` and
  `infra/cloud/providers/{az,hetzner,upcloud,vastai}.py` TYPE_CHECKING imports switch
  to the intra-package or facade path.
- `yascheduler/config/cloud.py` is deleted; `yascheduler/config/__init__.py` drops the
  cloud re-exports; `yascheduler/infra/cloud/__init__.py` gains them from
  `.cloud_configs`.

**Non-Goals:**
- Moving `Config` aggregate / `ConfigLocal` / `ConfigRemote` / `ConfigDb` out of
  `yascheduler/config/` (P4).
- Removing `attrs` from the project dependency list (P5 — `config/config.py`,
  `config/db.py`, `config/remote.py` still use attrs; they move in P4).
- Changing `ConfigCloud*` field sets (no removals; only form and location change).
- Changing `CloudProvisionerImpl` provisioning behavior (`allocate`, `deallocate`,
  `select_provider` semantics unchanged; only the `configs` dict typing source moves).
- Migrating `config/utils.py` (`make_default_field`, `opt_str_val`,
  `warn_unknown_fields`) — they stay in `config/utils.py` until P4 removes the last
  consumers (`ConfigDb`, `ConfigLocal`, `ConfigRemote`). P3's cloud parsers import
  `warn_unknown_fields` and `opt_str_val` from `config/utils.py`.
- Introducing a `CloudConfig` implementation in `domain/` (the Protocol is structural;
  the DTOs in `infra/cloud/cloud_configs.py` satisfy it without inheritance).
- Removing `yascheduler.config` from the outside-layer-set exemption list or removing
  the `forbidden` contract (P4 — P3 only shrinks the exemption by one edge).

## Decisions

### D1: Frozen stdlib dataclasses, no attrs, no parser methods on DTOs

The 5 cloud DTOs become `@dataclass(frozen=True)` with plain field annotations and
defaults. The attrs `validators.instance_of`, `validators.ge(0)`, `validators.ge(1)`,
`opt_str_val`, and `_check_az_user` are **not** translated into `__post_init__` checks
on the dataclasses. Validation runs parser-side in `entrypoints/config_parser.py`
(matching P2's D2 decision for `Engine`): the parser functions call
`warn_unknown_fields`, validate ranges, and raise `ValueError` before constructing the
DTO. A DTO constructed directly (e.g., in tests) accepts any values — the frozen form
enforces immutability, not validity; validity is the parser's contract.

`AzureImageReference.from_urn` is retained: it parses a URN string
(`publisher:offer:sku:version`) and constructs the dataclass. It does not import
`ConfigParser`/`SectionProxy` — it is a pure string parser, not an INI parser. It stays
on the DTO (same as `Engine.validate_inputs` stays on `Engine` in P2 — pure domain
logic, not INI parsing).

Rejected alternatives:
- **attrs frozen** — rejected: project policy is to migrate off attrs; P3 removes the
  largest attrs consumer in the cloud path (`config/cloud.py`).
- **`__post_init__` validation on the DTO** — rejected: couples the DTO to validation
  rules and makes direct construction in tests error-prone. Parser-side validation
  matches P2's precedent and keeps the DTO pure.
- **Keep `from_config_parser_section` as a classmethod** — rejected: DTOs must not
  import `ConfigParser`/`SectionProxy`; parsing is an adapter concern belonging at the
  composition root (entrypoints).

### D2: Registry placement — `entrypoints/config_parser.py` (Decision b)

The `CLOUD_CONFIG_PARSERS` registry maps each provider prefix to a parser callable.
Two placement options were considered (see explore-brief "Module placement tension"):

- **(a)** Registry in `infra/cloud/cloud_configs.py`, importing parser functions from
  `entrypoints/config_parser.py` — violates R3 (`infra → entrypoints`).
- **(b)** Registry in `entrypoints/config_parser.py`, importing DTO classes from
  `infra/cloud/cloud_configs.py` — R3-legal (`entrypoints → infra`).

**Decision: (b).** The registry lives at the composition-root layer alongside the
parser functions it references. The cloud subpackage owns the DTOs and the `ConfigCloud`
Union; the entrypoints layer owns the parsers and the registry. This keeps the
dependency direction legal and matches the P2 decision that parsers live at the
composition root. The umbrella plan §4 P3 placed the registry in `infra/cloud/`; the
explore-brief Decision (b) corrects this — the proposal and design follow Decision (b).

The registry is a module-level constant built once at import time; the parser
functions are defined above it in the same module. `parse_clouds(cfg, remote)`
iterates `CLOUD_CONFIG_PARSERS`, and for each prefix present in `[clouds]` options,
dispatches to the per-prefix parser. The username-inheritance loop (currently in
`Config.from_config_parser`: for each prefix, if `{prefix}_user` is absent, inherit
`remote.username`) moves into `parse_clouds` so the parser sees the inherited
username.

### D3: `Config.from_config_parser` cloud assembly — lazy import (same as P2 engines)

`Config.from_config_parser` currently hardcodes the cloud variant tuple and the
username-inheritance loop. After P3:

- `Config.from_config_parser` delegates cloud assembly to
  `parse_clouds(cfg, remote)` from `entrypoints/config_parser.py` via a lazy import
  inside the method (the same pattern P2 uses for `parse_engines`). The
  `cloud_variants` tuple, the `cloud_prefixes` derivation, the username-inheritance
  loop, and the `cloud_variants_match` filter move into `parse_clouds`.
- `Config` stays constructible in one call — `Config.from_config_parser(path)` still
  returns a fully populated `Config` with `clouds` populated via the registry. The
  lazy import is documented with a TODO referencing P4 (when `Config` moves to
  entrypoints and the import becomes intra-package).

This matches P2's engine-assembly decision (P2 design D7): the hybrid
`Config.from_config_parser` delegates engine assembly to `parse_engines` and cloud
assembly to `parse_clouds`; db/local/remote assembly stays inline until P4. P3 and P2
compose cleanly — both add a lazy-imported `parse_*` call to the same method; no
conflict.

Rejected: move cloud assembly entirely to the composition root (`entrypoints/di.py`)
and drop it from `Config.from_config_parser`. Rejected because it would require
`di.py` to assemble clouds separately and pass them into `Config`, splitting the
construction contract. The lazy-import hybrid keeps `Config` constructible in one call
and minimizes the surface change — only the cloud path is extracted.

### D4: `CloudConfig` Protocol — structural, 6 fields, application-only

`CloudConfig` is a `@runtime_checkable` Protocol in `domain/ports.py` with 6 fields:
`prefix: str`, `max_nodes: int`, `idle_tolerance: int`, `username: str`,
`jump_username: str | None`, `jump_host: str | None`. This is exactly the surface
application-layer consumers read:
- `deallocate_nodes`: `ccfg.prefix`, `ccfg.idle_tolerance`.
- `orchestrator._clouds_get_capacity`: `c.max_nodes`, `c.prefix`.
- `orchestrator._connect_machine_consumer`: `cloud.prefix`, `cloud.jump_host`,
  `cloud.jump_username`.

Precedent: `OccupancyConfig` and `TaskExecutionEngine` already live in `domain/ports.py`
as structural Protocols. `CloudConfig` follows the same pattern. The cloud DTOs satisfy
it structurally (no explicit inheritance); `application → infra` stays TYPE_CHECKING-only
because application types against the domain Protocol, not the infra DTOs.

Infra-layer consumers (`CloudProvisionerImpl`, provider modules) stay typed against the
concrete `ConfigCloud*` DTOs because they access provider-specific fields (`tenant_id`,
`token`, `login`, `api_key`, `server_type`, `vm_size`, etc.) that are not on the
Protocol. This is correct: infra→infra is legal, and the Protocol is for application
decoupling, not for infra.

Rejected alternatives:
- **Nominal Protocol (explicit inheritance)** — rejected: breaks the structural
  precedent and forces every DTO to declare `class ConfigCloudAzure(CloudConfig)`.
  Structural satisfaction is idiomatic for this project (`OccupancyConfig` does it).
- **Wider Protocol including provider-specific fields** — rejected: application never
  reads `tenant_id` or `token`; exposing them on the domain Protocol would couple
  domain to provider specifics and violate ISP.
- **Narrower Protocol (only `prefix` + `max_nodes`)** — rejected: `deallocate_nodes`
  needs `idle_tolerance`; `orchestrator._connect_machine_consumer` needs `jump_*`. The
  6-field set is the minimal complete surface.

### D5: `infra/cloud/protocols.py` import becomes intra-package

`infra/cloud/protocols.py:37` currently does
`from yascheduler.config import ConfigCloud` (runtime). After P3 it becomes
`from .cloud_configs import ConfigCloud` (intra-package, relative within the
`infra.cloud` subpackage — R1-compliant). The three `TypeVar(bound=ConfigCloud)`
declarations (`TConfigCloud_inv`, `TConfigCloud_co`, `TConfigCloud_contra`) continue to
bind to the relocated Union; no change to their semantics.

This removes the only runtime `infra → yascheduler.config` edge in the cloud subpackage.
The outside-layer-set exemption for `yascheduler.config` shrinks by one edge but the
package remains exempt (P4 removes it).

### D6: Provider module imports — facade path

`infra/cloud/providers/{az,hetzner,upcloud,vastai}.py` currently TYPE_CHECKING-import
`ConfigCloudX` from `yascheduler.config`. After P3 they import from
`yascheduler.infra.cloud` (the subpackage facade):

```python
from yascheduler.infra.cloud import ConfigCloudAzure, AzureImageReference  # az.py
from yascheduler.infra.cloud import PCloudConfig  # already the case
```

This matches the existing provider-module style (`from yascheduler.infra.cloud import
get_rnd_name`) and is R2-compliant (facade import, not deep path). The alternative
intra-package relative import (`from ..cloud_configs import ConfigCloudAzure`) is
R1-legal but inconsistent with the provider modules' existing facade-import style; the
facade path is preferred for consistency.

`infra/cloud/{adapters,provider_selection,manager}.py` use intra-package relative
imports for `ConfigCloud` (`from .cloud_configs import ConfigCloud`) since they sit
inside the `infra.cloud` subpackage and the R1 rule prefers relative within-package
imports.

### D7: `_connect_to_vm` getattr fallbacks — direct attribute access

`CloudProvisionerImpl._connect_to_vm` currently uses
`getattr(config, "jump_host", None) or None` and
`getattr(config, "jump_username", None) or None`. After P3, all 4 DTOs declare
`jump_host: str | None` and `jump_username: str | None` as fields (they already do
today), so the `getattr` fallbacks can become direct attribute access:
`config.jump_host or None` / `config.jump_username or None`. This is a non-breaking
improvement (the `or None` normalizes empty strings to `None`, preserving behavior)
and removes the `getattr` defensive pattern that existed because the field presence was
implicit. This is an optional cleanup; if it risks scope creep, it can be deferred to
P4. The proposal lists it as a `cloud-provisioner` delta note; tasks include it as a
small, explicit step.

## Risks / Trade-offs

- **`MagicMock(spec=ConfigCloud)` interface drift** → Mitigation: `ConfigCloud` is a
  `Union`, not a class; `MagicMock(spec=ConfigCloud)` is unusual (spec against a Union
  raises `TypeError` in older Python; in 3.10+ it's allowed but introspects the first
  member). The audit in tasks greps for `spec=ConfigCloud` and `spec=ConfigCloudAzure`
  etc.; any test relying on `from_config_parser_section` or
  `get_valid_config_parser_fields` being on the DTO's spec breaks and migrates to the
  parser functions. The concrete DTO classes keep their fields (no field removal), so
  `MagicMock(spec=ConfigCloudAzure)` with attribute access (`cfg.tenant_id`) continues
  to work.
- **Parser locality loss** → Trade-off: `from_config_parser_section` no longer lives
  next to the fields. Mitigation: `cloud_valid_fields(prefix)` documents the per-prefix
  INI key list (including aliases like `user` for `username`, `jump_user` for
  `jump_username`, `image` for `vm_image`, `size` for `vm_size`) in the parser module;
  `warn_unknown_fields` is called from the parser. The INI contract is documented in
  one place (the parser), not split across DTOs.
- **`Config.from_config_parser` partial extraction** → Trade-off: cloud assembly is
  extracted to the parser module, but db/local/remote/engine assembly stays in
  `Config.from_config_parser` (engine via P2's `parse_engines`, db/local/remote inline
  until P4). This leaves `Config.from_config_parser` as a hybrid for one proposal
  cycle. Mitigation: the hybrid is explicitly documented with a TODO referencing P4; the
  cloud path is the second extracted one (after engines), keeping the surface minimal.
- **`attrs` still in `config/config.py`, `config/db.py`, `config/remote.py`** →
  Trade-off: P3 removes attrs from `config/cloud.py` (deleted) but not from the other
  config modules. `config/utils.py` (`make_default_field`, `opt_str_val`,
  `warn_unknown_fields`) stays because `ConfigDb`/`ConfigLocal`/`ConfigRemote` still
  consume it (they move in P4). Mitigation: `utils.py` migration is deferred to P4 when
  its last consumers move; P3 does not touch `config/utils.py`.
- **Registry import-time ordering** → Trade-off: the registry is a module-level
  constant in `entrypoints/config_parser.py`, built after the parser functions are
  defined. There is no import-time side-effect dependency — the parser functions and
  the registry are in the same module, so the order is deterministic. `parse_clouds`
  references `CLOUD_CONFIG_PARSERS` at call time, not import time, so there is no
  ordering risk even if a provider module is imported later. Mitigation: none needed;
  the design is order-independent by construction.
- **`CloudConfig` Protocol vs `ConfigCloud` Union confusion** → Trade-off: two names
  for overlapping concepts. `CloudConfig` (domain Protocol, 6 fields) is the
  application-facing contract; `ConfigCloud` (infra Union, full provider DTOs) is the
  infra-facing union. Tests and code must choose correctly. Mitigation: the proposal
  and tasks document the rule — application tests use `CloudConfig`; infra tests and
  provider modules use `ConfigCloud`. The naming distinction (`CloudConfig` Protocol vs
  `ConfigCloud` Union) is deliberate and matches the existing pattern (`OccupancyConfig`
  Protocol vs `Engine` class).

## Migration Plan

Single-repo, single-PR change. No runtime migration, no DB migration, no config-file
format change. The INI format (`[clouds]` section with `{prefix}_*` keys) and `Config`
public surface are unchanged from the operator's perspective.

Steps (mirror tasks.md ordering):
1. Create `yascheduler/infra/cloud/cloud_configs.py` with the 5 frozen dataclasses +
   `ConfigCloud` Union + `AzureImageReference.from_urn`. No parser methods.
2. Add the cloud parser functions + `_check_az_user` + `_fmt_key` helpers +
   `CLOUD_CONFIG_PARSERS` registry to `entrypoints/config_parser.py` (extending the P2
   module; create the module with only cloud parsers if P2 is not yet implemented).
3. Add the `CloudConfig` structural Protocol to `domain/ports.py`; re-export from
   `yascheduler.domain`.
4. Update `config/config.py::Config.from_config_parser` to delegate cloud assembly to
   `parse_clouds(cfg, remote)` via lazy import; delete the `cloud_variants` tuple,
   `cloud_prefixes` derivation, username-inheritance loop, and `cloud_variants_match`
   filter from `Config.from_config_parser` (they move into `parse_clouds`).
5. Delete `config/cloud.py`; update `config/__init__.py` to drop cloud re-exports;
   update `config/config.py` to drop the `from .cloud import (...)` block AND add the
   replacement import `from yascheduler.infra.cloud import ConfigCloud` (R2 facade) so
   the `Config.clouds: Sequence[ConfigCloud]` field annotation still resolves (the
   Union now lives in the cloud subpackage; the lazy `parse_clouds` import in step 4
   returns `list[CloudConfig]`-compatible DTOs that satisfy the Union). Note: after P3,
   `config/config.py` has a runtime `entrypoints → infra` edge via this import — but
   `config/` is outside-layer-set (exempt from R3) until P4 removes the package, so the
   edge is legal under the current exemption. P4 eliminates it when `Config` moves to
   `entrypoints` and the import becomes intra-package.
6. Update `infra/cloud/__init__.py` to re-export the DTOs + Union +
   `AzureImageReference` from `.cloud_configs`.
7. Switch `infra/cloud/protocols.py` runtime import to intra-package;
   `infra/cloud/{adapters,provider_selection,manager}.py` and
   `infra/cloud/providers/{az,hetzner,upcloud,vastai}.py` TYPE_CHECKING imports to the
   facade or intra-package path.
8. Switch `application/deallocate_nodes.py` and `application/orchestrator.py`
   TYPE_CHECKING imports: `ConfigCloud` → `CloudConfig`; update
   `config_clouds`/`active_clouds` parameter types to `Sequence[CloudConfig]`.
9. Update `entrypoints/di.py` TYPE_CHECKING: `ConfigCloud` → `CloudConfig` (for
   `active_clouds` typing); keep `Config`, `ConfigLocal`, `ConfigRemote` until P4.
10. Optionally simplify `CloudProvisionerImpl._connect_to_vm` `getattr` fallbacks to
    direct attribute access (D7).
11. Update `docs/knowledge-graph.xml`: add `M-CLOUD-CONFIGS`, remove `M-CONFIG-CLOUD`,
    repoint CrossLinks, add `protocol-CloudConfig` annotation to `M-DOMAIN-PORTS`.
12. Migrate tests: `from yascheduler.config.cloud import ...` →
    `from yascheduler.infra.cloud import ...`; `ConfigCloudX.from_config_parser_section`
    → `parse_cloud_section`; `from yascheduler.config import ConfigCloud` →
    `from yascheduler.infra.cloud import ConfigCloud` (DTO) or
    `from yascheduler.domain import CloudConfig` (Protocol).
13. Run `uv run pytest -m unit`, `uv run pytest -m integration`, `uv run lint-imports`,
    `python3 scripts/grace_check.py`, `openspec validate --all --json`.

Rollback: revert the single PR. No data format or persisted-state change exists, so
rollback is clean. The INI format is unchanged; the only externally visible effect is
the import-path change for code that imported `ConfigCloud*` from `yascheduler.config`
(BREAKING, documented).

## Open Questions

None. All architectural questions (Q5–Q9) are locked in
`docs/config-layer-split-plan.md` §3. The registry-placement decision (D2) is resolved
in the explore-brief (Decision b). The `MagicMock(spec=ConfigCloud)` audit is an
implementation-time discovery task in tasks.md, not an open question. The D7
`getattr`→direct-access cleanup is optional and scoped; if it proves noisy, it is
deferred to P4 without affecting P3's core goals.