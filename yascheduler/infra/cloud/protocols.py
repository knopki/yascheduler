# FILE: yascheduler/infra/cloud/protocols.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Protocol definitions for cloud config, node creation, deletion callables.
#   SCOPE: PCloudConfig, CreateNodeCallable, DeleteNodeCallable, SupportedPlatformChecker, CloudCapacity, TypeVars.
#   DEPENDS: M-CLOUD-CONFIGS
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS, M-CLOUD-CONFIGS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   PCloudConfig - Cloud config init protocol
#   CreateNodeCallable - Create node in the cloud protocol
#   DeleteNodeCallable - Delete node in the cloud protocol
#   CloudCapacity - Cloud capacity dataclass
#   SupportedPlatformChecker - platform name validator
#   TConfigCloud_inv - contravariant cloud config TypeVar
#   TConfigCloud_co - covariant cloud config TypeVar
#   TConfigCloud_contra - contravariant cloud config TypeVar
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Import ConfigCloud from .cloud_configs (intra-package) instead of yascheduler.config (cloud-configs-to-infra-registry); removes the only runtime `infra -> yascheduler.config` edge in the cloud subpackage, shrinking the outside-layer-set exemption surface by one edge.
#   PREVIOUS_CHANGE: v1.1.0 - Migrate CloudCapacity from attrs.define(frozen=True) to dataclasses.dataclass(frozen=True); remove stale `from attr import define` typo import (migrate-cloud-from-attrs).
# END_CHANGE_SUMMARY

"""Cloud protocols"""

import logging
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional, Protocol, TypeVar, Union

from asyncssh.public_key import SSHKey

from .cloud_configs import ConfigCloud

SupportedPlatformChecker = Callable[[str], bool]

TConfigCloud_inv = TypeVar("TConfigCloud_inv", bound=ConfigCloud)
TConfigCloud_co = TypeVar("TConfigCloud_co", bound=ConfigCloud, covariant=True)
TConfigCloud_contra = TypeVar(
    "TConfigCloud_contra", bound=ConfigCloud, contravariant=True
)


# FIXME: is this really needed? how many consumers?
class PCloudConfig(Protocol):
    "Cloud config init protocol"

    bootcmd: tuple[Union[str, list[str]], ...]
    package_upgrade: bool
    packages: list[str]

    @abstractmethod
    def render(self) -> str:
        "Render config to string"
        raise NotImplementedError

    @abstractmethod
    def render_base64(self) -> str:
        "Render to user-data format as base64 string"


class CreateNodeCallable(Protocol[TConfigCloud_contra]):
    "Create node in the cloud protocol"

    @abstractmethod
    async def __call__(
        self,
        log: logging.Logger,
        cfg: TConfigCloud_contra,
        key: SSHKey,
        cloud_config: Optional[PCloudConfig] = None,
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


# FIXME: dead code?
@dataclass(frozen=True)
class CloudCapacity:
    "Cloud capacity object"

    name: str
    max: int
    current: int
