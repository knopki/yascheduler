## 1. Domain settings module

- [x] 1.1 Create `yascheduler/domain/settings.py` with `LocalSettings` as `@dataclass(frozen=True)`: fields `data_dir: Path`, `tasks_dir: Path`, `engines_dir: Path`, `keys_dir: Path`, `webhook_url: str | None`, `webhook_reqs_limit: int`, `conn_machine_limit: int`, `conn_machine_pending: int`, `allocate_limit: int`, `allocate_pending: int`, `consume_limit: int`, `consume_pending: int`, `deallocate_limit: int`, `deallocate_pending: int`. Defaults match `config/local.py`. Add `__post_init__` validators mirroring P1's `ConfigLocal` (ge(1) for limits, ge(0) for webhook_reqs_limit).
- [x] 1.2 Add `RemoteDefaults` to `yascheduler/domain/settings.py` as `@dataclass(frozen=True)`: fields `data_dir: PurePath`, `tasks_dir: PurePath`, `engines_dir: PurePath`, `username: str`, `jump_username: str | None`, `jump_host: str | None`. Defaults match `config/remote.py`.
- [x] 1.3 Add MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY to `domain/settings.py` (DEPENDS: none; LINKS: M-DOMAIN-PORTS, M-APPLICATION-ORCHESTRATOR).
- [x] 1.4 Re-export `LocalSettings`, `RemoteDefaults` from `yascheduler/domain/__init__.py`.

## 2. PostgresDbConfig module

- [x] 2.1 Create `yascheduler/infra/persistence/db_config.py` with `PostgresDbConfig` as `@dataclass(frozen=True)`: fields `user: str`, `password: str`, `database: str`, `host: str`, `port: int`. Defaults match `config/db.py`. Add `__post_init__` validator (ge(1) for port).
- [x] 2.2 Add MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY (DEPENDS: none; LINKS: M-PERSISTENCE-UOW, M-PERSISTENCE-SCHEMA).
- [x] 2.3 Re-export `PostgresDbConfig` from `yascheduler/infra/persistence/__init__.py`.

## 3. Parser extension

- [x] 3.1 Relocate `make_default_field`, `warn_unknown_fields`, `opt_str_val`, `ConfigWarning`, `config_repr` from `config/utils.py` into `entrypoints/config_parser.py` (or sibling `entrypoints/_config_utils.py` if parser exceeds 500 lines). Migrate to stdlib: `make_default_field` becomes a default-with-validation helper; `opt_str_val` becomes a parser-side `Optional[str]` coercion; drop attrs imports.
- [x] 3.2 Add `_parse_db_section(sec: SectionProxy) -> PostgresDbConfig` to `entrypoints/config_parser.py` (relocate `ConfigDb.from_config_parser_section` logic; validation parser-side).
- [x] 3.3 Add `_db_valid_fields() -> Sequence[str]` (relocate `ConfigDb.get_valid_config_parser_fields`).
- [x] 3.4 Add `_parse_local_section(sec: SectionProxy) -> LocalSettings` (relocate `ConfigLocal.from_config_parser_section` logic).
- [x] 3.5 Add `_local_valid_fields() -> Sequence[str]`.
- [x] 3.6 Add `_parse_remote_section(sec: SectionProxy) -> RemoteDefaults` (relocate `ConfigRemote.from_config_parser_section` logic; includes `username` inheritance from `RemoteDefaults`).
- [x] 3.7 Add `_remote_valid_fields() -> Sequence[str]`.
- [x] 3.8 Add public `parse_config(path: str | bytes | PurePath) -> Config` orchestrating: read INI, `_parse_db_section`, `_parse_local_section`, `_parse_remote_section`, `parse_engines`, `parse_clouds` (via `CLOUD_CONFIG_PARSERS` registry from P3), assemble frozen `Config`.

## 4. Config aggregate module

- [x] 4.1 Create `yascheduler/entrypoints/config.py` with `Config` as `@dataclass(frozen=True)`: fields `db: PostgresDbConfig`, `local: LocalSettings`, `remote: RemoteDefaults`, `clouds: Sequence[CloudConfig]`, `engines: EngineRepository`.
- [x] 4.2 Add MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY (DEPENDS: M-DOMAIN-SETTINGS, M-INFRA-DB-CONFIG, M-CLOUD-CONFIGS, M-DOMAIN-ENGINE; LINKS: M-ENTRYPOINTS-DI, M-ENTRYPOINTS-CONFIG-PARSER).
- [x] 4.3 Re-export `Config` from `yascheduler/entrypoints/__init__.py`.

