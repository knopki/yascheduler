# FILE: yascheduler/entrypoints/config_parser.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: INI config parsing — adapter layer between ConfigParser and domain/infra types; owns parse_config assembly and all per-section parsers.
#   SCOPE: parse_engine_section, parse_engines, engine_valid_fields (P2 engine parsers); parse_cloud_section, parse_clouds, cloud_valid_fields, CLOUD_CONFIG_PARSERS (P3 cloud parsers + registry); _parse_db_section, _db_valid_fields, _parse_local_section, _local_valid_fields, _parse_remote_section, _remote_valid_fields (P4 db/local/remote parsers); parse_config public assembly (P4); _check_spawn, _check_check_, _check_at_least_one_elem, _check_az_user, _fmt_key parser-internal validators/helpers.
#   DEPENDS: M-DOMAIN-ENGINE, M-CLOUD-CONFIGS, M-DOMAIN-PORTS, M-DOMAIN-SETTINGS, M-INFRA-DB-CONFIG, M-ENTRYPOINTS-CONFIG
#   LINKS: M-DI, M-ENTRYPOINTS-CONFIG
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   parse_config - Public assembly: read INI, parse all sections, return frozen Config aggregate
#   _parse_db_section - Build PostgresDbConfig from a [db] INI section
#   _db_valid_fields - Return valid INI keys for the [db] section
#   _parse_local_section - Build LocalSettings from a [local] INI section
#   _local_valid_fields - Return valid INI keys for the [local] section
#   _parse_remote_section - Build RemoteDefaults from a [remote] INI section
#   _remote_valid_fields - Return valid INI keys for the [remote] section
#   parse_engine_section - Build a frozen Engine from a single [engine.*] INI section
#   parse_engines - Build an EngineRepository from all [engine.*] sections in a ConfigParser
#   engine_valid_fields - Return valid INI keys for an [engine.*] section (dataclass fields + deploy aliases, minus name/deployable)
#   parse_cloud_section - Dispatch a single [clouds] sub-section to its per-prefix parser via CLOUD_CONFIG_PARSERS
#   parse_clouds - Build the list of ConfigCloud DTOs from a [clouds] section, inheriting remote.username for missing prefix users
#   cloud_valid_fields - Return valid INI keys for a given cloud prefix (dataclass fields + aliases, minus prefix/username/jump_username + provider-specific excludes)
#   CLOUD_CONFIG_PARSERS - Registry mapping cloud provider prefix -> per-prefix parser callable (open/closed seam)
#   _check_spawn - Parser-side validator: reject unknown template placeholders in spawn
#   _check_check_ - Parser-side validator: require check_cmd or check_pname
#   _check_at_least_one_elem - Parser-side validator: require non-empty sequence fields
#   _check_az_user - Parser-side validator: reject username="root" for Azure
#   _fmt_key - Helper: format `{prefix}_{name}` INI key
#   _parse_azure_section - Build ConfigCloudAzure from a [clouds] section
#   _parse_hetzner_section - Build ConfigCloudHetzner from a [clouds] section
#   _parse_upcloud_section - Build ConfigCloudUpcloud from a [clouds] section
#   _parse_vastai_section - Build ConfigCloudVastAI from a [clouds] section
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - Move cloud-init package_upgrade knob to the per-provider cloud config (move-cloud-package-upgrade): remove cloud_package_upgrade=sec.getboolean(...) from _parse_local_section, and add package_upgrade=sec.getboolean(fmt("package_upgrade"), fallback=True) to _parse_azure_section/_parse_hetzner_section/_parse_upcloud_section/_parse_vastai_section. cloud_valid_fields(prefix) auto-introspects dataclasses.fields(dto_cls), so {prefix}_package_upgrade is auto-registered as a valid key with no edit to _CLOUD_FIELD_RULES, and _local_valid_fields() drops cloud_package_upgrade automatically so a leftover [local] key now surfaces as a ConfigWarning.
#   PREVIOUS_CHANGE: v1.4.0 - _parse_local_section reads optional [local] cloud_package_upgrade key via sec.getboolean(..., fallback=True) (add-hetzner-live-e2e); the new LocalSettings field defaults to True preserving pre-change cloud-init behavior, and _local_valid_fields() introspection already accepts the key with no "unknown field" warning.
# END_CHANGE_SUMMARY

from __future__ import annotations

import dataclasses
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
    from configparser import ConfigParser, SectionProxy

    from yascheduler.entrypoints.config import Config
    from yascheduler.infra.cloud.cloud_configs import ConfigCloud


