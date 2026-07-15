# FILE: yascheduler/infra/notifier/webhook.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Webhook event handler and outbound payload DTO — sends HTTP notifications for task lifecycle events.
#   SCOPE: WebhookPayload frozen dataclass, webhook_handler async function, _send_webhook retry helper.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
#   LINKS: M-DOMAIN-EVENTS, M-NOTIFIER-WEBHOOK
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   webhook_handler - Async handler that sends webhooks for task lifecycle events
#   _send_webhook - Send webhook payload via HTTP POST with retry and rate limiting
#   WebhookPayload - Webhook request data shape
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY

#   LAST_CHANGE: v1.3.0 - Migrate logger binding from get_logger("M-...") to logging.getLogger(__name__); trace() → debug(msg, extra=...)
#   PREVIOUS_CHANGE: v1.4.0 - Rewrite GIVEUP exception to pure narrative (no grace marker) per reform-grace-logging slice 7.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from asyncio.locks import Semaphore
from dataclasses import asdict, dataclass, field
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

_webhook_sem: Semaphore | None = None


@dataclass(frozen=True)
class WebhookPayload:
    task_id: int = field()
    status: int = field()
    custom_params: Mapping[str, Any] = field(default_factory=dict)


# START_CONTRACT: webhook_handler
#   PURPOSE: Async handler that sends webhooks for task lifecycle events.
#   INPUTS: { event: DomainEvent - domain event (event.task_id is a TaskId) with optional webhook_url, http: aiohttp.ClientSession }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Sends HTTP POST via _send_webhook (body built via asdict(WebhookPayload(task_id=event.task_id.value, ...))); suppresses final errors after backoff exhausts.
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL
# END_CONTRACT: webhook_handler
def _get_semaphore() -> Semaphore:
    global _webhook_sem
    if _webhook_sem is None:
        _webhook_sem = Semaphore(10)
    return _webhook_sem


async def webhook_handler(event: DomainEvent, http: aiohttp.ClientSession) -> None:
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


# START_CONTRACT: _send_webhook
#   PURPOSE: Send webhook payload via HTTP POST with retry and rate limiting.
#   INPUTS: { url: str, payload: WebhookPayload, http: aiohttp.ClientSession }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Sends HTTP POST to url; logs warning on non-ok response.
#   RAISES: aiohttp.ClientError — propagated for backoff retry.
#   LINKS: M-NOTIFIER-WEBHOOK
# END_CONTRACT: _send_webhook
@backoff.on_exception(backoff.fibo, aiohttp.ClientError, max_time=60)
async def _send_webhook(
    url: str, payload: WebhookPayload, http: aiohttp.ClientSession
) -> None:
    async with _get_semaphore():
        try:
            async with http.post(url, data=asdict(payload)) as resp:
                if resp.ok:
                    return
                raise aiohttp.ClientError(f"HTTP {resp.status}: {await resp.text()}")
        except aiohttp.ClientError:
            logger.debug("RETRY", extra={"url": url})
            logger.warning("webhook retry to %s", url)
            raise
