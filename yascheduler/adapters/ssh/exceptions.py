# FILE: yascheduler/adapters/ssh/exceptions.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Public SSH retry exception types for adapters/ssh/ consumers.
#   SCOPE: Re-exports of SSHRetryExc, SFTPRetryExc, AllSSHRetryExc from platform protocol.
#   DEPENDS: M-PLATFORM-PROTOCOL
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   SSHRetryExc - Tuple of retriable SSH exception types
#   SFTPRetryExc - Tuple of retriable SFTP exception types
#   AllSSHRetryExc - Union of SSHRetryExc and SFTPRetryExc
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from remote_machine/protocol.py; re-exports from platform/protocol.
# END_CHANGE_SUMMARY

"""SSH retry exception types — public façade for adapters/ssh/ consumers."""

from .platform.protocol import (
    AllSSHRetryExc,
    SFTPRetryExc,
    SSHRetryExc,
)

__all__ = [
    "AllSSHRetryExc",
    "SFTPRetryExc",
    "SSHRetryExc",
]
