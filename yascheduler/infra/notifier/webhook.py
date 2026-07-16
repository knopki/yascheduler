"""Webhook event handler and outbound payload DTO — sends HTTP notifications for task lifecycle events."""
# region MODULE_CONTRACT
# PURPOSE: Notify external systems (CI pipelines, monitoring) about task lifecycle events asynchronously so operators react to completions and failures without the orchestrator blocking on outbound HTTP.
# SCOPE: Webhook event dispatch with backoff retries and concurrency throttling; outbound payload DTO.
# DEPENDENCIES: USES API: aiohttp.ClientSession, USES API: backoff.on_exception, WRITES: HTTP POST via aiohttp
# KEYWORDS: webhook, handler, notification, http, event
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from asyncio.locks import Semaphore
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import aiohttp
import backoff

from yascheduler.domain import (
    DomainEvent,
    TaskAllocated,
    TaskCreated,
    TaskStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "WebhookPayload",
    "webhook_handler",
]


@dataclass(frozen=True)
class WebhookPayload:
    """Payload dataclass for webhook event dispatch."""

    task_id: int = field()
    status: int = field()
    custom_params: Mapping[str, Any] = field(default_factory=dict)


# region FUNC__get_semaphore
# PURPOSE: Limit concurrent outbound webhook requests process-wide so the event loop is not saturated by parallel HTTP deliveries.
@lru_cache(maxsize=1)
def _get_semaphore() -> Semaphore:
    """Return the process-wide webhook concurrency semaphore (lazy-init).

    Created lazily on first call so it binds to the running event loop.
    """
    return Semaphore(10)


# endregion FUNC__get_semaphore


# region FUNC_webhook_handler
# PURPOSE: Deliver task lifecycle notifications to registered webhook URLs so external systems react asynchronously — backoff retries transient failures, and final errors are logged without crashing the dispatcher.
async def webhook_handler(event: DomainEvent, http: aiohttp.ClientSession) -> None:
    """Async handler that sends webhooks for task lifecycle events."""
    if event.webhook_url is None:
        return

    if isinstance(event, TaskCreated):
        status = TaskStatus.TO_DO
    elif isinstance(event, TaskAllocated):
        status = TaskStatus.RUNNING
    else:
        status = TaskStatus.DONE

    payload = WebhookPayload(
        task_id=event.task_id.value,
        status=status.value,
        custom_params=event.webhook_custom_params,
    )
    try:
        await _send_webhook(event.webhook_url, payload, http)
    except aiohttp.ClientError:
        logger.exception("webhook giveup: %s", event.webhook_url)


# endregion FUNC_webhook_handler


# region FUNC__send_webhook
# PURPOSE: POST the webhook payload with exponential backoff and concurrency throttling so transient network failures are retried automatically without overwhelming the target.
@backoff.on_exception(backoff.fibo, aiohttp.ClientError, max_time=60)
async def _send_webhook(
    url: str,
    payload: WebhookPayload,
    http: aiohttp.ClientSession,
) -> None:
    async with _get_semaphore():
        try:
            async with http.post(url, data=asdict(payload)) as resp:
                if resp.ok:
                    return
                # Raised inside the try so the except below logs every retry
                # for BOTH error sources (network failure and HTTP status).
                msg = f"HTTP {resp.status}: {await resp.text()}"
                raise aiohttp.ClientError(msg)  # noqa: TRY301
        except aiohttp.ClientError:
            logger.debug("RETRY", extra={"url": url})
            logger.warning("webhook retry to %s", url)
            raise


# endregion FUNC__send_webhook
