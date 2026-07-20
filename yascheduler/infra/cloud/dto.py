"""Cloud DTOs."""
# region MODULE_CONTRACT
# PURPOSE: Carry cloud-provisioning payloads across the cloud-adapter boundary so provider create/delete functions stay decoupled from the provisioner's Node-mapping logic.
# SCOPE: Bare DTO only.
# KEYWORDS: dto, create node, cloud, data transfer
# endregion MODULE_CONTRACT

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CloudCreateNodeDTO"]


# region CLASS_CloudCreateNodeDTO
# PURPOSE: Carry the cloud-provisioned VM's connection identity from the provider create function to the provisioner so the allocator can stamp the resulting Node without knowing which provider ran.
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


# endregion CLASS_CloudCreateNodeDTO
