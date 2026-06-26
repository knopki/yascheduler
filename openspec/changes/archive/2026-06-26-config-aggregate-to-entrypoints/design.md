## Context

After P1 (`ssh-keys-extraction-vastai-parser-fix`), P2 (`engine-to-domain-frozen`), and
P3 (`cloud-configs-to-infra-registry`), `yascheduler/config/` is down to six files:
`__init__.py` (re-export hub), `config.py` (`Config` aggregate + `from_config_parser`),
`db.py` (`ConfigDb`, attrs), `local.py` (`ConfigLocal`, already stdlib dataclass after
P1), `remote.py` (`ConfigRemote`, attrs), `utils.py` (parser helpers, attrs). The
domain value objects (`Engine`, `EngineRepository`, `Deploy*`) moved to
`domain/engine.py` in P2; the cloud DTOs (`ConfigCloud*`, `AzureImageReference`) moved
to `infra/cloud/cloud_configs.py` in P3 with a `CloudConfig` Protocol in
`domain/ports.py` and a `CLOUD_CONFIG_PARSERS` registry in `entrypoints/config_parser.py`.

What remains is genuine cross-layer configuration: PG connection params, daemon paths
and concurrency limits, SSH defaults. But the package is still exempt from the R3 layers
contract, and three structural defects persist:

1. `Orchestrator.__init__` takes `config: Config` and reads `config.local.*`,
   `config.remote.*`, `config.clouds` at runtime. Once `Config` moves to `entrypoints`,
   that access is an `application → entrypoints` R3 violation.
2. `Config.from_config_parser` lazily imports `parse_engines` from
   `entrypoints/config_parser.py` (P2 seam); `pyproject.toml:137-139` has an
   `ignore_imports` entry tagged `TODO(P4)`. The seam exists only because the aggregate
   is outside `entrypoints` while the parser is inside.
3. `config/db.py` and `config/remote.py` still use attrs; `config/utils.py` is the last
   home of `make_default_field` / `warn_unknown_fields` / `opt_str_val` and exists only
   to serve the parser.

This change is governed by `docs/config-layer-split-plan.md` §4 (P4) and §3 (locked
decisions Q5–Q9). P4 is the final structural move: redistribute the remaining settings,
delete the package, collapse the exemption.

Constraints:
- R3 layers contract (`entrypoints → infra → application → domain → shared`). After P4,
  `application → domain` imports of `LocalSettings` / `RemoteDefaults` are R3-legal.
  `infra → domain` imports of the same are R3-legal. `entrypoints → infra` import of
  `PostgresDbConfig` is R3-legal. `entrypoints → domain` import of
  `LocalSettings` / `RemoteDefaults` / `EngineRepository` / `CloudConfig` is R3-legal.
  `application → entrypoints` is R3-illegal — the orchestrator must not import `Config`.
- GRACE-lite: new `domain/settings.py`, `infra/persistence/db_config.py`,
  `entrypoints/config.py` carry MODULE_CONTRACT, MODULE_MAP, and CHANGE_SUMMARY;
  `entrypoints/config_parser.py` gains `parse_config` + db/local/remote parser
  functions + the relocated utils; `docs/knowledge-graph.xml` loses the six `M-CONFIG*`
  nodes and gains `M-DOMAIN-SETTINGS`, `M-INFRA-DB-CONFIG`, `M-ENTRYPOINTS-CONFIG`.
- Field sets are preserved (no field removals on `ConfigLocal`/`ConfigRemote`/`ConfigDb`);
  only the form (attrs → frozen dataclass where not already done), the name
  (`ConfigLocal` → `LocalSettings`, `ConfigRemote` → `RemoteDefaults`, `ConfigDb` →
  `PostgresDbConfig`), and the parser location change.
- Public API stability: `from yascheduler import Yascheduler`, `CONFIG_FILE`,
  `LOG_FILE`, `PID_FILE`, `from yascheduler.client import Yascheduler` are all outside
  `yascheduler.config` and unaffected. No public symbol is re-exported through
  `yascheduler.config` today (verified against the package-facades spec).
- The `ignore_imports` seam in `pyproject.toml` is P4's to remove; the `forbidden`
  contract is P4's to remove; the outside-layer-set exemption list entry for
  `yascheduler.config` is P4's to remove.

## Goals / Non-Goals

