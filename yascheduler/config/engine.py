#!/usr/bin/env python3
# FILE: yascheduler/config/engine.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Calculation engine definition: spawn command, check command, deployables, platforms.
#   SCOPE: Engine dataclass, deploy types (LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy).
#   DEPENDS: M-CONFIG-UTILS
#   LINKS: M-CONFIG-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Engine - Calculation engine configuration dataclass
#   LocalFilesDeploy - Deploy local files configuration
#   LocalArchiveDeploy - Deploy local archive configuration
#   RemoteArchiveDeploy - Deploy remote archive configuration
#   Deploy - Union type of all deploy configurations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Engine configuration"""

from collections.abc import Sequence
from configparser import SectionProxy
from pathlib import PurePath
from typing import Optional, Union

from attrs import Attribute, define, field, fields, validators

from .utils import make_default_field, warn_unknown_fields


# START_CONTRACT: _check_spawn
#   PURPOSE: Validate spawn command has only supported template placeholders
#   INPUTS: { instance: Engine - engine instance, _: Attribute - attribute being validated, value: str - spawn command string }
#   OUTPUTS: { None - raises ValueError on invalid placeholders }
#   SIDE_EFFECTS: None
#   LINKS: M-CONFIG-ENGINE
# END_CONTRACT: _check_spawn
def _check_spawn(instance: "Engine", _, value: str):
    try:
        value.format(task_path="", engine_path="", ncpus="")
    except KeyError as err:
        msg = "Engine {name} has unknown template placeholder `{placeholder}` in *spawn* command"
        raise ValueError(
            msg.format(name=instance.name, placeholder=err.args[0])
        ) from err


# START_CONTRACT: _check_check_
#   PURPOSE: Ensure at least one of check_cmd or check_pname is set on the engine
#   INPUTS: { instance: Engine - engine instance, attribute: Attribute - attribute being validated, value: Optional[str] - the check command or process name }
#   OUTPUTS: { None - raises ValueError if both check_cmd and check_pname are unset }
#   SIDE_EFFECTS: None
#   LINKS: M-CONFIG-ENGINE
# END_CONTRACT: _check_check_
def _check_check_(instance: "Engine", attribute: Attribute, value: Optional[str]):
    no_check_cmd_curr = attribute.name == "check_cmd" and not value
    no_check_pname_curr = attribute.name == "check_pname" and not value
    if (no_check_cmd_curr and not instance.check_pname) or (
        no_check_pname_curr and not instance.check_cmd
    ):
        raise ValueError(
            f"Engine {instance.name} has no *check_cmd* or *check_pname* set"
        )


# START_CONTRACT: _check_at_least_one_elem
#   PURPOSE: Validate that a sequence attribute has at least one element
#   INPUTS: { instance: Engine - engine instance, attribute: Attribute - attribute being validated, value: Optional[Sequence] - the sequence value to check }
#   OUTPUTS: { None - raises ValueError if sequence is empty or None }
#   SIDE_EFFECTS: None
#   LINKS: M-CONFIG-ENGINE
# END_CONTRACT: _check_at_least_one_elem
def _check_at_least_one_elem(
    instance: "Engine", attribute: Attribute, value: Optional[Sequence]
):
    if not value or len(value) < 1:
        raise ValueError(f"Engine {instance.name} has no *{attribute.name}* config set")


@define(frozen=True)
class LocalFilesDeploy:
    "Deploy local files configuration"

    files: tuple[PurePath, ...] = field(factory=tuple)


@define(frozen=True)
class LocalArchiveDeploy:
    "Deploy local archive configuration"

    file: PurePath


@define(frozen=True)
class RemoteArchiveDeploy:
    "Deploy remote archive configuration"

    url: str


Deploy = Union[
    LocalFilesDeploy,
    LocalArchiveDeploy,
    RemoteArchiveDeploy,
]