# START_CONTRACT: _check_spawn
#   PURPOSE: Validate spawn command has only supported template placeholders.
#   INPUTS: { engine: Engine - engine instance under construction, value: str - spawn command string }
#   OUTPUTS: { None - raises ValueError on invalid placeholders }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-ENGINE
# END_CONTRACT: _check_spawn
def _check_spawn(engine: Engine, value: str) -> None:
    try:
        value.format(task_path="", engine_path="", ncpus="")
    except KeyError as err:
        msg = "Engine {name} has unknown template placeholder `{placeholder}` in *spawn* command"
        raise ValueError(msg.format(name=engine.name, placeholder=err.args[0])) from err


# START_CONTRACT: _check_check_
#   PURPOSE: Ensure at least one of check_cmd or check_pname is set on the engine.
#   INPUTS: { engine: Engine - engine instance under construction }
#   OUTPUTS: { None - raises ValueError if both check_cmd and check_pname are unset }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-ENGINE
# END_CONTRACT: _check_check_
def _check_check_(engine: Engine) -> None:
    if not engine.check_cmd and not engine.check_pname:
        raise ValueError(
            f"Engine {engine.name} has no *check_cmd* or *check_pname* set"
        )


# START_CONTRACT: _check_at_least_one_elem
#   PURPOSE: Validate that a sequence field on the engine has at least one element.
#   INPUTS: { engine: Engine - engine instance under construction, field_name: str - field name for the error message, value: Sequence - the sequence value to check }
#   OUTPUTS: { None - raises ValueError if sequence is empty or None }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-ENGINE
# END_CONTRACT: _check_at_least_one_elem
def _check_at_least_one_elem(
    engine: Engine, field_name: str, value: Sequence[object] | None
) -> None:
    if not value or len(value) < 1:
        raise ValueError(f"Engine {engine.name} has no *{field_name}* config set")


# START_CONTRACT: engine_valid_fields
#   PURPOSE: Return valid INI keys for an [engine.*] section (dataclass fields + deploy aliases, excluding name and deployable).
#   INPUTS: { None }
#   OUTPUTS: { Sequence[str] - list of valid config keys }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-ENGINE, M-ENTRYPOINTS-CONFIG
# END_CONTRACT: engine_valid_fields
def engine_valid_fields() -> Sequence[str]:
    exclude_names = ["name", "deployable"]
    include_names = [
        "deploy_local_files",
        "deploy_local_archive",
        "deploy_remote_archive",
    ]
    return [
        f.name for f in dataclasses.fields(Engine) if f.name not in exclude_names
    ] + include_names


# START_CONTRACT: parse_engine_section
#   PURPOSE: Build a frozen Engine from a single [engine.*] INI section.
#   INPUTS: { sec: SectionProxy - config parser section with engine keys, engines_dir: PurePath - engines directory for resolving deploy paths }
#   OUTPUTS: { Engine - frozen engine value object }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys.
#   RAISES: ValueError - on invalid spawn placeholders, missing check methods, or empty input_files/output_files (parser-side validators)
#   LINKS: M-DOMAIN-ENGINE, M-ENTRYPOINTS-CONFIG
# END_CONTRACT: parse_engine_section
def parse_engine_section(sec: SectionProxy, engines_dir: PurePath) -> Engine:
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
        raise ValueError(f"Engine {name} has no spawn command")
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

    # START_BLOCK_VALIDATE_ENGINE
    _check_spawn(engine, engine.spawn)
    _check_check_(engine)
    _check_at_least_one_elem(engine, "input_files", engine.input_files)
    _check_at_least_one_elem(engine, "output_files", engine.output_files)
    # END_BLOCK_VALIDATE_ENGINE
    return engine


# START_CONTRACT: parse_engines
#   PURPOSE: Parse all engine.* sections from an INI config into an EngineRepository.
#   INPUTS: { cfg: ConfigParser - parsed INI config, engines_dir: PurePath - engines directory path }
#   OUTPUTS: { EngineRepository - frozen repository populated with engines from config }
#   SIDE_EFFECTS: None
#   RAISES: ValueError - propagated from parse_engine_section validators
#   LINKS: M-DOMAIN-ENGINE, M-ENTRYPOINTS-CONFIG
# END_CONTRACT: parse_engines
def parse_engines(cfg: ConfigParser, engines_dir: PurePath) -> EngineRepository:
    snames = filter(lambda x: x.startswith("engine."), cfg.sections())
    data: dict[str, Engine] = {}
    for sname in snames:
        engine = parse_engine_section(cfg[sname], engines_dir)
        data[engine.name] = engine
    return EngineRepository(data=data)


