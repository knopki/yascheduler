#!/usr/bin/env python3
# FILE: yascheduler/remote_machine/exc.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Custom exceptions for remote machine operations.
#   SCOPE: PlatformGuessFailed exception.
#   DEPENDS: none
#   LINKS: M-REMOTE-EXC
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   PlatformGuessFailed - Raised when platform detection from host string fails
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#


class PlatformGuessFailed(Exception):
    pass
