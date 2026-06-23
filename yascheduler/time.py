# FILE: yascheduler/time.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Sleep utilities for sync and async contexts.
#   SCOPE: Timestamp utility functions.
#   DEPENDS: none
#   LINKS: none
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   sleep_until - Sleep until a given datetime
#   asleep_until - Async sleep until a given datetime
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
# FIXME: move this module to application (?)
"""Time utils"""

import asyncio
from datetime import datetime
from time import sleep


# FIXME: dead code?
def sleep_until(end: datetime) -> None:
    "Sleep until :end:"
    now = datetime.now()
    if now >= end:
        return
    sleep((end - now).total_seconds())


async def asleep_until(end: datetime) -> None:
    "Sleep until :end:"
    now = datetime.now()
    if now >= end:
        return
    await asyncio.sleep((end - now).total_seconds())
