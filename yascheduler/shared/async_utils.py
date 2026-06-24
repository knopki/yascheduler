# FILE: yascheduler/shared/async_utils.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Async runtime bridges.
#   SCOPE: to_sync decorator, asleep_until helper.
#   DEPENDS: none
#   LINKS: M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   to_sync - Decorator wrapping async functions for sync execution
#   asleep_until - Async sleep until a given datetime
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Gained asleep_until relocated from yascheduler/time.py.
#   PREVIOUS_CHANGE: v1.6.0 - Initial extraction from yascheduler/client.py.
# END_CHANGE_SUMMARY

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import wraps
from typing import Any, TypeVar

from .compat import ParamSpec

ReturnT_co = TypeVar("ReturnT_co", covariant=True)
ParamT = ParamSpec("ParamT")


# START_CONTRACT: to_sync
#   PURPOSE: Wrap an async function so it can be called synchronously, detecting a running event loop and offloading to a worker thread when necessary.
#   INPUTS: { func: Callable[ParamT, Coroutine[Any, Any, ReturnT_co]] - async function to wrap }
#   OUTPUTS: { Callable[ParamT, ReturnT_co] - sync callable preserving the wrapped signature }
#   SIDE_EFFECTS: May spawn a ThreadPoolExecutor and call asyncio.run in a worker thread when a running event loop is detected.
#   LINKS: M-SHARED
# END_CONTRACT: to_sync
def to_sync(
    func: Callable[ParamT, Coroutine[Any, Any, ReturnT_co]],
) -> Callable[ParamT, ReturnT_co]:
    """
    Wraps async function and run it sync in thread.
    """

    @wraps(func)
    def outer(*args: ParamT.args, **kwargs: ParamT.kwargs):  # noqa: ANN202
        """
        Execute the async method synchronously in sync and async runtime.
        """
        coro = func(*args, **kwargs)
        try:
            asyncio.get_running_loop()  # Triggers RuntimeError if no running event loop

            # Create a separate thread so we can block before returning
            with ThreadPoolExecutor(1) as pool:
                return pool.submit(lambda: asyncio.run(coro)).result()
        except RuntimeError:
            return asyncio.run(coro)

    return outer


# START_CONTRACT: asleep_until
#   PURPOSE: Sleep until a given datetime asynchronously.
#   INPUTS: { end: datetime - target time to sleep until }
#   OUTPUTS: { None - no return value }
#   SIDE_EFFECTS: Awaits asyncio.sleep for the remaining interval; returns immediately if now >= end.
#   LINKS: M-SHARED
# END_CONTRACT: asleep_until
async def asleep_until(end: datetime) -> None:
    "Sleep until :end:"
    now = datetime.now()
    if now >= end:
        return
    await asyncio.sleep((end - now).total_seconds())