@define
class Engine:
    """Engine configuration"""

    name: str = field(validator=[validators.instance_of(str)])
    spawn: str = field(validator=[validators.instance_of(str), _check_spawn])
    check_cmd: Optional[str] = field(
        validator=[validators.optional(validators.instance_of(str)), _check_check_]
    )
    check_pname: Optional[str] = field(
        validator=[validators.optional(validators.instance_of(str)), _check_check_]
    )
    deployable: tuple[Deploy, ...] = field(factory=tuple)
    input_files: tuple[str, ...] = field(
        factory=tuple,
        validator=[
            validators.deep_iterable(member_validator=validators.instance_of(str)),
            _check_at_least_one_elem,
        ],
    )
    output_files: tuple[str, ...] = field(
        factory=tuple,
        validator=[
            validators.deep_iterable(member_validator=validators.instance_of(str)),
            _check_at_least_one_elem,
        ],
    )
    platforms: tuple[str, ...] = field(
        factory=tuple,
        validator=[
            validators.deep_iterable(member_validator=validators.instance_of(str))
        ],
    )
    platform_packages: tuple[str, ...] = field(
        factory=tuple,
        validator=[
            validators.deep_iterable(member_validator=validators.instance_of(str))
        ],
    )
    check_cmd_code: int = make_default_field(0)
    sleep_interval: int = make_default_field(10)

    # START_CONTRACT: get_valid_config_parser_fields
    #   PURPOSE: Return valid config parser field names including deploy alias fields
    #   INPUTS: { None }
    #   OUTPUTS: { Sequence[str] - list of valid config keys }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-ENGINE
    # END_CONTRACT: get_valid_config_parser_fields
    @classmethod
    def get_valid_config_parser_fields(cls) -> Sequence[str]:
        "Returns a list of valid config keys"
        exclude_names = ["name", "deployable"]
        include_names = [
            "deploy_local_files",
            "deploy_local_archive",
            "deploy_remote_archive",
        ]
        return [
            f.name for f in fields(cls) if f.name not in exclude_names
        ] + include_names

    # START_CONTRACT: from_config_parser_section
    #   PURPOSE: Create Engine instance from a config parser section
    #   INPUTS: { sec: SectionProxy - config parser section with engine keys, engines_dir: PurePath - engines directory for resolving deploy paths }
    #   OUTPUTS: { Engine - engine configuration }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-ENGINE
    # END_CONTRACT: from_config_parser_section
    @classmethod
    def from_config_parser_section(
        cls, sec: SectionProxy, engines_dir: PurePath
    ) -> "Engine":
        "Create config from config parser's section"

        warn_unknown_fields(cls.get_valid_config_parser_fields(), sec)

        def gettuple(key: str) -> tuple[str, ...]:
            return tuple(
                x.strip() for x in filter(None, sec.get(key, fallback="").split())
            )

        name = sec.name[7:]
        engine_dir = engines_dir / name

        deployable: Sequence[Deploy] = []
        deploy_local_files = [
            engine_dir / x.strip() for x in gettuple("deploy_local_files")
        ]
        if deploy_local_files:
            deployable.append(LocalFilesDeploy(files=tuple(deploy_local_files)))
        deploy_local_archive = sec.get("deploy_local_archive", None)
        if deploy_local_archive:
            deploy = LocalArchiveDeploy(file=engine_dir / deploy_local_archive)
            deployable.append(deploy)
        deploy_remote_archive = sec.get("deploy_remote_archive", None)
        if deploy_remote_archive:
            deploy = RemoteArchiveDeploy(url=deploy_remote_archive)
            deployable.append(deploy)

        return cls(
            name=name,
            deployable=tuple(deployable),
            spawn=sec.get("spawn"),  # type: ignore
            check_cmd=sec.get("check_cmd"),
            check_cmd_code=sec.getint("check_cmd_code"),  # type: ignore
            check_pname=sec.get("check_pname"),
            input_files=gettuple("input_files"),
            output_files=gettuple("output_files"),
            sleep_interval=sec.getint("sleep_interval"),  # type: ignore
            platforms=gettuple("platforms"),
            platform_packages=gettuple("platform_packages"),
        )
