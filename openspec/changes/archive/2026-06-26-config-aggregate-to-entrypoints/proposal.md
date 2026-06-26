## Why

`yascheduler/config/` is the last survivor of the config-layer split. After P1
(`ssh-keys-extraction-vastai-parser-fix`), P2 (`engine-to-domain-frozen`), and P3
(`cloud-configs-to-infra-registry`), only four files and one aggregate remain:
`config/config.py::Config`, `config/db.py::ConfigDb`, `config/local.py::ConfigLocal`,
`config/remote.py::ConfigRemote`, plus `config/utils.py` (parser helpers) and the
`__init__.py` re-export hub. These are genuine cross-layer settings, but they live
in a top-level package that is exempt from the R3 layers contract — an exemption the
package-facades spec treats as a temporary outside-layer-set carve-out. Three concrete
defects remain:

1. **`Orchestrator.__init__` takes `config: Config`** (`application/orchestrator.py:93`).
   The aggregate has no domain home yet, so the orchestrator reaches into
   `config.local.keys_dir`, `config.local.{conn_machine,allocate,consume,deallocate}_limit`,
   `config.remote.{data_dir,engines_dir,tasks_dir,jump_host,jump_username}`, and
   `config.clouds` at runtime. Once `Config` moves to `entrypoints`, that access becomes
   an `application → entrypoints` R3 violation unless the orchestrator stops taking the
   aggregate.
2. **`config.config -> entrypoints.config_parser` lazy-import seam**
   (`pyproject.toml:137-139`, tagged `TODO(P4)`). P2 introduced a lazy import inside
   `Config.from_config_parser` to reach the engine parser without a module-level
   `config → entrypoints` edge; the `ignore_imports` entry masks it. The seam exists
   only because the aggregate lives outside `entrypoints` while the parser lives inside
   it. Moving the aggregate into `entrypoints` collapses the seam — the assembly becomes
   intra-package and the `ignore_imports` entry is removed.
3. **`config/db.py`, `config/remote.py` still on attrs**; `config/utils.py`
   (`make_default_field`, `warn_unknown_fields`, `opt_str_val`, `ConfigWarning`) is the
   last attrs consumer set and exists only to serve the parser. With the DTOs migrated
   to stdlib dataclasses and the parser co-located in `entrypoints`, `utils.py` has no
   remaining reason to exist as a separate module.

This is the fourth step (P4) of the config-layer split plan
(`docs/config-layer-split-plan.md`): relocate the remaining settings to their
architectural homes — `LocalSettings`/`RemoteDefaults` to `domain/settings.py`,
`PostgresDbConfig` to `infra/persistence/db_config.py`, the `Config` aggregate and
`parse_config()` to `entrypoints/` — delete `yascheduler/config/` entirely, and collapse
the outside-layer-set exemption. Predecessors P1 and P2 are archived; P3
(`cloud-configs-to-infra-registry`) is the immediate predecessor — P4 assumes P3's
`CLOUD_CONFIG_PARSERS` registry, `CloudConfig` Protocol, and
`infra/cloud/cloud_configs.py` are in place.

## What Changes

- Move `ConfigLocal` → `yascheduler/domain/settings.py::LocalSettings` as
  `@dataclass(frozen=True)`. Field set preserved: `data_dir`, `tasks_dir`,
  `engines_dir`, `keys_dir`, `webhook_url`, `webhook_reqs_limit`,
  `conn_machine_limit`, `conn_machine_pending`, `allocate_limit`,
  `allocate_pending`, `consume_limit`, `consume_pending`, `deallocate_limit`,
  `deallocate_pending`. Drop `get_valid_config_parser_fields` and
  `from_config_parser_section` (move to parser). **BREAKING** for direct
  `from yascheduler.config import ConfigLocal` imports; the canonical path becomes
  `from yascheduler.domain import LocalSettings`.
- Move `ConfigRemote` → `yascheduler/domain/settings.py::RemoteDefaults` as
  `@dataclass(frozen=True)`. Field set preserved: `data_dir`, `tasks_dir`,
  `engines_dir`, `username`, `jump_username`, `jump_host`. Drop
  `get_valid_config_parser_fields` and `from_config_parser_section` (move to parser).
  **BREAKING** for direct `from yascheduler.config import ConfigRemote` imports; the
  canonical path becomes `from yascheduler.domain import RemoteDefaults`.
- Move `ConfigDb` → `yascheduler/infra/persistence/db_config.py::PostgresDbConfig` as
  `@dataclass(frozen=True)`. Field set preserved: `user`, `password`, `database`,
  `host`, `port`. Drop `get_valid_config_parser_fields` and
  `from_config_parser_section` (move to parser). **BREAKING** for direct
  `from yascheduler.config import ConfigDb` imports; the canonical path becomes
  `from yascheduler.infra.persistence import PostgresDbConfig`. `postgres_uow.py` and
  `postgres_schema.py` imports become intra-package.
