# FILE: yascheduler/infra/cloud/protocols.py
# VERSION: 1.3.0
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
#   LAST_CHANGE: v1.3.0 - Delete PCloudConfig Protocol (single-implementer, zero runtime dispatch; collapsed into concrete CloudInitConfig) and CloudCapacity dataclass (dead code; last consumer removed in archived cloud-provisioner-pure); retype CreateNodeCallable.__call__ cloud_config param Optional[PCloudConfig] → Optional[CloudInitConfig] (cloud-init-rename-and-prune / D2+D3).
#   PREVIOUS_CHANGE: v1.2.0 - Import ConfigCloud from .cloud_configs (intra-package) instead of yascheduler.config (cloud-configs-to-infra-registry); removes the only runtime `infra -> yascheduler.config` edge in the cloud subpackage, shrinking the outside-layer-set exemption surface by one edge.
# END_CHANGE_SUMMARY

"""Cloud protocols"""

import logging
from abc import abstractmethod
from collections.abc import Callable
from typing import Optional, Protocol, TypeVar

from asyncssh.public_key import SSHKey

from .cloud_configs import ConfigCloud
from .cloud_init import CloudInitConfig

SupportedPlatformChecker = Callable[[str], bool]

TConfigCloud_inv = TypeVar("TConfigCloud_inv", bound=ConfigCloud)
TConfigCloud_co = TypeVar("TConfigCloud_co", bound=ConfigCloud, covariant=True)
TConfigCloud_contra = TypeVar(
    "TConfigCloud_contra", bound=ConfigCloud, contravariant=True
)


class CreateNodeCallable(Protocol[TConfigCloud_contra]):
    "Create node in the cloud protocol"

    @abstractmethod
    async def __call__(
        self,
        log: logging.Logger,
        cfg: TConfigCloud_contra,
        key: SSHKey,
        cloud_config: Optional[CloudInitConfig] = None,
    ) -> str:
        raise NotImplementedError


class DeleteNodeCallable(Protocol[TConfigCloud_contra]):
    "Delete node in the cloud protocol"

    @abstractmethod
    async def __call__(
        self,
        log: logging.Logger,
        cfg: TConfigCloud_contra,
        host: str,
    ) -> None:
        raise NotImplementedError
