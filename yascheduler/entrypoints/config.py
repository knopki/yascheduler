# FILE: yascheduler/entrypoints/config.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Composition-root config aggregate bundling settings from all inner layers for delivery to the orchestrator and CLIs.
#   SCOPE: Config frozen dataclass aggregating PostgresDbConfig, LocalSettings, RemoteDefaults, Sequence[CloudConfig], EngineRepository; only entrypoints consumes it.
#   DEPENDS: M-DOMAIN-SETTINGS, M-INFRA-DB-CONFIG, M-CLOUD-CONFIGS, M-DOMAIN-ENGINE
#   LINKS: M-DI, M-ENTRYPOINTS-CONFIG-PARSER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Config - Frozen dataclass: composition-root aggregate (db, local, remote, clouds, engines); importable from yascheduler.entrypoints
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Relocate Config aggregate from yascheduler.config.config to yascheduler.entrypoints.config as a frozen stdlib dataclass (config-aggregate-to-entrypoints / P4); no attrs dependency; INI parsing owned by parse_config in entrypoints.config_parser.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from yascheduler.domain import (
        CloudConfig,
        EngineRepository,
        LocalSettings,
        RemoteDefaults,
    )
    from yascheduler.infra.persistence import PostgresDbConfig


@dataclass(frozen=True)
class Config:
    """Composition-root config aggregate."""

    db: PostgresDbConfig
    local: LocalSettings
    remote: RemoteDefaults
    clouds: Sequence[CloudConfig]
    engines: EngineRepository
