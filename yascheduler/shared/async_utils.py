# FILE: yascheduler/shared/async_utils.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Async-to-sync runtime bridge.
#   SCOPE: to_sync decorator.
#   DEPENDS: none
#   LINKS: M-SHARED
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   to_sync - Decorator wrapping async functions for sync execution
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial extraction from yascheduler/client.py.
# END_CHANGE_SUMMARY

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
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
