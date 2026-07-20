"""INI config parsing — adapter between ConfigParser and domain/infra types."""
# region MODULE_CONTRACT
# PURPOSE: Adapt `ConfigParser` to the application's frozen typed-configuration model so the rest of the system consumes validated value objects and never touches raw INI proxies.
# SCOPE: INI config parsing — engine sections, cloud provider sections, DB config, local/remote settings, and the top-level parse_config assembly.
# KEYWORDS: config, ini, parser, engine, cloud, database, settings
# endregion MODULE_CONTRACT

from __future__ import annotations

import dataclasses
from configparser import ConfigParser
from functools import partial
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from yascheduler.domain.engine import (
    Deploy,
    Engine,
    EngineRepository,
    LocalArchiveDeploy,
    LocalFilesDeploy,
    RemoteArchiveDeploy,
)
from yascheduler.domain.settings import LocalSettings, RemoteDefaults, _int_or_default
from yascheduler.entrypoints.config import Config
from yascheduler.infra.cloud.cloud_configs import (
    AzureImageReference,
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
)
from yascheduler.infra.persistence import PostgresDbConfig

from ._config_utils import warn_unknown_fields

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from configparser import SectionProxy

    from yascheduler.infra.cloud.cloud_configs import ConfigCloud


def _check_spawn(engine: Engine, value: str) -> None:
    try:
        value.format(task_path="", engine_path="", ncpus="")
    except KeyError as err:
        msg = "Engine {name} has unknown template placeholder `{placeholder}` in *spawn* command"
        raise ValueError(msg.format(name=engine.name, placeholder=err.args[0])) from err


def _check_check_(engine: Engine) -> None:
    if not engine.check_cmd and not engine.check_pname:
        msg = f"Engine {engine.name} has no *check_cmd* or *check_pname* set"
        raise ValueError(msg)


def _check_at_least_one_elem(
    engine: Engine,
    field_name: str,
    value: Sequence[object] | None,
) -> None:
    if not value or len(value) < 1:
        msg = f"Engine {engine.name} has no *{field_name}* config set"
        raise ValueError(msg)


def _check_port(name: str, value: int) -> int:
    min_port = 1
    max_port = 65535
    if value < min_port or value > max_port:
        msg = f"{name} must be between {min_port} and {max_port}, got {value}"
        raise ValueError(msg)
    return value


# region FUNC_engine_valid_fields
# PURPOSE: Return valid INI keys for an [engine.*] section (dataclass fields + deploy aliases, excluding name and deployable).
def engine_valid_fields() -> Sequence[str]:
    """Return valid INI keys for an [engine.*] section."""
    exclude_names = ["name", "deployable"]
    include_names = [
        "deploy_local_files",
        "deploy_local_archive",
        "deploy_remote_archive",
    ]
    return [
        f.name for f in dataclasses.fields(Engine) if f.name not in exclude_names
    ] + include_names


# endregion FUNC_engine_valid_fields


# region FUNC_parse_engine_section
# PURPOSE: Build a frozen Engine from a single [engine.*] INI section, validating spawn placeholders, check methods, and required file lists.
def parse_engine_section(sec: SectionProxy, engines_dir: PurePath) -> Engine:
    """Build a frozen Engine from a single [engine.*] section."""
    warn_unknown_fields(engine_valid_fields(), sec)

    def gettuple(key: str) -> tuple[str, ...]:
        return tuple(x.strip() for x in filter(None, sec.get(key, fallback="").split()))

    name = sec.name[7:]
    engine_dir = engines_dir / name

    deployable: list[Deploy] = []
    deploy_local_files = [
        engine_dir / x.strip() for x in gettuple("deploy_local_files")
    ]
    if deploy_local_files:
        deployable.append(LocalFilesDeploy(files=tuple(deploy_local_files)))
    deploy_local_archive = sec.get("deploy_local_archive", None)
    if deploy_local_archive:
        deployable.append(LocalArchiveDeploy(file=engine_dir / deploy_local_archive))
    deploy_remote_archive = sec.get("deploy_remote_archive", None)
    if deploy_remote_archive:
        deployable.append(RemoteArchiveDeploy(url=deploy_remote_archive))

    spawn = sec.get("spawn")
    if spawn is None:
        msg = f"Engine {name} has no spawn command"
        raise ValueError(msg)
    input_files = gettuple("input_files")
    output_files = gettuple("output_files")

    engine = Engine(
        name=name,
        spawn=spawn,
        check_cmd=sec.get("check_cmd"),
        check_cmd_code=sec.getint("check_cmd_code", fallback=0),
        check_pname=sec.get("check_pname"),
        deployable=tuple(deployable),
        input_files=input_files,
        output_files=output_files,
        sleep_interval=sec.getint("sleep_interval", fallback=10),
        platforms=gettuple("platforms"),
        platform_packages=gettuple("platform_packages"),
    )

    # region BLOCK_validate_engine
    _check_spawn(engine, engine.spawn)
    _check_check_(engine)
    _check_at_least_one_elem(engine, "input_files", engine.input_files)
    _check_at_least_one_elem(engine, "output_files", engine.output_files)
    # endregion BLOCK_validate_engine
    return engine


