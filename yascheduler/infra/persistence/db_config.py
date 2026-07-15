"""PostgreSQL connection configuration as a frozen stdlib dataclass."""
# FILE: yascheduler/infra/persistence/db_config.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: PostgreSQL connection configuration as a frozen stdlib dataclass.
#   SCOPE: PostgresDbConfig frozen dataclass with user/password/database/host/port; no INI parsing.
#   DEPENDS: none
#   LINKS: M-PERSISTENCE-UOW, M-PERSISTENCE-SCHEMA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   PostgresDbConfig - Frozen dataclass: PostgreSQL connection params; __post_init__ validates port >= 1
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Relocate ConfigDb from yascheduler.config.db to yascheduler.infra.persistence.db_config as PostgresDbConfig frozen stdlib dataclass; INI parsing moves to entrypoints.config_parser; no attrs dependency.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresDbConfig:
    """PostgreSQL connection configuration."""

    user: str = "yascheduler"
    password: str = "password"  # noqa:  S105 not a real password
    database: str = "database"
    host: str = "localhost"
    port: int = 5432

    # START_BLOCK_VALIDATE
    def __post_init__(self) -> None:
        """Validate port >= 1."""
        if not self.port >= 1:
            msg = f"port must be >= 1, got {self.port}"
            raise ValueError(msg)

    # END_BLOCK_VALIDATE