**Goals:**
- `LocalSettings` and `RemoteDefaults` are frozen stdlib dataclasses in
  `yascheduler/domain/settings.py`; no INI parsing on the DTOs; importable from
  `yascheduler.domain`.
- `PostgresDbConfig` is a frozen stdlib dataclass in
  `yascheduler/infra/persistence/db_config.py`; no INI parsing on the DTO; importable
  from `yascheduler.infra.persistence`.
- `Config` is a frozen stdlib dataclass in `yascheduler/entrypoints/config.py` with
  fields `db`, `local`, `remote`, `clouds`, `engines`; importable from
  `yascheduler.entrypoints`.
- `parse_config(path) -> Config` lives in `entrypoints/config_parser.py` and owns all
  per-section parsing (`_parse_db_section`, `_parse_local_section`,
  `_parse_remote_section`, `parse_engines`, `parse_clouds`) plus the relocated
  `make_default_field` / `warn_unknown_fields` / `opt_str_val` / `ConfigWarning` helpers.
  Validation runs parser-side, not in dataclass `__post_init__`.
- `Orchestrator.__init__` drops `config: Config`; accepts `local_settings:
  LocalSettings` and `remote_defaults: RemoteDefaults`; retains `list_private_keys_fn`
  (P1) and `config_clouds` / `active_clouds` (`CloudConfig` Protocol, P3). The
  orchestrator never imports `yascheduler.entrypoints`.
- `yascheduler/config/` is deleted. The `ignore_imports` seam, the `forbidden` contract,
  and the outside-layer-set exemption list entry are all removed.
- 26 `config.<field> = ...` mutation sites in 7 test files migrate to
  `dataclasses.replace(config, ...)` or a `ConfigBuilder` helper.

**Non-Goals:**
- Migrating the remaining attrs users in `infra/cloud/` (`manager.py`,
  `providers/az.py`) — that is P5.
- Removing `attrs` from `pyproject.toml` — P5.
- Changing the `Config` field set (no fields added or removed relative to the current
  aggregate).
- Changing the INI format or the `[local]` / `[remote]` / `[db]` section keys.
- Touching the `gateway-sftp-wrapping` residuals
  (`application.{consume_task,orchestrator} -> yascheduler.infra` `ignore_imports`) —
  those are tracked separately in the package-facades spec.
- Renaming `Config` itself — the aggregate keeps its name; only its home changes.

## Decisions

### D1: `LocalSettings` / `RemoteDefaults` live in `domain`, not `infra` or `entrypoints`

**Choice:** `domain/settings.py`.

**Rationale:** Both DTOs are consumed by `application` (orchestrator reads
`local.keys_dir`, `local.{conn_machine,allocate,consume,deallocate}_limit`,
`remote.{data_dir,engines_dir,tasks_dir,jump_host,jump_username}`) and by `entrypoints`
(CLIs read `local.webhook_url`, `remote.username`, `remote.engines_dir`). Placing them
in `infra` would force `application → infra` (R3 violation). Placing them in
`entrypoints` would force `application → entrypoints` (R3 violation). `domain` is the
only layer both `application` and `entrypoints` may import from. Precedent: the
`CloudConfig` Protocol (P3) and `OccupancyConfig` already live in `domain/ports.py` as
cross-layer structural contracts.

**Rejected:**
- `infra/ssh/settings.py` for `RemoteDefaults` — would force `application → infra`.
- `entrypoints/settings.py` — would force `application → entrypoints`.
- Splitting `LocalSettings` so that concurrency limits live in `application` and paths
  live in `domain` — fragments one INI section across layers; the parser would need to
  know two homes. YAGNI until a consumer needs only a subset.

### D2: `PostgresDbConfig` lives in `infra/persistence`, not `domain`

**Choice:** `infra/persistence/db_config.py`.

**Rationale:** Only two consumers: `postgres_uow.py` and `postgres_schema.py`, both in
`infra/persistence`. No `application` or `domain` module reads DB connection params.
Placing it in `domain` would pull a persistence-specific concept (PG connection) into
the domain layer. Placing it in `entrypoints` would force `infra → entrypoints` (R3
violation). `infra/persistence` is the natural home; the two consumers become
intra-package.

**Rejected:**
- `domain/db_config.py` — DB connection is an adapter concern, not a domain concept.
- `entrypoints/db_config.py` — `infra → entrypoints` is R3-illegal.

