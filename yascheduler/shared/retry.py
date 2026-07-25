"""Internal async retry utility with exponential backoff."""
# region MODULE_CONTRACT
# PURPOSE: Provide an internal async retry with backoff utility.
# SCOPE: Decorator, partial, and direct-call forms with exponential backoff.
# INVATIOANTS: Async-only, no third-party dependencies.
# KEYWORDS: retry, exponential backoff, async, retry utility
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, TypeVar

from yascheduler.shared.compat import ParamSpec

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

__all__ = ["retry"]

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


# region FUNC_retry
# PURPOSE: Provide an async retry with backoff decorator.
def retry(
    *,
    on: type[Exception] | tuple[type[Exception], ...],
    max_time: float = 60,
    giveup: Callable[[Exception], bool] | None = None,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    factor: float = 1.5,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Coroutine[None, None, R]]]:
    """Return a decorator that retries an async function with exponential backoff.

    Args:
        on: Exception type(s) that trigger a retry.
        max_time: Maximum total wall-clock time in seconds before giving up.
        giveup: Optional predicate; if it returns True the exception propagates immediately.
        initial_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay cap in seconds.
        factor: Multiplicative factor for exponential backoff.

    """

    def decorator(
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Coroutine[None, None, R]]:
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            deadline = asyncio.get_running_loop().time() + max_time
            delay = initial_delay

            while True:
                try:
                    return await func(*args, **kwargs)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not isinstance(exc, on):
                        raise
                    if giveup is not None and giveup(exc):
                        logger.debug("GIVEUP", extra={"exc": str(exc)})
                        raise
                    if asyncio.get_running_loop().time() >= deadline:
                        logger.debug("DEADLINE", extra={"exc": str(exc)})
                        raise
                    logger.debug("RETRY", extra={"exc": str(exc), "delay": delay})
                await asyncio.sleep(delay)
                delay = min(delay * factor, max_delay)

        return wrapper

    return decorator


# endregion FUNC_retry