# ============================================================================
# Cloud config parsers (cloud-configs-to-infra-registry / P3)
# ============================================================================


# START_CONTRACT: _check_az_user
#   PURPOSE: Reject username="root" for Azure (parser-side validator).
#   INPUTS: { username: str - the Azure username candidate }
#   OUTPUTS: { None - raises ValueError if username == "root" }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS
# END_CONTRACT: _check_az_user
def _check_az_user(username: str) -> None:
    if username == "root":
        raise ValueError("Root user is forbidden on Azure")


# START_CONTRACT: _fmt_key
#   PURPOSE: Format the INI key `{prefix}_{name}` for a cloud provider config field.
#   INPUTS: { prefix: str - provider prefix (e.g. "az", "hetzner"), name: str - field alias name }
#   OUTPUTS: { str - "{prefix}_{name}" }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-CONFIGS
# END_CONTRACT: _fmt_key
def _fmt_key(prefix: str, name: str) -> str:
    return f"{prefix}_{name}"


# Per-prefix valid-field tables. Excludes are the dataclass fields not surfaced as
# INI keys (prefix is a class attr, not a field; username/jump_username surface via
# user/jump_user aliases); provider-specific includes add the INI aliases (e.g. az
# uses `image` for vm_image and `size` for vm_size).
_AZ_EXCLUDES = {"prefix", "username", "jump_username", "vm_image", "vm_size"}
_AZ_INCLUDES = ["user", "jump_user", "image", "size"]
_HETZNER_EXCLUDES = {"prefix", "username", "jump_username"}
_HETZNER_INCLUDES = ["user", "jump_user"]
_UPCLOUD_EXCLUDES = {"prefix", "username", "jump_username"}
_UPCLOUD_INCLUDES = ["user", "jump_user"]
_VASTAI_EXCLUDES = {"prefix", "username", "jump_username", "env"}
_VASTAI_INCLUDES = ["user", "jump_user"]


# START_CONTRACT: cloud_valid_fields
#   PURPOSE: Return valid INI keys for a [clouds] sub-section keyed by a cloud provider prefix.
#   INPUTS: { prefix: str - provider prefix (az/hetzner/upcloud/vastai) }
#   OUTPUTS: { Sequence[str] - list of `{prefix}_{field_or_alias}` keys }
#   SIDE_EFFECTS: None
#   RAISES: KeyError - if prefix is not in CLOUD_CONFIG_PARSERS (unknown provider)
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: cloud_valid_fields
def cloud_valid_fields(prefix: str) -> Sequence[str]:
    exclude_names, include_names = _CLOUD_FIELD_RULES[prefix]
    dto_cls = _CLOUD_DTO_BY_PREFIX[prefix]
    return [
        f"{prefix}_{name}"
        for name in (
            [f.name for f in dataclasses.fields(dto_cls) if f.name not in exclude_names]
            + include_names
        )
    ]


# START_CONTRACT: _parse_azure_section
#   PURPOSE: Build ConfigCloudAzure from a [clouds] INI section.
#   INPUTS: { sec: SectionProxy - [clouds] config parser section with az_* prefixed keys }
#   OUTPUTS: { ConfigCloudAzure - frozen Azure cloud configuration }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys across all 4 providers' valid fields.
#   RAISES: ValueError - if username == "root" (parser-side _check_az_user) or AzureImageReference.from_urn fails on a malformed az_image URN
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _parse_azure_section
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
        raise ValueError(f"az max_nodes must be >= 0, got {max_nodes}")
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=300)
    if idle_tolerance < 1:
        raise ValueError(f"az idle_tolerance must be >= 1, got {idle_tolerance}")

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
    )


# START_CONTRACT: _parse_hetzner_section
#   PURPOSE: Build ConfigCloudHetzner from a [clouds] INI section.
#   INPUTS: { sec: SectionProxy - [clouds] config parser section with hetzner_* prefixed keys }
#   OUTPUTS: { ConfigCloudHetzner - frozen Hetzner cloud configuration }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys across all 4 providers' valid fields.
#   RAISES: ValueError - if max_nodes < 0 or idle_tolerance < 1
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _parse_hetzner_section
def _parse_hetzner_section(sec: SectionProxy) -> ConfigCloudHetzner:
    prefix = "hetzner"
    fmt = partial(_fmt_key, prefix)

    warn_unknown_fields(_ALL_CLOUD_VALID_FIELDS, sec)

    max_nodes = sec.getint(fmt("max_nodes"), fallback=10)
    if max_nodes < 0:
        raise ValueError(f"hetzner max_nodes must be >= 0, got {max_nodes}")
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=120)
    if idle_tolerance < 1:
        raise ValueError(f"hetzner idle_tolerance must be >= 1, got {idle_tolerance}")

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
    )