### D3: `Config` aggregate lives in `entrypoints`, not `domain` or `application`

**Choice:** `entrypoints/config.py`.

**Rationale:** The aggregate is a composition-root concept: it bundles settings from
multiple layers (`PostgresDbConfig` from infra, `LocalSettings`/`RemoteDefaults` from
domain, `CloudConfig*` from infra, `EngineRepository` from domain) for delivery to the
orchestrator and CLIs. Only `entrypoints` (the composition root `di.py`, the daemon
launchers, the CLIs) consumes it. Placing it in `domain` would make `domain` depend on
`infra` (`PostgresDbConfig`, `ConfigCloud*`) — R3 violation. Placing it in
`application` would make `application` depend on `infra` — R3 violation. `entrypoints`
is the outermost layer and may import from all inner layers.

**Rejected:**
- `domain/config.py` — would force `domain → infra` for `PostgresDbConfig` /
  `ConfigCloud*`.
- `application/config.py` — would force `application → infra`.
- Keep `Config` in a residual `yascheduler.config` package — defeats the purpose of P4;
  the outside-layer-set exemption is the defect being removed.

### D4: Orchestrator takes unpacked settings, not the aggregate

**Choice:** `Orchestrator.__init__` drops `config: Config` and accepts
`local_settings: LocalSettings`, `remote_defaults: RemoteDefaults`. The
`list_private_keys_fn` callable (P1) is retained.

**Rationale:** Once `Config` lives in `entrypoints`, `Orchestrator` (in `application`)
cannot import it without an R3 violation. The orchestrator reads exactly two sub-configs
(`local` and `remote`) plus `config_clouds` (already a separate parameter). Passing the
whole aggregate would re-introduce the `application → entrypoints` edge; passing the
unpacked settings keeps `application → domain` only. The `list_private_keys_fn`
callable (P1) already demonstrated the pattern: inject the capability, don't import the
layer. P4 extends the same pattern to `local_settings` / `remote_defaults`.

**Rejected:**
- Pass `Config` and have the orchestrator import it from `entrypoints` under
  `TYPE_CHECKING` only — runtime reads of `self._config.local.*` still require the
  instance, and the instance is constructed in `entrypoints`; the orchestrator would
  still depend on the `entrypoints`-defined type at runtime via attribute access. The
  TYPE_CHECKING guard is for type annotations, not for runtime attribute access on a
  passed instance whose class is defined in a forbidden layer.
- Pass `config.local` and `config.remote` as the existing `ConfigLocal` / `ConfigRemote`
  types (without renaming) — the rename to `LocalSettings` / `RemoteDefaults` is part of
  the locked decisions (Q-names without the orphaned `Config*` prefix).
- Pass each scalar field individually (`keys_dir`, `conn_machine_limit`, ...) — explodes
  the parameter list from 2 to ~19; the orchestrator already has 12 parameters; another
  17 is unreadable.

### D5: Parser helpers (`make_default_field`, `warn_unknown_fields`, `opt_str_val`, `ConfigWarning`) relocate to `entrypoints`

**Choice:** Move into `entrypoints/config_parser.py` (or a sibling
`entrypoints/_config_utils.py` if the parser module would exceed the GRACE-lite 500-line
soft limit).

**Rationale:** These helpers exist only to serve the parser. `make_default_field` is an
attrs-field factory (becomes a stdlib default-with-validation helper after migration);
`warn_unknown_fields` emits `ConfigWarning` for unknown INI keys; `opt_str_val` is an
attrs validator (becomes a parser-side `Optional[str]` coercion). They have no domain
meaning and no consumer outside the parser. Co-locating them with the parser keeps the
INI contract in one module.

**Rejected:**
- `domain/settings_utils.py` — the helpers are parser concerns, not domain logic.
- `shared/config_utils.py` — `shared` is the shared kernel for typing primitives consumed
  by ≥2 architectural layers; these helpers are consumed by one module (the parser).
- Keep `config/utils.py` as a standalone module outside `config/` — creates a stray
  one-file package with no layer home; the package-facades spec has no exemption for it.

### D6: Test mutation migration uses `dataclasses.replace`, with a `ConfigBuilder` fallback