# endregion FUNC_parse_engine_section


# region FUNC_parse_engines
# PURPOSE: Parse all engine.* sections from an INI config into an EngineRepository.
def parse_engines(cfg: ConfigParser, engines_dir: PurePath) -> EngineRepository:
    """Parse all engine.* sections from an INI config into an EngineRepository."""
    snames = filter(lambda x: x.startswith("engine."), cfg.sections())
    data: dict[str, Engine] = {}
    for sname in snames:
        engine = parse_engine_section(cfg[sname], engines_dir)
        data[engine.name] = engine
    return EngineRepository(data=data)


# endregion FUNC_parse_engines

# ============================================================================
# Cloud config parsers
# ============================================================================


def _check_az_user(username: str) -> None:
    if username == "root":
        msg = "Root user is forbidden on Azure"
        raise ValueError(msg)


def _fmt_key(prefix: str, name: str) -> str:
    return f"{prefix}_{name}"


# Per-prefix valid-field tables.
_AZ_EXCLUDES = {"prefix", "username", "jump_username", "vm_image", "vm_size"}
_AZ_INCLUDES = ["user", "jump_user", "image", "size"]
_HETZNER_EXCLUDES = {"prefix", "username", "jump_username"}
_HETZNER_INCLUDES = ["user", "jump_user"]
_UPCLOUD_EXCLUDES = {"prefix", "username", "jump_username"}
_UPCLOUD_INCLUDES = ["user", "jump_user"]
_VASTAI_EXCLUDES = {"prefix", "username", "jump_username", "env"}
_VASTAI_INCLUDES = ["user", "jump_user"]


# region FUNC_cloud_valid_fields
# PURPOSE: Return valid INI keys for a [clouds] sub-section keyed by a cloud provider prefix.
def cloud_valid_fields(prefix: str) -> Sequence[str]:
    """Return valid INI keys for a [clouds] sub-section keyed by a cloud provider prefix."""
    exclude_names, include_names = _CLOUD_FIELD_RULES[prefix]
    dto_cls = _CLOUD_DTO_BY_PREFIX[prefix]
    return [
        f"{prefix}_{name}"
        for name in (
            [f.name for f in dataclasses.fields(dto_cls) if f.name not in exclude_names]
            + include_names
        )
    ]


# endregion FUNC_cloud_valid_fields


