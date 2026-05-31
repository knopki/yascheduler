# FILE: yascheduler/remote_machine/linux_methods.py
# VERSION: 1.7.0
# START_MODULE_CONTRACT
#   PURPOSE: Backward-compatible re-exports from adapters.ssh.platform.linux.
#   SCOPE: Re-exports only.
#   DEPENDS: M-PLATFORM-LINUX
#   LINKS: M-PLATFORM-LINUX
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Re-exports - Backward-compatible re-exports from adapters.ssh.platform
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Converted to re-export shim; imports from adapters.ssh.platform.
# END_CHANGE_SUMMARY
from yascheduler.adapters.ssh.platform.linux import *  # noqa: F401,F403