# START_CONTRACT: _parse_upcloud_section
#   PURPOSE: Build ConfigCloudUpcloud from a [clouds] INI section.
#   INPUTS: { sec: SectionProxy - [clouds] config parser section with upcloud_* prefixed keys }
#   OUTPUTS: { ConfigCloudUpcloud - frozen Upcloud cloud configuration }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys across all 4 providers' valid fields.
#   RAISES: ValueError - if max_nodes < 0 or idle_tolerance < 1
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _parse_upcloud_section
def _parse_upcloud_section(sec: SectionProxy) -> ConfigCloudUpcloud:
    prefix = "upcloud"
    fmt = partial(_fmt_key, prefix)

    warn_unknown_fields(_ALL_CLOUD_VALID_FIELDS, sec)

    max_nodes = sec.getint(fmt("max_nodes"), fallback=10)
    if max_nodes < 0:
        raise ValueError(f"upcloud max_nodes must be >= 0, got {max_nodes}")
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=120)
    if idle_tolerance < 1:
        raise ValueError(f"upcloud idle_tolerance must be >= 1, got {idle_tolerance}")

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
    )


# START_CONTRACT: _parse_vastai_section
#   PURPOSE: Build ConfigCloudVastAI from a [clouds] INI section.
#   INPUTS: { sec: SectionProxy - [clouds] config parser section with vastai_* prefixed keys }
#   OUTPUTS: { ConfigCloudVastAI - frozen VastAI cloud configuration }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys across all 4 providers' valid fields.
#   RAISES: ValueError - if disk_gb/min_vram_mb/num_gpus < 1, max_price_per_hr/max_nodes < 0, or idle_tolerance < 1
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _parse_vastai_section
def _parse_vastai_section(sec: SectionProxy) -> ConfigCloudVastAI:
    prefix = "vastai"
    fmt = partial(_fmt_key, prefix)

    warn_unknown_fields(_ALL_CLOUD_VALID_FIELDS, sec)

    disk_gb = sec.getint(fmt("disk_gb"), fallback=80)
    if disk_gb < 1:
        raise ValueError(f"vastai disk_gb must be >= 1, got {disk_gb}")
    min_vram_mb = sec.getint(fmt("min_vram_mb"), fallback=80 * 1024)
    if min_vram_mb < 1024:
        raise ValueError(f"vastai min_vram_mb must be >= 1024, got {min_vram_mb}")
    num_gpus = sec.getint(fmt("num_gpus"), fallback=1)
    if num_gpus < 1:
        raise ValueError(f"vastai num_gpus must be >= 1, got {num_gpus}")
    max_price_per_hr = sec.getfloat(fmt("max_price_per_hr"), fallback=1.50)
    if max_price_per_hr < 0:
        raise ValueError(
            f"vastai max_price_per_hr must be >= 0, got {max_price_per_hr}"
        )
    max_nodes = sec.getint(fmt("max_nodes"), fallback=10)
    if max_nodes < 0:
        raise ValueError(f"vastai max_nodes must be >= 0, got {max_nodes}")
    idle_tolerance = sec.getint(fmt("idle_tolerance"), fallback=300)
    if idle_tolerance < 1:
        raise ValueError(f"vastai idle_tolerance must be >= 1, got {idle_tolerance}")

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
    )


# Open/closed registry: adding a provider = one parser function + one entry here.
# The aggregate root (Config.from_config_parser) iterates this registry via
# parse_clouds and never hardcodes the variant list.
# Typed against the ConfigCloud Union (the concrete DTOs the parsers return);
# application-layer consumers type against the domain CloudConfig Protocol and
# the DTOs satisfy both structurally.
CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], ConfigCloud]] = {
    "az": _parse_azure_section,
    "hetzner": _parse_hetzner_section,
    "upcloud": _parse_upcloud_section,
    "vastai": _parse_vastai_section,
}