## 5. Orchestrator signature change

- [x] 5.1 In `application/orchestrator.py`, drop `config: Config` from `Orchestrator.__init__`; add `local_settings: LocalSettings`, `remote_defaults: RemoteDefaults`. Update TYPE_CHECKING imports: drop `Config`, `ConfigCloud` from `yascheduler.config`; add `LocalSettings`, `RemoteDefaults` from `yascheduler.domain` (retain `CloudConfig` from P3, `EngineRepository` from P2).
- [x] 5.2 Replace `self._config = config` with `self._local_settings = local_settings` and `self._remote_defaults = remote_defaults`.
- [x] 5.3 Repoint `self._config.local.keys_dir` → `self._local_settings.keys_dir` (`_connect_machine_consumer`).
- [x] 5.4 Repoint `self._config.local.{conn_machine,allocate,consume,deallocate}_limit` → `self._local_settings.*` (worker spawn sites).
- [x] 5.5 Repoint `self._config.local.{conn_machine,allocate,consume,deallocate}_pending` → `self._local_settings.*` (queue maxsize sites in `__init__`).
- [x] 5.6 Repoint `self._config.remote.{data_dir,engines_dir,tasks_dir}` → `self._remote_defaults.*`.
- [x] 5.7 Repoint `self._config.remote.{jump_host,jump_username}` → `self._remote_defaults.*`.
- [x] 5.8 Collapse `self._config.clouds` iteration at `_connect_machine_consumer` → `self._config_clouds` (already a parameter).
- [x] 5.9 Update `Orchestrator.__init__` CONTRACT block and the MODULE_CONTRACT DEPENDS/LINKS.

## 6. Composition root update

- [x] 6.1 In `entrypoints/di.py`, import `Config` from `yascheduler.entrypoints.config` (not `yascheduler.config`); drop `from yascheduler.config import Config, ConfigCloud` (TYPE_CHECKING).
- [x] 6.2 In `make_daemon`, construct `Orchestrator` with `local_settings=config.local`, `remote_defaults=config.remote` (unpack the aggregate); retain `list_private_keys_fn`, `config_clouds`, `active_clouds`, `engines`, `local_tasks_dir`.

## 7. Persistence imports

- [x] 7.1 In `infra/persistence/postgres_uow.py`, change `from yascheduler.config import ConfigDb` (TYPE_CHECKING) → `from .db_config import PostgresDbConfig` (intra-package); rename type annotations `ConfigDb` → `PostgresDbConfig`.
- [x] 7.2 In `infra/persistence/postgres_schema.py`, change `from yascheduler.config import ConfigDb` (runtime) → `from .db_config import PostgresDbConfig` (intra-package); rename annotations and the `apply_schema(config: ConfigDb)` signature.

## 8. Cloud manager and application TYPE_CHECKING imports

- [x] 8.1 In `infra/cloud/manager.py`, change TYPE_CHECKING import `from yascheduler.config import ConfigLocal, ConfigRemote` → `from yascheduler.domain import LocalSettings, RemoteDefaults`; update `CloudProvisionerImpl` field annotations `local_config: ConfigLocal` → `local_config: LocalSettings` and `remote_config: ConfigRemote` → `remote_config: RemoteDefaults`.
- [x] 8.2 In `application/deallocate_nodes.py`, change TYPE_CHECKING import `from yascheduler.config import ConfigCloud` → `from yascheduler.domain import CloudConfig`; update `config_clouds: Sequence[ConfigCloud]` → `config_clouds: Sequence[CloudConfig]` annotation.

## 9. Entrypoints CLI imports

- [x] 9.1 In `entrypoints/cli/submit.py`, `entrypoints/cli/manage_node.py`, `entrypoints/cli/check_status.py`, `entrypoints/cli/show_nodes.py`, `entrypoints/cli/init.py`, `entrypoints/cli/daemonize.py`, `entrypoints/cli/daemon_systemd.py`, `entrypoints/cli/daemon_sysv.py`, `entrypoints/cli/daemon_common.py`, `entrypoints/client.py`: change `from yascheduler.config import Config` → `from yascheduler.entrypoints import Config`.

## 10. Delete yascheduler/config/

- [x] 10.1 Delete `yascheduler/config/__init__.py`, `config/config.py`, `config/db.py`, `config/local.py`, `config/remote.py`, `config/utils.py`. Remove the `config/` directory.

