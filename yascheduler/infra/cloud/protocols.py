"""Cloud protocols."""
# FILE: yascheduler/infra/cloud/protocols.py
# VERSION: 1.4.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Protocol definitions for node creation and deletion callables.
#   SCOPE: CreateNodeCallable, DeleteNodeCallable, SupportedPlatformChecker, TypeVars.
#   DEPENDS: M-CLOUD-CONFIGS, M-CLOUD-INIT
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CLOUD-CONFIGS, M-CLOUD-INIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CreateNodeCallable - Create node in the cloud protocol
#   DeleteNodeCallable - Delete node in the cloud protocol
#   SupportedPlatformChecker - platform name validator
#   TConfigCloud_inv - contravariant cloud config TypeVar
#   TConfigCloud_co - covariant cloud config TypeVar
#   TConfigCloud_contra - contravariant cloud config TypeVar
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.4.0 - remove log parameter from Protocol signatures; bind module-local logger = get_logger("M-CLOUD-PROTOCOLS") at module top
#   PREVIOUS_CHANGE: v1.3.0 - Delete PCloudConfig Protocol (single-implementer, zero runtime dispatch; collapsed into concrete CloudInitConfig) and CloudCapacity dataclass (dead code; last consumer removed); retype CreateNodeCallable.__call__ cloud_config param Optional[PCloudConfig] → Optional[CloudInitConfig].
# END_CHANGE_SUMMARY

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, TypeVar

from .cloud_configs import ConfigCloud

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey

    from .cloud_init import CloudInitConfig

SupportedPlatformChecker = Callable[[str], bool]

TConfigCloud_inv = TypeVar("TConfigCloud_inv", bound=ConfigCloud)
TConfigCloud_co = TypeVar("TConfigCloud_co", bound=ConfigCloud, covariant=True)
TConfigCloud_contra = TypeVar(
    "TConfigCloud_contra",
    bound=ConfigCloud,
    contravariant=True,
)


class CreateNodeCallable(Protocol[TConfigCloud_contra]):
    """Create node in the cloud protocol."""

    @abstractmethod
    async def __call__(
        self,
        cfg: TConfigCloud_contra,
        key: SSHKey,
        cloud_config: CloudInitConfig | None = None,
    ) -> str:
        """Call."""
        raise NotImplementedError


class DeleteNodeCallable(Protocol[TConfigCloud_contra]):
    """Delete node in the cloud protocol."""

    @abstractmethod
    async def __call__(
        self,
        cfg: TConfigCloud_contra,
        host: str,
    ) -> None:
        """Call."""
        raise NotImplementedError