# Mapping prefix -> (dataclass, exclude_names, include_names) used by
# cloud_valid_fields. Kept as module-level constants so the parser functions and
# the registry reference the same DTO classes.
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

# Union of all providers' valid INI keys — passed to warn_unknown_fields so a key
# belonging to any provider prefix does not warn (the [clouds] section is shared
# across all providers, unlike [engine.*] which is per-engine).
_ALL_CLOUD_VALID_FIELDS: list[str] = [
    *cloud_valid_fields("az"),
    *cloud_valid_fields("hetzner"),
    *cloud_valid_fields("upcloud"),
    *cloud_valid_fields("vastai"),
]


# START_CONTRACT: parse_cloud_section
#   PURPOSE: Dispatch a [clouds] sub-section to its per-prefix parser via the registry.
#   INPUTS: { sec: SectionProxy - [clouds] config parser section, prefix: str - provider prefix }
#   OUTPUTS: { ConfigCloud - frozen cloud provider config DTO }
#   SIDE_EFFECTS: None (warn_unknown_fields runs inside the per-prefix parser)
#   RAISES: KeyError - if prefix is not in CLOUD_CONFIG_PARSERS (unknown provider)
#   LINKS: M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: parse_cloud_section
def parse_cloud_section(sec: SectionProxy, prefix: str) -> ConfigCloud:
    return CLOUD_CONFIG_PARSERS[prefix](sec)


# START_CONTRACT: parse_clouds
#   PURPOSE: Build the list of ConfigCloud DTOs from a [clouds] section, inheriting remote.username for missing prefix users.
#   INPUTS: { cfg: ConfigParser - parsed INI config with a [clouds] section, remote: RemoteDefaults - remote defaults (username inherited) }
#   OUTPUTS: { list[ConfigCloud] - one DTO per provider prefix present in [clouds] options }
#   SIDE_EFFECTS: Mutates cfg["clouds"] to inject `{prefix}_user = remote.username` for any prefix whose user key is absent.
#   LINKS: M-CLOUD-CONFIGS, M-DOMAIN-SETTINGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: parse_clouds
def parse_clouds(cfg: ConfigParser, remote: RemoteDefaults) -> list[ConfigCloud]:
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


# ============================================================================
# db / local / remote section parsers + parse_config assembly
# (config-aggregate-to-entrypoints / P4)
# ============================================================================


# START_CONTRACT: _db_valid_fields
#   PURPOSE: Return valid INI keys for the [db] section (PostgresDbConfig dataclass fields).
#   INPUTS: { None }
#   OUTPUTS: { Sequence[str] - list of valid config keys }
#   SIDE_EFFECTS: None
#   LINKS: M-INFRA-DB-CONFIG, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _db_valid_fields
def _db_valid_fields() -> Sequence[str]:
    return [f.name for f in dataclasses.fields(PostgresDbConfig)]


# START_CONTRACT: _parse_db_section
#   PURPOSE: Build a frozen PostgresDbConfig from a [db] INI section.
#   INPUTS: { sec: SectionProxy - config parser section with db config keys }
#   OUTPUTS: { PostgresDbConfig - frozen database connection configuration }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys.
#   LINKS: M-INFRA-DB-CONFIG, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _parse_db_section
def _parse_db_section(sec: SectionProxy) -> PostgresDbConfig:
    warn_unknown_fields(_db_valid_fields(), sec)
    return PostgresDbConfig(
        user=sec.get("user", "yascheduler"),
        password=sec.get("password", "password"),
        database=sec.get("database", "database"),
        host=sec.get("host", "localhost"),
        port=sec.getint("port", fallback=5432),
    )


# START_CONTRACT: _local_valid_fields
#   PURPOSE: Return valid INI keys for the [local] section (LocalSettings dataclass fields).
#   INPUTS: { None }
#   OUTPUTS: { Sequence[str] - list of valid config keys }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-SETTINGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _local_valid_fields
def _local_valid_fields() -> Sequence[str]:
    return [f.name for f in dataclasses.fields(LocalSettings)]


