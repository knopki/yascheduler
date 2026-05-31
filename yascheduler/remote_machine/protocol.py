# FILE: yascheduler/remote_machine/protocol.py
# VERSION: 1.7.0
# START_MODULE_CONTRACT
#   PURPOSE: Backward-compatible re-exports from adapters.ssh.platform.protocol.
#   SCOPE: Re-exports only.
#   DEPENDS: M-PLATFORM-PROTOCOL
#   LINKS: M-PLATFORM-PROTOCOL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Re-exports - Backward-compatible re-exports from adapters.ssh.platform
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Converted to re-export shim; imports from adapters.ssh.platform.
# END_CHANGE_SUMMARY
from yascheduler.adapters.ssh.platform.protocol import *  # noqa: F401,F403