- Create `yascheduler/entrypoints/config.py::Config` as `@dataclass(frozen=True)` with
  fields `db: PostgresDbConfig`, `local: LocalSettings`, `remote: RemoteDefaults`,
  `clouds: Sequence[CloudConfig]`, `engines: EngineRepository`. This is the
  composition-root aggregate; only `entrypoints` consumes it. **BREAKING** for direct
  `from yascheduler.config import Config` imports; the canonical path becomes
  `from yascheduler.entrypoints import Config`.
- Move `from_config_parser_section` / `get_valid_config_parser_fields` from
  `ConfigLocal`, `ConfigRemote`, `ConfigDb` into `entrypoints/config_parser.py` as free
  functions (`_parse_local_section`, `_parse_remote_section`, `_parse_db_section`,
  `_local_valid_fields`, `_remote_valid_fields`, `_db_valid_fields`). The existing
  `parse_engine_section` / `parse_engines` / `parse_cloud_section` / `parse_clouds`
  (from P2/P3) are joined by a public `parse_config(path) -> Config` orchestrating all
  per-section parsers and the `CLOUD_CONFIG_PARSERS` registry. Validation
  (`validators.ge(1)`, `instance_of`, `opt_str_val`, `default_if_none`) runs in the
  parser, not in dataclass `__post_init__` — value objects stay pure.
- Move `config/utils.py` (`make_default_field`, `warn_unknown_fields`, `opt_str_val`,
  `ConfigWarning`, `config_repr`) into `entrypoints/config_parser.py` (or a sibling
  `entrypoints/_config_utils.py` if the parser module would exceed the GRACE-lite 500-
  line soft limit). These are parser-side helpers; they have no domain meaning.
- `Orchestrator.__init__` (`application/orchestrator.py:91`): **drop the `config:
  Config` parameter**. Replace with `local_settings: LocalSettings` and
  `remote_defaults: RemoteDefaults` (both from `yascheduler.domain`). The
  `list_private_keys_fn` callable introduced in P1 is retained unchanged. The
  `config_clouds` / `active_clouds` parameters are already typed against the
  `CloudConfig` Protocol (P3); no change. `self._config` is removed; the orchestrator
  stores `self._local_settings` and `self._remote_defaults`. All `self._config.local.*`
  reads become `self._local_settings.*`; all `self._config.remote.*` reads become
  `self._remote_defaults.*`; the `self._config.clouds` iteration at the
  `_connect_machine_consumer` cloud-fallback becomes iteration over
  `self._config_clouds` (already a parameter, already iterated elsewhere — the
  duplicate `config.clouds` read is collapsed). The orchestrator never imports
  `yascheduler.entrypoints` (R3-legal: `application → domain` only).
- Update `entrypoints/di.py::make_daemon` to construct `Orchestrator` with the new
  signature: pass `config.local` → `local_settings`, `config.remote` → `remote_defaults`,
  and the existing `list_private_keys_fn` / `config_clouds` / `active_clouds`. The
  composition root owns the `Config` aggregate and unpacks it into the orchestrator.
- Delete `yascheduler/config/` package entirely: `config/__init__.py`,
  `config/config.py`, `config/db.py`, `config/local.py`, `config/remote.py`,
  `config/utils.py`. The `config/cloud.py`, `config/engine.py`,
  `config/engine_repository.py` files are already deleted by P3/P2 respectively; P4
  removes the last six.
- Update `yascheduler/domain/__init__.py` to re-export `LocalSettings`,
  `RemoteDefaults` from `.settings`.
- Update `yascheduler/infra/persistence/__init__.py` to re-export `PostgresDbConfig`
  from `.db_config`.
- Update `yascheduler/entrypoints/__init__.py` to re-export `Config` from `.config`.
- Remove the `yascheduler.config -> yascheduler.entrypoints.config_parser`
  `ignore_imports` entry from `pyproject.toml` (the seam collapses — the parser and the
  aggregate are both in `entrypoints`).
- Remove the `forbidden` contract
  (`Shared kernel has no config imports`, `source_modules = ["yascheduler.shared"]`,
  `forbidden_modules = ["yascheduler.config"]`) from `pyproject.toml`. With
  `yascheduler.config` deleted, the contract is vacuous.
- Migrate tests: every `config.engines = engines`, `config.clouds = ...`,
  `config.local = ...`, `config.remote = ...`, `config.db = ...` mutation site (26 sites
  across 7 files: `test_cli_manage_node.py`, `test_cli_behavioral.py`,
  `test_application_orchestrator.py`, `test_di.py`, `test_cli_submit.py`,
  `test_cli_show_nodes.py`, `test_cli_check_status.py`) migrates to
  `dataclasses.replace(config, engines=engines, ...)` or a small `ConfigBuilder` helper
  in `tests/unit/conftest.py` if the repetition is excessive. The frozen aggregate
  forbids direct attribute assignment.