# START_CONTRACT: _parse_local_section
#   PURPOSE: Build a frozen LocalSettings from a [local] INI section.
#   INPUTS: { sec: SectionProxy - config parser section with local config keys }
#   OUTPUTS: { LocalSettings - frozen local daemon settings }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys.
#   LINKS: M-DOMAIN-SETTINGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _parse_local_section
def _parse_local_section(sec: SectionProxy) -> LocalSettings:
    warn_unknown_fields(_local_valid_fields(), sec)
    data_dir = Path(sec.get("data_dir", "./data")).resolve()
    # sec.getint(...) returns None when the key is absent; _int_or_default
    # coerces None back to the dataclass default (matching the former
    # converters.default_if_none) without falsy-coercing a legitimate 0.
    return LocalSettings(
        data_dir=data_dir,
        tasks_dir=Path(sec.get("tasks_dir", str(data_dir / "tasks"))).resolve(),
        engines_dir=Path(sec.get("engines_dir", str(data_dir / "engines"))).resolve(),
        keys_dir=Path(sec.get("keys_dir", str(data_dir / "keys"))).resolve(),
        webhook_reqs_limit=_int_or_default(
            "webhook_reqs_limit", sec.getint("webhook_reqs_limit")
        ),
        webhook_url=sec.get("webhook_url"),
        conn_machine_limit=_int_or_default(
            "conn_machine_limit", sec.getint("conn_machine_limit")
        ),
        conn_machine_pending=_int_or_default(
            "conn_machine_pending", sec.getint("conn_machine_pending")
        ),
        allocate_limit=_int_or_default("allocate_limit", sec.getint("allocate_limit")),
        allocate_pending=_int_or_default(
            "allocate_pending", sec.getint("allocate_pending")
        ),
        consume_limit=_int_or_default("consume_limit", sec.getint("consume_limit")),
        consume_pending=_int_or_default(
            "consume_pending", sec.getint("consume_pending")
        ),
        deallocate_limit=_int_or_default(
            "deallocate_limit", sec.getint("deallocate_limit")
        ),
        deallocate_pending=_int_or_default(
            "deallocate_pending", sec.getint("deallocate_pending")
        ),
    )


# START_CONTRACT: _remote_valid_fields
#   PURPOSE: Return valid INI keys for the [remote] section (RemoteDefaults dataclass fields, with user/jump_user aliases replacing username/jump_username).
#   INPUTS: { None }
#   OUTPUTS: { Sequence[str] - list of valid config keys }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-SETTINGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _remote_valid_fields
def _remote_valid_fields() -> Sequence[str]:
    exclude_names = ["username", "jump_username"]
    include_names = ["user", "jump_user"]
    return [
        f.name
        for f in dataclasses.fields(RemoteDefaults)
        if f.name not in exclude_names
    ] + include_names


# START_CONTRACT: _parse_remote_section
#   PURPOSE: Build a frozen RemoteDefaults from a [remote] INI section.
#   INPUTS: { sec: SectionProxy - config parser section with remote config keys }
#   OUTPUTS: { RemoteDefaults - frozen remote machine defaults }
#   SIDE_EFFECTS: Emits ConfigWarning via warn_unknown_fields for unknown keys.
#   LINKS: M-DOMAIN-SETTINGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: _parse_remote_section
def _parse_remote_section(sec: SectionProxy) -> RemoteDefaults:
    warn_unknown_fields(_remote_valid_fields(), sec)
    data_dir = PurePath(sec.get("data_dir", "./data"))
    return RemoteDefaults(
        data_dir=data_dir,
        engines_dir=PurePath(sec.get("engines_dir", str(data_dir / "engines"))),
        tasks_dir=PurePath(sec.get("tasks_dir", str(data_dir / "tasks"))),
        username=sec.get("user", "root"),
        jump_username=sec.get("jump_user", None),
        jump_host=sec.get("jump_host", None),
    )


# START_CONTRACT: parse_config
#   PURPOSE: Read an INI file, parse each section via per-section parser functions, and return a frozen Config aggregate.
#   INPUTS: { path: str | bytes | PurePath - path or contents of INI config file }
#   OUTPUTS: { Config - fully populated frozen configuration object }
#   SIDE_EFFECTS: Reads from filesystem when path is a path; mutates the in-memory ConfigParser to add missing [db]/[local]/[remote]/[clouds] sections and to inherit remote.username into [clouds].
#   LINKS: M-ENTRYPOINTS-CONFIG, M-INFRA-DB-CONFIG, M-DOMAIN-SETTINGS, M-DOMAIN-ENGINE, M-CLOUD-CONFIGS, M-ENTRYPOINTS-CONFIG-PARSER
# END_CONTRACT: parse_config
def parse_config(path: str | bytes | PurePath) -> Config:
    """Parse an INI config file (path or contents) into a frozen Config aggregate."""
    from configparser import ConfigParser

    from yascheduler.entrypoints.config import Config

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