# region FUNC__parse_azure_section
# PURPOSE: Build ConfigCloudAzure from a [clouds] INI section.
def _parse_azure_section(sec: SectionProxy) -> ConfigCloudAzure:
    prefix = "az"
    fmt = partial(_fmt_key, prefix)

    warn_unknown_fields(_ALL_CLOUD_VALID_FIELDS, sec)

    vm_image_urn = sec.get(fmt("image"))
    image_ref = AzureImageReference.from_urn(vm_image_urn) if vm_image_urn else None

    username = sec.get(fmt("user"), "yascheduler")
    _check_az_user(username)

    max_nodes = sec.getint(fmt("max_nodes"), fallback=10)
    if max_nodes < 0:
        msg = f"az max_nodes must be >= 0, got {max_nodes}"
        raise ValueError(msg)
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=300)
    if idle_tolerance < 1:
        msg = f"az idle_tolerance must be >= 1, got {idle_tolerance}"
        raise ValueError(msg)

    jump_port = _check_port("az jump_port", sec.getint(fmt("jump_port"), fallback=22))

    return ConfigCloudAzure(
        tenant_id=sec.get(fmt("tenant_id"), ""),
        client_id=sec.get(fmt("client_id"), ""),
        client_secret=sec.get(fmt("client_secret"), ""),
        subscription_id=sec.get(fmt("subscription_id"), ""),
        resource_group=sec.get(fmt("resource_group"), "yascheduler-rg"),
        location=sec.get(fmt("location"), "westeurope"),
        vnet=sec.get(fmt("vnet"), "yascheduler-vnet"),
        subnet=sec.get(fmt("subnet"), "yascheduler-subnet"),
        nsg=sec.get(fmt("nsg"), "yascheduler-nsg"),
        vm_image=image_ref or AzureImageReference(),
        vm_size=sec.get(fmt("size"), "Standard_B1s"),
        max_nodes=max_nodes,
        username=username,
        priority=sec.getint(fmt("priority"), fallback=0),
        idle_tolerance=idle_tolerance,
        package_upgrade=sec.getboolean(fmt("package_upgrade"), fallback=True),
        jump_username=sec.get(fmt("jump_user"), None),
        jump_host=sec.get(fmt("jump_host"), None),
        jump_port=jump_port,
    )


# endregion FUNC__parse_azure_section


# region FUNC__parse_hetzner_section
# PURPOSE: Build ConfigCloudHetzner from a [clouds] INI section.
def _parse_hetzner_section(sec: SectionProxy) -> ConfigCloudHetzner:
    prefix = "hetzner"
    fmt = partial(_fmt_key, prefix)

    warn_unknown_fields(_ALL_CLOUD_VALID_FIELDS, sec)

    max_nodes = sec.getint(fmt("max_nodes"), fallback=10)
    if max_nodes < 0:
        msg = f"hetzner max_nodes must be >= 0, got {max_nodes}"
        raise ValueError(msg)
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=120)
    if idle_tolerance < 1:
        msg = f"hetzner idle_tolerance must be >= 1, got {idle_tolerance}"
        raise ValueError(msg)

    jump_port = _check_port(
        "hetzner jump_port",
        sec.getint(fmt("jump_port"), fallback=22),
    )

    return ConfigCloudHetzner(
        token=sec.get(fmt("token"), ""),
        max_nodes=max_nodes,
        username=sec.get(fmt("user"), "root"),
        priority=sec.getint(fmt("priority"), fallback=0),
        server_type=sec.get(fmt("server_type"), "cx52"),
        location=sec.get(fmt("location"), None),
        image_name=sec.get(fmt("image_name"), "debian-13"),
        idle_tolerance=idle_tolerance,
        package_upgrade=sec.getboolean(fmt("package_upgrade"), fallback=True),
        jump_username=sec.get(fmt("jump_user"), None),
        jump_host=sec.get(fmt("jump_host"), None),
        jump_port=jump_port,
    )


# endregion FUNC__parse_hetzner_section


# region FUNC__parse_upcloud_section
# PURPOSE: Build ConfigCloudUpcloud from a [clouds] INI section.
def _parse_upcloud_section(sec: SectionProxy) -> ConfigCloudUpcloud:
    prefix = "upcloud"
    fmt = partial(_fmt_key, prefix)

    warn_unknown_fields(_ALL_CLOUD_VALID_FIELDS, sec)

    max_nodes = sec.getint(fmt("max_nodes"), fallback=10)
    if max_nodes < 0:
        msg = f"upcloud max_nodes must be >= 0, got {max_nodes}"
        raise ValueError(msg)
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=120)
    if idle_tolerance < 1:
        msg = f"upcloud idle_tolerance must be >= 1, got {idle_tolerance}"
        raise ValueError(msg)

    jump_port = _check_port(
        "upcloud jump_port",
        sec.getint(fmt("jump_port"), fallback=22),
    )

    return ConfigCloudUpcloud(
        login=sec.get(fmt("login"), ""),
        password=sec.get(fmt("password"), ""),
        max_nodes=max_nodes,
        username=sec.get(fmt("user"), "root"),
        priority=sec.getint(fmt("priority"), fallback=0),
        idle_tolerance=idle_tolerance,
        package_upgrade=sec.getboolean(fmt("package_upgrade"), fallback=True),
        jump_username=sec.get(fmt("jump_user"), None),
        jump_host=sec.get(fmt("jump_host"), None),
        jump_port=jump_port,
    )


