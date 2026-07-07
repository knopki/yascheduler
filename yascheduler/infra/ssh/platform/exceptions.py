#!/usr/bin/env python3
# FILE: yascheduler/infra/ssh/platform/exc.py
# VERSION: 1.0.1
#
# START_MODULE_CONTRACT
#   PURPOSE: Custom exceptions for remote machine operations.
#   SCOPE: PlatformGuessFailedError exception.
#   DEPENDS: none
#   LINKS: M-PLATFORM-ADAPTERS, M-PLATFORM-EXC
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   PlatformGuessFailedError - Raised when platform detection from host string fails
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/; no behavioral change.
#   PREVIOUS_CHANGE: v1.0.0 - Initial version.
# END_CHANGE_SUMMARY
#


class PlatformGuessFailedError(Exception):
    pass
