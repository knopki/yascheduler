# FILE: yascheduler/domain/settings.py
# VERSION: 1.4.0
# START_MODULE_CONTRACT
#   PURPOSE: Cross-layer application settings as frozen stdlib dataclasses — local daemon config and remote SSH defaults.
#   SCOPE: Local and remote typed config DTOs: LocalSettings (daemon paths, webhook, concurrency limits) and RemoteDefaults (SSH paths, username, jump host); no INI parsing on the DTOs.
#   DEPENDS: none
#   LINKS: M-DOMAIN-PORTS, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   LocalSettings - Frozen dataclass: daemon data paths, webhook, concurrency limits; __post_init__ validates ge(1)/ge(0)
#   RemoteDefaults - Frozen dataclass: remote SSH paths, username, jump host, jump_port
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - Add jump_port: int = 22 field to RemoteDefaults; configurable via [remote] jump_port INI key.
#   PREVIOUS_CHANGE: v1.3.0 - Remove cloud_package_upgrade field from LocalSettings; the cloud-init package_upgrade knob is a cloud-only concern relocated to per-provider ConfigCloud* DTOs.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from pathlib import Path, PurePath
from typing import cast

# Concurrency-limit int fields that must be >= 1 (formerly validators.ge(1)).
_GE1_LIMIT_FIELDS = (
    "conn_machine_limit",
    "conn_machine_pending",
    "allocate_limit",
    "allocate_pending",
    "consume_limit",
    "consume_pending",
    "deallocate_limit",
    "deallocate_pending",
)


@dataclass(frozen=True)
class LocalSettings:
    """Local daemon settings: data paths, concurrency limits, webhook config."""

    data_dir: Path = Path("./data")
    tasks_dir: Path = Path("./data/tasks")
    engines_dir: Path = Path("./data/engines")
    keys_dir: Path = Path("./data/keys")
    webhook_url: str | None = None
    webhook_reqs_limit: int = 5
    conn_machine_limit: int = 10
    conn_machine_pending: int = 10
    allocate_limit: int = 20
    allocate_pending: int = 1
    consume_limit: int = 20
    consume_pending: int = 1
    deallocate_limit: int = 5
    deallocate_pending: int = 1

    # START_BLOCK_VALIDATE
    def __post_init__(self) -> None:
        """Validate field constraints.

        - Path fields must be Path instances (formerly instance_of(Path)).
        - Concurrency-limit fields in _GE1_LIMIT_FIELDS must be >= 1.
        - webhook_reqs_limit must be >= 0.
        - webhook_url, when set, must be a str.
        """
        for f in fields(type(self)):
            value = getattr(self, f.name)
            if value is None:
                continue
            if f.name in _GE1_LIMIT_FIELDS:
                if not isinstance(value, int):
                    raise ValueError(
                        f"{f.name} must be int, got {type(value).__name__}"
                    )
                if value < 1:
                    raise ValueError(f"{f.name} must be >= 1, got {value}")
            elif f.name == "webhook_reqs_limit":
                if not isinstance(value, int):
                    raise ValueError(
                        f"webhook_reqs_limit must be int, got {type(value).__name__}"
                    )
                if value < 0:
                    raise ValueError(f"webhook_reqs_limit must be >= 0, got {value}")
            elif f.name in ("data_dir", "tasks_dir", "engines_dir", "keys_dir"):
                if not isinstance(value, Path):
                    raise ValueError(
                        f"{f.name} must be Path, got {type(value).__name__}"
                    )
            elif f.name == "webhook_url":
                if not isinstance(value, str):
                    raise ValueError(
                        f"webhook_url must be str, got {type(value).__name__}"
                    )

    # END_BLOCK_VALIDATE


@dataclass(frozen=True)
class RemoteDefaults:
    """Remote machine defaults: data directories, SSH username, jump host."""

    data_dir: PurePath = PurePath("./data")
    tasks_dir: PurePath = PurePath("./data/tasks")
    engines_dir: PurePath = PurePath("./data/engines")
    username: str = "root"
    jump_username: str | None = None
    jump_host: str | None = None
    jump_port: int = 22


# Derived from LocalSettings field defaults so there is a single source of truth:
# if a field default changes, _INT_DEFAULTS follows automatically.
_INT_DEFAULTS: dict[str, int] = {
    f.name: cast("int", f.default)
    for f in fields(LocalSettings)
    if f.name in (_GE1_LIMIT_FIELDS + ("webhook_reqs_limit",))
    and f.default is not MISSING
}


def _int_or_default(name: str, value: int | None) -> int:
    """Return value if not None, else the dataclass default for name.

    Replicates converters.default_if_none(default=...) without falsy-coercing
    a legitimate 0 (which must reach __post_init__ so ge(1) raises). The
    default is read from _INT_DEFAULTS — a single source of truth derived from
    the LocalSettings field defaults.
    """
    if value is None:
        return _INT_DEFAULTS[name]
    return value
