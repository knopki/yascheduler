# FILE: yascheduler/infra/persistence/db_config.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: PostgreSQL connection configuration as a frozen stdlib dataclass.
#   SCOPE: PostgresDbConfig value object with user/password/database/host/port; no INI parsing on the DTO.
#   DEPENDS: none
#   LINKS: M-PERSISTENCE-UOW, M-PERSISTENCE-SCHEMA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   PostgresDbConfig - Frozen dataclass: PostgreSQL connection params; __post_init__ validates port >= 1
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Relocate ConfigDb from yascheduler.config.db to yascheduler.infra.persistence.db_config as PostgresDbConfig frozen stdlib dataclass (config-aggregate-to-entrypoints / P4); INI parsing moves to entrypoints.config_parser; no attrs dependency.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresDbConfig:
    """PostgreSQL connection configuration."""

    user: str = "yascheduler"
    password: str = "password"
    database: str = "database"
    host: str = "localhost"
    port: int = 5432

    # START_BLOCK_VALIDATE
    def __post_init__(self) -> None:
        """Validate port >= 1 (formerly attrs validator)."""
        if not isinstance(self.port, int):
            raise ValueError(f"port must be int, got {type(self.port).__name__}")
        if self.port < 1:
            raise ValueError(f"port must be >= 1, got {self.port}")

    # END_BLOCK_VALIDATE