- Migrate test imports: `from yascheduler.config import Config` →
  `from yascheduler.entrypoints import Config`; `from yascheduler.config.db import
  ConfigDb` → `from yascheduler.infra.persistence import PostgresDbConfig`; `from
  yascheduler.config import ConfigLocal` → `from yascheduler.domain import
  LocalSettings`; `from yascheduler.config import ConfigRemote` →
  `from yascheduler.domain import RemoteDefaults`. Patch targets
  (`patch("yascheduler.config.config.Config.from_config_parser")` etc.) repoint to
  `yascheduler.entrypoints.config_parser.parse_config` or the new module paths.

## Capabilities

### New Capabilities
- `app-settings`: Cross-layer application settings as frozen stdlib dataclasses in
  `yascheduler/domain/settings.py` — `LocalSettings` (13 fields: daemon paths,
  webhook, concurrency limits) and `RemoteDefaults` (6 fields: SSH paths, username,
  jump host). No INI parsing on the DTOs; no attrs dependency; importable from
  `yascheduler.domain`. Consumed by `application` (orchestrator) and `entrypoints`
  (composition root, CLI).
- `db-config`: PostgreSQL connection configuration as a frozen stdlib dataclass
  `PostgresDbConfig` in `yascheduler/infra/persistence/db_config.py` (5 fields: user,
  password, database, host, port). No INI parsing on the DTO; importable from
  `yascheduler.infra.persistence`. Consumed by `postgres_uow.py` and
  `postgres_schema.py` (intra-package).
- `config-aggregate`: The `Config` composition-root aggregate as a frozen stdlib
  dataclass in `yascheduler/entrypoints/config.py` (5 fields: `db`, `local`, `remote`,
  `clouds`, `engines`). Importable from `yascheduler.entrypoints`. Only `entrypoints`
  consumes it; `application` and `infra` never import it.
- `config-parser-assembly`: The `parse_config(path) -> Config` function in
  `entrypoints/config_parser.py` orchestrating per-section parsers
  (`_parse_db_section`, `_parse_local_section`, `_parse_remote_section`,
  `parse_engines`, `parse_clouds`) and producing the frozen `Config` aggregate. The
  parser owns validation, `warn_unknown_fields`, and the `make_default_field`/
  `opt_str_val` helpers (relocated from `config/utils.py`). This is the single seam
  between INI and the domain/infra/entrypoints types.

### Modified Capabilities
- `orchestrator`: `Orchestrator.__init__` drops the `config: Config` parameter and
  accepts `local_settings: LocalSettings`, `remote_defaults: RemoteDefaults` (both from
  `yascheduler.domain`). The `list_private_keys_fn` callable (P1) and
  `config_clouds`/`active_clouds` (`CloudConfig` Protocol, P3) are retained. The
  orchestrator no longer holds an `self._config` reference; it stores
  `self._local_settings` and `self._remote_defaults`. All `self._config.local.*` and
  `self._config.remote.*` reads are repointed. The duplicate `self._config.clouds`
  iteration at `_connect_machine_consumer` is collapsed into `self._config_clouds`.
- `dependency-injection`: `make_daemon` unpacks `config.local` → `local_settings`,
  `config.remote` → `remote_defaults` and passes them to `Orchestrator`. The
  composition root owns the `Config` aggregate; the orchestrator receives unpacked
  domain settings.
- `package-facades`: `yascheduler.config` is removed from the outside-layer-set
  exemption list. The `forbidden` contract (`Shared kernel has no config imports`) is
  removed (vacuous). The `ignore_imports` entry
  (`yascheduler.config.config -> yascheduler.entrypoints.config_parser`) is removed
  (the seam collapses). The `yascheduler.config` facade re-export list is deleted
  entirely. The `yascheduler.domain` facade gains `LocalSettings` / `RemoteDefaults`.
  The `yascheduler.infra.persistence` facade gains `PostgresDbConfig`. The
  `yascheduler.entrypoints` facade gains `Config`.
- `testing-unit`: The config-parsing requirement loses
  `ConfigLocal.from_config_parser_section` / `ConfigRemote.from_config_parser_section`
  / `ConfigDb.from_config_parser_section` direct calls; section round-trip parsing is
  asserted against `parse_config` / the per-section parser functions. The DTOs are
  asserted frozen with no parser methods. The `config.engines = engines` mutation
  pattern in 7 test files migrates to `dataclasses.replace(config, engines=engines)`
  or a `ConfigBuilder` helper.

## Impact

