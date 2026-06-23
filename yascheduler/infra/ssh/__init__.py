# FILE: yascheduler/infra/ssh/__init__.py
# VERSION: 1.1.1
# START_MODULE_CONTRACT
#   PURPOSE: SSH adapter package root — re-exports gateway class and retry exceptions.
#   SCOPE: Package marker; public re-exports of SSHMachineGateway, AllSSHRetryExc, SFTPRetryExc.
#   DEPENDS: M-SSH-GATEWAY, M-SSH-EXCEPTIONS
#   LINKS: M-SSH-GATEWAY, M-SSH-EXCEPTIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SSHMachineGateway - SSH implementation of MachineGateway protocol
#   AllSSHRetryExc - Union of all retryable SSH exceptions
#   SFTPRetryExc - Tuple of retriable SFTP exception types
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.1.0 - Expose SSHMachineGateway and retry exceptions as public surface (clean-architecture-imports R2 enforcement).
# END_CHANGE_SUMMARY

from .exceptions import AllSSHRetryExc, SFTPRetryExc
from .gateway import SSHMachineGateway

__all__ = [
    "AllSSHRetryExc",
    "SFTPRetryExc",
    "SSHMachineGateway",
]