**Choice:** Migrate `config.engines = engines` →
`dataclasses.replace(config, engines=engines)` at each of the 26 sites. If a test file
has ≥4 such sites, introduce a `ConfigBuilder` helper in `tests/unit/conftest.py` to
avoid `replace`-chains.

**Rationale:** `Config` becomes frozen; direct attribute assignment raises
`FrozenInstanceError`. `dataclasses.replace` is the stdlib idiom and preserves the
frozen contract. A `ConfigBuilder` is only justified where repetition is high — the
7 files have an average of ~3.7 sites each, so most files use `replace` directly; only
`test_di.py` (6 sites) and `test_application_orchestrator.py` (4 sites) may warrant the
builder.

**Rejected:**
- Make `Config` mutable for test convenience — defeats D3 (frozen composition-root value
  object) and the locked decision Q8.
- A full `ConfigBuilder` in production code — YAGNI; only tests need mutation.
- `pytest` fixtures returning a mutable copy — hides the frozen contract from the test;
  `replace` makes the immutability visible at each call site.

### D7: Collapse the `config.clouds` duplicate read in `_connect_machine_consumer`

**Choice:** The orchestrator's `_connect_machine_consumer`
(`application/orchestrator.py:229`) currently iterates `self._config.clouds` to find a
matching cloud for a machine IP. After P4, `self._config` is gone. The iteration is
repointed to `self._config_clouds` (already a parameter, already typed against the
`CloudConfig` Protocol, already iterated in `deallocate_nodes` and elsewhere).

**Rationale:** `self._config_clouds` and `self._config.clouds` hold the same data (the
composition root passes `config.clouds` as `config_clouds`); the duplicate read is an
artifact of the orchestrator taking both the aggregate and the unpacked list. P4
collapses it.

**Rejected:**
- Keep a separate `self._clouds_for_connect` field — duplicates `self._config_clouds`
  for no reason.

## Risks / Trade-offs

- **Orchestrator signature churn** → The `__init__` parameter list changes (drops
  `config`, adds `local_settings` / `remote_defaults`). Every test constructing an
  `Orchestrator` directly (`test_application_orchestrator.py`) and the composition root
  (`di.py`) must update. Mitigation: the change is mechanical; the parameter count drops
  by 1 (net +1 after adding 2 and removing 1); `di.py` already has all the values.
- **Test mutation migration scope** → 26 sites across 7 files. Mitigation: each file is
  independent; `replace` is a one-line change per site; the `ConfigBuilder` helper
  absorbs the high-density files. The churn is intentional — merging it with P2's test
  migration would create one large proposal.
- **`MagicMock(spec=ConfigDb)` drift** → `postgres_uow.py` and `postgres_schema.py` may
  use `MagicMock(spec=ConfigDb)`; after rename to `PostgresDbConfig`, the `spec` target
  must update. Mitigation: P4 audits these sites; `spec` checks the class identity, so
  the rename is a one-line change per site.
- **`patch("yascheduler.config...")` targets** → tests patching `yascheduler.config.*`
  paths break. Mitigation: grep for `patch("yascheduler.config` and repoint to the new
  paths (`yascheduler.entrypoints.config`, `yascheduler.entrypoints.config_parser`,
  `yascheduler.domain.settings`, `yascheduler.infra.persistence.db_config`). The number
  is small (estimated <10 sites).
- **Parser module size** → `entrypoints/config_parser.py` already has the engine parsers
  (P2) and the cloud parsers + registry (P3); P4 adds db/local/remote parsers + the
  relocated utils + `parse_config`. This may approach the GRACE-lite 500-line soft
  limit. Mitigation: if the module exceeds 500 lines, split the relocated utils into
  `entrypoints/_config_utils.py` (sibling, underscore-private) and keep
  `config_parser.py` for the parsers + `parse_config`. Decision is made at implementation
  time based on actual line count.
- **`entrypoints → infra` import of `PostgresDbConfig`** → the `Config` aggregate in
  `entrypoints` references `PostgresDbConfig` from `infra`. This is R3-legal
  (`entrypoints → infra` is the layer direction), but it means `entrypoints/config.py`
  imports from `infra.persistence`. Mitigation: this is the composition root's job —
  wiring types from inner layers is what `entrypoints` does. The `Config` dataclass
  field is typed `db: PostgresDbConfig`; the import is `from yascheduler.infra.persistence
  import PostgresDbConfig` (facade, R2-compliant).