- **Code**: New `yascheduler/domain/settings.py`, new
  `yascheduler/infra/persistence/db_config.py`, new
  `yascheduler/entrypoints/config.py`; deleted `yascheduler/config/` (6 files:
  `__init__.py`, `config.py`, `db.py`, `local.py`, `remote.py`, `utils.py`);
  modified `yascheduler/application/orchestrator.py` (`__init__` signature,
  `self._config.*` reads), `yascheduler/entrypoints/di.py` (unpacking + new import),
  `yascheduler/entrypoints/config_parser.py` (gains `parse_config` + db/local/remote
  parsers + relocated utils), `yascheduler/domain/__init__.py` (re-exports),
  `yascheduler/infra/persistence/__init__.py` (re-exports),
  `yascheduler/entrypoints/__init__.py` (re-exports),
  `yascheduler/infra/persistence/postgres_uow.py` (intra-package import),
  `yascheduler/infra/persistence/postgres_schema.py` (intra-package import),
  `yascheduler/entrypoints/cli/{submit,manage_node,check_status,show_nodes,init,daemonize,daemon_systemd,daemon_sysv,daemon_common}.py`
  (`from yascheduler.config import Config` → `from yascheduler.entrypoints import
  Config`), `yascheduler/entrypoints/client.py` (same).
- **APIs**: Direct `from yascheduler.config import ...` (any symbol) breaks; the
  package no longer exists. Canonical paths:
  - `Config` → `from yascheduler.entrypoints import Config`
  - `ConfigLocal` → `from yascheduler.domain import LocalSettings`
  - `ConfigRemote` → `from yascheduler.domain import RemoteDefaults`
  - `ConfigDb` → `from yascheduler.infra.persistence import PostgresDbConfig`
  - `make_default_field` / `warn_unknown_fields` / `opt_str_val` / `ConfigWarning` →
    `from yascheduler.entrypoints.config_parser import ...` (or a sibling utils module
    within `entrypoints`).
  `ConfigLocal.from_config_parser_section` / `ConfigRemote.from_config_parser_section`
  / `ConfigDb.from_config_parser_section` break; the canonical path is
  `from yascheduler.entrypoints.config_parser import parse_config`. No public API
  surface (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `from yascheduler
  import Yascheduler`, `from yascheduler.client import Yascheduler`) is affected —
  none are re-exported through `yascheduler.config`.
- **Layers contract**: `yascheduler.config` is removed from the outside-layer-set
  exemption list in the `package-facades` spec. The `forbidden` contract is removed
  (vacuous — `yascheduler.config` no longer exists). The `ignore_imports` entry
  (`yascheduler.config.config -> yascheduler.entrypoints.config_parser`) is removed
  (the seam collapses). After P4, the only `ignore_imports` entries remaining are the
  two `application.{consume_task,orchestrator} -> yascheduler.infra` residuals tracked
  separately for the `gateway-sftp-wrapping` follow-up.
- **Dependencies**: `attrs` usage in `config/db.py`, `config/remote.py`,
  `config/utils.py` removed (the files are deleted or their contents migrated to
  stdlib dataclasses). After P4, the only remaining attrs users are in `infra/cloud/`
  (`manager.py`, `providers/az.py`) — P5 removes those and drops `attrs` from
  `pyproject.toml`.
- **Specs**: New `app-settings`, `db-config`, `config-aggregate`,
  `config-parser-assembly` capability specs. Delta specs for `orchestrator`,
  `dependency-injection`, `package-facades`, `testing-unit`.
- **Tests**: 7 test files with 26 `config.<field> = ...` mutation sites migrate to
  `dataclasses.replace(config, ...)` or a `ConfigBuilder` helper. Import-path
  migrations across ~15 test files. `patch("yascheduler.config.config.Config...")`
  targets repoint to `yascheduler.entrypoints.config.Config` or
  `yascheduler.entrypoints.config_parser.parse_config`.
- **Knowledge graph**: Remove `M-CONFIG`, `M-CONFIG-DB`, `M-CONFIG-LOCAL`,
  `M-CONFIG-REMOTE`, `M-CONFIG-UTILS`, `M-CONFIG-HUB` (the `__init__.py` hub). Add
  `M-DOMAIN-SETTINGS` (`LocalSettings`, `RemoteDefaults`), `M-INFRA-DB-CONFIG`
  (`PostgresDbConfig`), `M-ENTRYPOINTS-CONFIG` (`Config` aggregate),
  `M-ENTRYPOINTS-CONFIG-PARSER` gains `parse_config` + db/local/remote parser function
  annotations + the relocated utils annotations. CrossLinks from `M-APPLICATION-ORCHESTRATOR`,
  `M-ENTRYPOINTS-DI`, `M-ENTRYPOINTS-CLI-*`, `M-PERSISTENCE-*` that targeted `M-CONFIG*`
  repoint to `M-DOMAIN-SETTINGS` / `M-INFRA-DB-CONFIG` / `M-ENTRYPOINTS-CONFIG`.