# endregion FUNC__parse_upcloud_section


# region FUNC__parse_vastai_section
# PURPOSE: Build ConfigCloudVastAI from a [clouds] INI section.
def _parse_vastai_section(sec: SectionProxy) -> ConfigCloudVastAI:
    prefix = "vastai"
    fmt = partial(_fmt_key, prefix)

    warn_unknown_fields(_ALL_CLOUD_VALID_FIELDS, sec)
    kibi = 1024

    disk_gb = sec.getint(fmt("disk_gb"), fallback=80)
    if disk_gb < 1:
        msg = f"vastai disk_gb must be >= 1, got {disk_gb}"
        raise ValueError(msg)
    min_vram_mb = sec.getint(fmt("min_vram_mb"), fallback=80 * kibi)
    if min_vram_mb < kibi:
        msg = f"vastai min_vram_mb must be >= 1024, got {min_vram_mb}"
        raise ValueError(msg)
    num_gpus = sec.getint(fmt("num_gpus"), fallback=1)
    if num_gpus < 1:
        msg = f"vastai num_gpus must be >= 1, got {num_gpus}"
        raise ValueError(msg)
    max_price_per_hr = sec.getfloat(fmt("max_price_per_hr"), fallback=1.50)
    if max_price_per_hr < 0:
        msg = f"vastai max_price_per_hr must be >= 0, got {max_price_per_hr}"
        raise ValueError(
            msg,
        )
    max_nodes = sec.getint(fmt("max_nodes"), fallback=10)
    if max_nodes < 0:
        msg = f"vastai max_nodes must be >= 0, got {max_nodes}"
        raise ValueError(msg)
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=300)
    if idle_tolerance < 1:
        msg = f"vastai idle_tolerance must be >= 1, got {idle_tolerance}"
        raise ValueError(msg)

    jump_port = _check_port(
        "vastai jump_port",
        sec.getint(fmt("jump_port"), fallback=22),
    )

    return ConfigCloudVastAI(
        api_key=sec.get(fmt("api_key"), ""),
        image=sec.get(fmt("image"), "pytorch/pytorch:2.2.2-cuda12.1-cudnn8-devel"),
        disk_gb=disk_gb,
        min_vram_mb=min_vram_mb,
        num_gpus=num_gpus,
        max_price_per_hr=max_price_per_hr,
        max_nodes=max_nodes,
        username=sec.get(fmt("user"), "root"),
        priority=sec.getint(fmt("priority"), fallback=0),
        idle_tolerance=idle_tolerance,
        package_upgrade=sec.getboolean(fmt("package_upgrade"), fallback=True),
        onstart_script=sec.get(fmt("onstart_script"), ""),
        docker_options=sec.get(fmt("docker_options"), ""),
        env={},
        jump_username=sec.get(fmt("jump_user"), None),
        jump_host=sec.get(fmt("jump_host"), None),
        jump_port=jump_port,
    )


# endregion FUNC__parse_vastai_section


# Open/closed registry: adding a provider = one parser function + one entry here.
CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], ConfigCloud]] = {
    "az": _parse_azure_section,
    "hetzner": _parse_hetzner_section,
    "upcloud": _parse_upcloud_section,
    "vastai": _parse_vastai_section,
}

_CLOUD_DTO_BY_PREFIX: dict[str, type] = {
    "az": ConfigCloudAzure,
    "hetzner": ConfigCloudHetzner,
    "upcloud": ConfigCloudUpcloud,
    "vastai": ConfigCloudVastAI,
}
_CLOUD_FIELD_RULES: dict[str, tuple[set[str], list[str]]] = {
    "az": (_AZ_EXCLUDES, _AZ_INCLUDES),
    "hetzner": (_HETZNER_EXCLUDES, _HETZNER_INCLUDES),
    "upcloud": (_UPCLOUD_EXCLUDES, _UPCLOUD_INCLUDES),
    "vastai": (_VASTAI_EXCLUDES, _VASTAI_INCLUDES),
}

