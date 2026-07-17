"""Cloud DTOs."""
# region MODULE_CONTRACT
# PURPOSE: Define data-transfer objects for cloud adapter operations.
# SCOPE: Bare DTO only.
# KEYWORDS: dto, create node, cloud
# endregion MODULE_CONTRACT

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CloudCreateNodeDTO"]


@dataclass(frozen=True)
class CloudCreateNodeDTO:
    """Result of a cloud provider create_node call."""

    external_id: str
    hostname: str
    username: str = "root"
    port: int = 22
    jump_host: str | None = None
    jump_port: int = 22
    jump_username: str = "root"