## Migration Plan

1. Create `yascheduler/domain/settings.py` with `LocalSettings` and `RemoteDefaults` as
   frozen dataclasses (field sets copied from `config/local.py` and `config/remote.py`).
   No parser methods. Add MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY. Re-export from
   `yascheduler/domain/__init__.py`.
2. Create `yascheduler/infra/persistence/db_config.py` with `PostgresDbConfig` as a
   frozen dataclass (field set copied from `config/db.py`). No parser methods. Add
   MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY. Re-export from
   `yascheduler/infra/persistence/__init__.py`.
3. Extend `entrypoints/config_parser.py`: add `_parse_db_section`, `_parse_local_section`,
   `_parse_remote_section`, `_db_valid_fields`, `_local_valid_fields`,
   `_remote_valid_fields`, and the public `parse_config(path) -> Config`. Relocate
   `make_default_field`, `warn_unknown_fields`, `opt_str_val`, `ConfigWarning` from
   `config/utils.py` (migrate to stdlib; drop attrs). If the module exceeds 500 lines,
   split utils into `entrypoints/_config_utils.py`.
4. Create `yascheduler/entrypoints/config.py` with `Config` as a frozen dataclass
   (`db: PostgresDbConfig`, `local: LocalSettings`, `remote: RemoteDefaults`,
   `clouds: Sequence[CloudConfig]`, `engines: EngineRepository`). Re-export from
   `yascheduler/entrypoints/__init__.py`.
5. Update `application/orchestrator.py`: drop `config: Config` from `__init__`; add
   `local_settings: LocalSettings`, `remote_defaults: RemoteDefaults`; replace
   `self._config` with `self._local_settings` / `self._remote_defaults`; repoint all
   `self._config.local.*` → `self._local_settings.*`, `self._config.remote.*` →
   `self._remote_defaults.*`; collapse `self._config.clouds` → `self._config_clouds`.
   Update the MODULE_CONTRACT and the `__init__` contract.
6. Update `entrypoints/di.py::make_daemon`: import `Config` from
   `yascheduler.entrypoints.config`; unpack `config.local` → `local_settings`,
   `config.remote` → `remote_defaults` when constructing `Orchestrator`.
7. Update `infra/persistence/postgres_uow.py` and `postgres_schema.py`:
   `from yascheduler.config import ConfigDb` →
   `from .db_config import PostgresDbConfig` (intra-package); rename type annotations.
8. Update `entrypoints/cli/*.py` and `entrypoints/client.py`:
   `from yascheduler.config import Config` → `from yascheduler.entrypoints import Config`.
9. Delete `yascheduler/config/` (all six remaining files).
10. Update `pyproject.toml`: remove the `ignore_imports` entry
    (`yascheduler.config.config -> yascheduler.entrypoints.config_parser`); remove the
    `forbidden` contract (`Shared kernel has no config imports`).
11. Update `docs/knowledge-graph.xml`: remove `M-CONFIG`, `M-CONFIG-DB`, `M-CONFIG-LOCAL`,
    `M-CONFIG-REMOTE`, `M-CONFIG-UTILS`, `M-CONFIG-HUB`; add `M-DOMAIN-SETTINGS`,
    `M-INFRA-DB-CONFIG`, `M-ENTRYPOINTS-CONFIG`; repoint CrossLinks.
12. Migrate tests: 7 files with 26 `config.<field> = ...` sites →
    `dataclasses.replace(config, ...)` or `ConfigBuilder`; update imports; repoint
    `patch(...)` targets.
13. Update OpenSpec specs: `package-facades` (remove `yascheduler.config` from
    outside-layer-set; remove the `forbidden` contract requirement; remove the
    `ignore_imports` entry; update facade re-export lists), `orchestrator` (new
    `__init__` signature), `dependency-injection` (unpacking), `testing-unit` (mutation
    migration).

Rollback: revert the commit. The change is self-contained — no data migration, no
external API surface change, no INI format change. The `yascheduler.config` package is
restored from git. The only forward-only artifact is the OpenSpec spec deltas (archived
with the change).

## Open Questions

None. All architectural decisions are locked in `docs/config-layer-split-plan.md` §3
(Q5–Q9) and D1–D7 above. The parser-module-size split (step 3) is decided at
implementation time based on the actual line count.