_ALL_CLOUD_VALID_FIELDS: list[str] = [
    *cloud_valid_fields("az"),
    *cloud_valid_fields("hetzner"),
    *cloud_valid_fields("upcloud"),
    *cloud_valid_fields("vastai"),
]


# region FUNC_parse_cloud_section
# PURPOSE: Dispatch a [clouds] sub-section to its per-prefix parser via the registry.
def parse_cloud_section(sec: SectionProxy, prefix: str) -> ConfigCloud:
    """Dispatch a [clouds] sub-section to its per-prefix parser via the registry."""
    return CLOUD_CONFIG_PARSERS[prefix](sec)


# endregion FUNC_parse_cloud_section


# region FUNC_parse_clouds
# PURPOSE: Build the list of ConfigCloud DTOs from a [clouds] section, inheriting remote.username for missing prefix users.
# RATIONALE:
# - Q: Why derive prefixes from [clouds] option names instead of an explicit list?
#   A: So adding a provider is one parser + one registry entry, with no separate prefix-list key to forget.
def parse_clouds(cfg: ConfigParser, remote: RemoteDefaults) -> list[ConfigCloud]:
    """Build the list of ConfigCloud DTOs from a [clouds] section, inheriting remote.username for missing prefix users."""
    if not cfg.has_section("clouds"):
        cfg.add_section("clouds")
    sec = cfg["clouds"]

    # Derive cloud prefixes from [clouds] option names (first segment of `{prefix}_*`).
    cloud_prefixes = {name.split("_")[0] for name in cfg.options("clouds")}

    # Inherit remote.username into [clouds] for any prefix whose {prefix}_user is absent.
    for prefix in cloud_prefixes:
        user_key = f"{prefix}_user"
        if user_key not in cfg.options("clouds"):
            sec[user_key] = remote.username

    # Dispatch each known prefix to its parser; unknown prefixes are silently
    # skipped (they would warn via warn_unknown_fields inside every parser call).
    return [
        CLOUD_CONFIG_PARSERS[prefix](sec)
        for prefix in cloud_prefixes
        if prefix in CLOUD_CONFIG_PARSERS
    ]


# endregion FUNC_parse_clouds

# ============================================================================
# db / local / remote section parsers + parse_config assembly
# ============================================================================


def _db_valid_fields() -> Sequence[str]:
    return [f.name for f in dataclasses.fields(PostgresDbConfig)]


# region FUNC__parse_db_section
# PURPOSE: Build a frozen PostgresDbConfig from a [db] INI section.
def _parse_db_section(sec: SectionProxy) -> PostgresDbConfig:
    warn_unknown_fields(_db_valid_fields(), sec)
    return PostgresDbConfig(
        user=sec.get("user", "yascheduler"),
        password=sec.get("password", "password"),
        database=sec.get("database", "database"),
        host=sec.get("host", "localhost"),
        port=sec.getint("port", fallback=5432),
    )


# endregion FUNC__parse_db_section


def _local_valid_fields() -> Sequence[str]:
    return [f.name for f in dataclasses.fields(LocalSettings)]


# region FUNC__parse_local_section
# PURPOSE: Build a frozen LocalSettings from a [local] INI section.
def _parse_local_section(sec: SectionProxy) -> LocalSettings:
    warn_unknown_fields(_local_valid_fields(), sec)
    data_dir = Path(sec.get("data_dir", "./data")).resolve()
    return LocalSettings(
        data_dir=data_dir,
        tasks_dir=Path(sec.get("tasks_dir", str(data_dir / "tasks"))).resolve(),
        engines_dir=Path(sec.get("engines_dir", str(data_dir / "engines"))).resolve(),
        keys_dir=Path(sec.get("keys_dir", str(data_dir / "keys"))).resolve(),
        webhook_reqs_limit=_int_or_default(
            "webhook_reqs_limit",
            sec.getint("webhook_reqs_limit"),
        ),
        webhook_url=sec.get("webhook_url"),
        conn_machine_limit=_int_or_default(
            "conn_machine_limit",
            sec.getint("conn_machine_limit"),
        ),
        conn_machine_pending=_int_or_default(
            "conn_machine_pending",
            sec.getint("conn_machine_pending"),
        ),
        allocate_limit=_int_or_default("allocate_limit", sec.getint("allocate_limit")),
        allocate_pending=_int_or_default(
            "allocate_pending",
            sec.getint("allocate_pending"),
        ),
        consume_limit=_int_or_default("consume_limit", sec.getint("consume_limit")),
        consume_pending=_int_or_default(
            "consume_pending",
            sec.getint("consume_pending"),
        ),
        deallocate_limit=_int_or_default(
            "deallocate_limit",
            sec.getint("deallocate_limit"),
        ),
        deallocate_pending=_int_or_default(
            "deallocate_pending",
            sec.getint("deallocate_pending"),
        ),
    )


