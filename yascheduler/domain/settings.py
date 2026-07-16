"""Cross-layer application settings as frozen stdlib dataclasses — local daemon config and remote SSH defaults."""
# region MODULE_CONTRACT
# PURPOSE: Carry daemon and remote-SSH defaults as validated, immutable values shared across layers without re-parsing INI at each use site.
# SCOPE:
# - LocalSettings (daemon data paths, webhook, concurrency limits) and RemoteDefaults (remote SSH paths, username, jump host).
# - NOT: INI parsing (entrypoints.config_parser) or cloud-provider config (infra.cloud.cloud_configs).
# INVARIANTS: After construction, concurrency-limit fields are >= 1, webhook_reqs_limit >= 0, and path fields are Path instances.
# KEYWORDS: settings, config, daemon, concurrency limits, webhook, jump host, LocalSettings, RemoteDefaults
# endregion MODULE_CONTRACT

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path, PurePath
from typing import cast

__all__ = ["LocalSettings", "RemoteDefaults"]

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


# region CLASS_LocalSettings
# PURPOSE: Freeze the daemon's runtime configuration (paths, webhook, concurrency limits) so it is validated once and shared safely across async components.
# INVARIANTS: Concurrency-limit fields >= 1; webhook_reqs_limit >= 0; path fields are Path instances.
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

    # region BLOCK_validate
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
                    msg = f"{f.name} must be int, got {type(value).__name__}"
                    raise ValueError(msg)
                if value < 1:
                    msg = f"{f.name} must be >= 1, got {value}"
                    raise ValueError(msg)
            elif f.name == "webhook_reqs_limit":
                if not isinstance(value, int):
                    msg = f"webhook_reqs_limit must be int, got {type(value).__name__}"
                    raise ValueError(msg)
                if value < 0:
                    msg = f"webhook_reqs_limit must be >= 0, got {value}"
                    raise ValueError(msg)
            elif f.name in ("data_dir", "tasks_dir", "engines_dir", "keys_dir"):
                if not isinstance(value, Path):
                    msg = f"{f.name} must be Path, got {type(value).__name__}"
                    raise ValueError(msg)
            elif f.name == "webhook_url":
                if not isinstance(value, str):
                    msg = f"webhook_url must be str, got {type(value).__name__}"
                    raise ValueError(msg)

    # endregion BLOCK_validate


# endregion CLASS_LocalSettings


@dataclass(frozen=True)
class RemoteDefaults:
    """Remote machine defaults: data directories, SSH username, jump host."""

    data_dir: PurePath = field(default_factory=lambda: PurePath("./data"))
    tasks_dir: PurePath = field(default_factory=lambda: PurePath("./data/tasks"))
    engines_dir: PurePath = field(default_factory=lambda: PurePath("./data/engines"))
    username: str = "root"
    jump_username: str | None = None
    jump_host: str | None = None
    jump_port: int = 22


# Derived from LocalSettings field defaults so there is a single source of truth:
# if a field default changes, _INT_DEFAULTS follows automatically.
_INT_DEFAULTS: dict[str, int] = {
    f.name: cast("int", f.default)
    for f in fields(LocalSettings)
    if f.name in ((*_GE1_LIMIT_FIELDS, "webhook_reqs_limit"))
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