## 11. Layers contract cleanup

- [x] 11.1 In `pyproject.toml`, remove the `ignore_imports` entry `yascheduler.config.config -> yascheduler.entrypoints.config_parser` (and the `TODO(P4)` comment).
- [x] 11.2 In `pyproject.toml`, remove the `forbidden` contract (`Shared kernel has no config imports`, `source_modules = ["yascheduler.shared"]`, `forbidden_modules = ["yascheduler.config"]`).

## 12. Knowledge graph

- [x] 12.1 In `docs/knowledge-graph.xml`, remove `M-CONFIG`, `M-CONFIG-DB`, `M-CONFIG-LOCAL`, `M-CONFIG-REMOTE`, `M-CONFIG-UTILS`, `M-CONFIG-HUB`.
- [x] 12.2 Add `M-DOMAIN-SETTINGS` (TYPE=CORE_LOGIC, STATUS=implemented) with `class-LocalSettings`, `class-RemoteDefaults` annotations.
- [x] 12.3 Add `M-INFRA-DB-CONFIG` (TYPE=DATA_LAYER, STATUS=implemented) with `class-PostgresDbConfig` annotation.
- [x] 12.4 Add `M-ENTRYPOINTS-CONFIG` (TYPE=ENTRY_POINT, STATUS=implemented) with `class-Config` annotation.
- [x] 12.5 Update `M-ENTRYPOINTS-CONFIG-PARSER` annotations: add `fn-parse_config`, `fn-_parse_db_section`, `fn-_parse_local_section`, `fn-_parse_remote_section`.
- [x] 12.6 Repoint CrossLinks from `M-APPLICATION-ORCHESTRATOR`, `M-ENTRYPOINTS-DI`, `M-ENTRYPOINTS-CLI-*`, `M-PERSISTENCE-*` that targeted `M-CONFIG*` → `M-DOMAIN-SETTINGS` / `M-INFRA-DB-CONFIG` / `M-ENTRYPOINTS-CONFIG`.

## 13. Test migration

- [x] 13.1 In `tests/unit/conftest.py`, add a `ConfigBuilder` helper if `test_di.py` or `test_application_orchestrator.py` would otherwise have ≥4 `replace` calls; otherwise rely on `dataclasses.replace`.
- [x] 13.2 Migrate `tests/unit/test_cli_manage_node.py`: `config.engines = engines` etc. → `replace(config, engines=engines, ...)`; update `from yascheduler.config import ...` → new paths.
- [x] 13.3 Migrate `tests/unit/test_cli_behavioral.py` (6 sites).
- [x] 13.4 Migrate `tests/unit/test_application_orchestrator.py` (4 sites; update `Orchestrator(...)` constructor call with new signature).
- [x] 13.5 Migrate `tests/unit/test_di.py` (6 sites; update `make_daemon` / `Orchestrator` wiring).
- [x] 13.6 Migrate `tests/unit/test_cli_submit.py` (5 sites).
- [x] 13.7 Migrate `tests/unit/test_cli_show_nodes.py` (4 sites).
- [x] 13.8 Migrate `tests/unit/test_cli_check_status.py` (5 sites).
- [x] 13.9 Update `tests/unit/test_config.py`: `from yascheduler.config.*` imports → new paths; `ConfigLocal.from_config_parser_section` / `ConfigRemote.from_config_parser_section` / `ConfigDb.from_config_parser_section` direct calls → `parse_config` / per-section parser functions; assert DTOs frozen + no parser methods.
- [x] 13.10 Grep for `patch("yascheduler.config` across `tests/` and repoint each to the new module path (`yascheduler.entrypoints.config.Config`, `yascheduler.entrypoints.config_parser.parse_config`, etc.).
- [x] 13.11 Update `tests/unit/test_di.py` `MagicMock(spec=ConfigDb)` → `MagicMock(spec=PostgresDbConfig)` (audit `postgres_uow.py` / `postgres_schema.py` test mocks similarly).
- [x] 13.12 Update integration/e2e conftest imports: `from yascheduler.config.db import ConfigDb` → `from yascheduler.infra.persistence import PostgresDbConfig`; `from yascheduler.config import Config` → `from yascheduler.entrypoints import Config`.

## 14. OpenSpec spec deltas