# endregion FUNC__parse_local_section


def _remote_valid_fields() -> Sequence[str]:
    exclude_names = ["username", "jump_username"]
    include_names = ["user", "jump_user"]
    return [
        f.name
        for f in dataclasses.fields(RemoteDefaults)
        if f.name not in exclude_names
    ] + include_names


# region FUNC__parse_remote_section
# PURPOSE: Turn a `[remote]` INI section into a validated `RemoteDefaults` value object so the rest of the system consumes immutable typed values instead of re-reading `ConfigParser` proxies at every SSH call site.
# INVARIANTS: validation runs in the parser, not in `RemoteDefaults.__post_init__` — `jump_port` is checked against the 1..65535 range via `_check_port`, mirroring the `yascheduler_nodes.jump_port` DB `CHECK` constraint; `user` and `jump_user` are INI aliases for `username` and `jump_username` and are registered in `_remote_valid_fields` so `warn_unknown_fields` does not fire on them.
# RATIONALE:
# - Q: why does `jump_port` validation run in `_parse_remote_section` via `_check_port` instead of in `RemoteDefaults.__post_init__` like `LocalSettings` does for its concurrency limits?
#   A: `jump_port` mirrors the `yascheduler_nodes.jump_port` DB `CHECK` constraint (1..65535) — keeping the same range check at parse time surfaces a misconfigured INI before any downstream code receives the value, and it follows the existing per-section parser idiom (`max_nodes`, `idle_tolerance`, cloud `{prefix}_jump_port`) so all port/limit invariants fail fast at config load; `LocalSettings` uses `__post_init__` because its limits are dataclass-internal (no DB mirror) and the parser must let a legitimate `0` reach `__post_init__` so `ge(1)` raises rather than being silently coerced.
def _parse_remote_section(sec: SectionProxy) -> RemoteDefaults:
    warn_unknown_fields(_remote_valid_fields(), sec)
    data_dir = PurePath(sec.get("data_dir", "./data"))

    jump_port = _check_port("jump_port", sec.getint("jump_port", fallback=22))

    return RemoteDefaults(
        data_dir=data_dir,
        engines_dir=PurePath(sec.get("engines_dir", str(data_dir / "engines"))),
        tasks_dir=PurePath(sec.get("tasks_dir", str(data_dir / "tasks"))),
        username=sec.get("user", "root"),
        jump_username=sec.get("jump_user", None),
        jump_host=sec.get("jump_host", None),
        jump_port=jump_port,
    )


# endregion FUNC__parse_remote_section


# region FUNC_parse_config
# PURPOSE: Read an INI file, parse each section via per-section parser functions, and return a frozen Config aggregate.
def parse_config(path: str | bytes | PurePath) -> Config:
    """Parse an INI config file (path or contents) into a frozen Config aggregate."""
    cfg = ConfigParser()
    cfg.read(path)

    for sec_name in ("db", "local", "remote", "clouds"):
        if not cfg.has_section(sec_name):
            cfg.add_section(sec_name)

    local = _parse_local_section(cfg["local"])
    remote = _parse_remote_section(cfg["remote"])
    clouds = parse_clouds(cfg, remote)

    return Config(
        db=_parse_db_section(cfg["db"]),
        local=local,
        remote=remote,
        clouds=clouds,
        engines=parse_engines(cfg, local.engines_dir),
    )


# endregion FUNC_parse_config
