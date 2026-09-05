"""Cloud protocols."""
# region MODULE_CONTRACT
# PURPOSE: Define typed callable contracts for node create/delete so provider implementations are type-checked against a standard interface and the adapter layer stays provider-agnostic.
# SCOPE: CreateNodeCallable, DeleteNodeCallable, SupportedPlatformChecker, TypeVars.
# KEYWORDS: protocol, callable, create node, delete node, typevar, platform checker
# endregion MODULE_CONTRACT

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, TypeVar

from .cloud_configs import ConfigCloud

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey

    from .cloud_init import CloudInitConfig
    from .dto import CloudCreateNodeDTO

__all__ = [
    "CreateNodeCallable",
    "DeleteNodeCallable",
    "SupportedPlatformChecker",
    "TConfigCloud_co",
    "TConfigCloud_contra",
]

SupportedPlatformChecker = Callable[[str], bool]

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
    ) -> CloudCreateNodeDTO:
        """Call."""
        raise NotImplementedError


class DeleteNodeCallable(Protocol[TConfigCloud_contra]):
    """Delete node in the cloud protocol."""

    @abstractmethod
    async def __call__(
        self,
        cfg: TConfigCloud_contra,
        external_id: str,
    ) -> None:
        """Call."""
        raise NotImplementedError