- [x] 14.1 `package-facades` delta: MODIFIED `Outside-layer-set exemptions` — remove `yascheduler.config` bullet; REMOVED `Shared kernel config-import prohibition`. (The `ignore_imports` seam removal and the `forbidden` contract removal are `pyproject.toml` edits, not spec-heading changes — the `Layers contract configuration` and `Documented residual edges` requirements in the spec describe the `ignore_imports` for the `gateway-sftp-wrapping` residuals, which are untouched by P4; they do not mention the `yascheduler.config.config -> config_parser` seam, so no MODIFIED heading is needed for them.)
- [x] 14.2 `package-facades` delta: MODIFIED facade re-export lists — `yascheduler.config` facade deleted; `yascheduler.domain` facade gains `LocalSettings` / `RemoteDefaults`; `yascheduler.infra.persistence` facade gains `PostgresDbConfig`; `yascheduler.entrypoints` facade gains `Config`.
- [x] 14.3 `orchestrator` delta: MODIFIED `Orchestrator manages producer-consumer loops` — new `__init__` signature (drop `config`, add `local_settings` / `remote_defaults`); add scenario for unpacked-settings construction.
- [x] 14.4 `dependency-injection` delta: MODIFIED `make_daemon factory` — unpacks `config.local` / `config.remote` into orchestrator; add scenario.
- [x] 14.5 `testing-unit` delta: MODIFIED `Config parsing and validation` — remove `ConfigLocal` / `ConfigRemote` / `ConfigDb` `from_config_parser_section` direct calls; assert `parse_config` / per-section parsers; assert DTOs frozen + no parser methods; add scenario for `dataclasses.replace` mutation pattern.
- [x] 14.6 Create new capability spec `app-settings/spec.md` (ADDED Requirements: `LocalSettings` fields + defaults + frozen; `RemoteDefaults` fields + defaults + frozen).
- [x] 14.7 Create new capability spec `db-config/spec.md` (ADDED Requirements: `PostgresDbConfig` fields + defaults + frozen).
- [x] 14.8 Create new capability spec `config-aggregate/spec.md` (ADDED Requirements: `Config` fields + frozen + importable from `yascheduler.entrypoints`).
- [x] 14.9 Create new capability spec `config-parser-assembly/spec.md` (ADDED Requirements: `parse_config(path) -> Config`; per-section parser functions; relocated utils).

## 15. GRACE-lite markup

- [x] 15.1 Add START_CONTRACT blocks for `LocalSettings.__post_init__`, `RemoteDefaults.__post_init__`, `PostgresDbConfig.__post_init__` if validators are non-trivial.
- [x] 15.2 Add START_CONTRACT for `parse_config` (PURPOSE, INPUTS, OUTPUTS, SIDE_EFFECTS, LINKS).
- [x] 15.3 Update CHANGE_SUMMARY in `application/orchestrator.py` (LAST_CHANGE: drop `config: Config`, add `local_settings` / `remote_defaults`).
- [x] 15.4 Update CHANGE_SUMMARY in `entrypoints/config_parser.py` (LAST_CHANGE: gain `parse_config` + db/local/remote parsers + relocated utils).
- [x] 15.5 Update CHANGE_SUMMARY in `entrypoints/di.py` (LAST_CHANGE: import `Config` from `entrypoints.config`, unpack into orchestrator).

## 16. Verification

- [x] 16.1 Run `uv run pytest -m unit` — all pass.
- [x] 16.2 Run `uv run pytest -m integration` — all pass.
- [x] 16.3 Run `uv run pytest -m e2e` — all pass (or skip if no testcontainers env).
- [x] 16.4 Run `uv run ruff check .` — clean.
- [x] 16.5 Run `uv run ruff format --check .` — clean.
- [x] 16.6 Run `uv run lint-imports` — no violations; verify the `forbidden` contract is gone and the `ignore_imports` seam is gone.
- [x] 16.7 Run `python3 scripts/grace_check.py` — exit 0.
- [x] 16.8 Run `openspec validate --all --json` — pass.
- [x] 16.9 Grep `from yascheduler.config` across `yascheduler/` and `tests/` — zero matches (package deleted).
- [x] 16.10 Grep `import yascheduler.config` across `yascheduler/` and `tests/` — zero matches.
- [x] 16.11 Verify `python -c "import yascheduler.config"` raises `ModuleNotFoundError`.
- [x] 16.12 Grep `attrs` in `yascheduler/config/` — zero matches (directory deleted); grep `from attrs` in `yascheduler/` — only `infra/cloud/{manager,providers/az}.py` remain (P5 scope).