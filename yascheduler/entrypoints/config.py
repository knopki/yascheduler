"""Composition-root config aggregate bundling settings from all inner layers for delivery to the orchestrator and CLIs."""
# region MODULE_CONTRACT
# PURPOSE: Bundle all layer-specific settings (DB, local, remote, clouds, engines) into a single frozen composition-root dataclass for delivery to the orchestrator and CLI entry points.
# SCOPE: Config frozen dataclass — composition-root aggregate; no parsing logic (owned by config_parser).
# KEYWORDS: config, composition-root, settings, aggregate
# endregion MODULE_CONTRACT

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from yascheduler.domain import (
        EngineRepository,
        LocalSettings,
        RemoteDefaults,
    )
    from yascheduler.infra.cloud.cloud_configs import ConfigCloud
    from yascheduler.infra.persistence import PostgresDbConfig


@dataclass(frozen=True)
class Config:
    """Composition-root config aggregate."""

    db: PostgresDbConfig
    local: LocalSettings
    remote: RemoteDefaults
    clouds: Sequence[ConfigCloud]
    engines: EngineRepository
