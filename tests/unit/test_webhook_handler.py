# region MODULE_CONTRACT
# PURPOSE: Tests for the webhook notification handler.
# SCOPE: Unit tests for webhook_handler event dispatch, _send_webhook, and WebhookPayload construction.
# KEYWORDS: webhook handler, _send_webhook, WebhookPayload
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import datetime as _datetime
import logging
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import backoff._async as _backoff_async
import pytest

from tests.log_assertions import extra_fields
from yascheduler.domain.events import (
    DomainEvent,
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
from yascheduler.domain.model import NodeId, TaskId, TaskStatus
from yascheduler.infra.notifier.webhook import WebhookPayload, webhook_handler

URL = "https://example.com/hook"


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    real_now = _datetime.datetime.now
    calls = {"n": 0}

    class _FastDateTime:
        @staticmethod
        def now(*args: object, **kwargs: object) -> _datetime.datetime:
            calls["n"] += 1
            base = real_now()
            if calls["n"] > 2:
                return base + _datetime.timedelta(seconds=120)
            return base

    monkeypatch.setattr(
        _backoff_async,
        "datetime",
        types.SimpleNamespace(datetime=_FastDateTime),
    )


async def _call(event: DomainEvent) -> AsyncMock:
    http = AsyncMock()
    await webhook_handler(event, http)
    return http


@pytest.mark.parametrize(
    "event_cls,extra_kw,expected_status",
    [
        (TaskCreated, {"engine_name": "fleur"}, TaskStatus.TO_DO),
        (
            TaskAllocated,
            {"node_id": NodeId(7), "engine_name": "fleur"},
            TaskStatus.RUNNING,
        ),
        (
            TaskCompleted,
            {"local_folder": "/tmp/out"},
            TaskStatus.DONE,
        ),
        (TaskFailed, {"reason": "oops"}, TaskStatus.DONE),
        (TaskAbandoned, {"node_id": NodeId(7)}, TaskStatus.DONE),
    ],
    ids=["created", "allocated", "completed", "failed", "abandoned"],
)
async def test_event_dispatches_correct_status(
    event_cls: type[DomainEvent],
    extra_kw: dict[str, Any],
    expected_status: TaskStatus,
) -> None:
    event = event_cls(
        task_id=TaskId(42),
        webhook_url=URL,
        webhook_custom_params={},
        **extra_kw,
    )
    with patch(
        "yascheduler.infra.notifier.webhook._send_webhook",
        new_callable=AsyncMock,
    ) as mock_send:
        await webhook_handler(event, AsyncMock())

    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    sent_url = call_args[0][0]
    sent_payload = call_args[0][1]
    assert sent_url == URL
    assert isinstance(sent_payload, WebhookPayload)
    assert sent_payload.task_id == 42
    assert sent_payload.status == expected_status.value


async def test_skip_when_no_webhook_url() -> None:
    event = TaskCreated(
        task_id=TaskId(1),
        webhook_url=None,
        webhook_custom_params={},
        engine_name="fleur",
    )
    with patch(
        "yascheduler.infra.notifier.webhook._send_webhook",
        new_callable=AsyncMock,
    ) as mock_send:
        await webhook_handler(event, AsyncMock())
    mock_send.assert_not_awaited()


async def test_custom_params_forwarded() -> None:
    params: dict[str, object] = {"key": "val", "n": 42}
    event = TaskCreated(
        task_id=TaskId(7),
        webhook_url=URL,
        webhook_custom_params=params,
        engine_name="fleur",
    )
    with patch(
        "yascheduler.infra.notifier.webhook._send_webhook",
        new_callable=AsyncMock,
    ) as mock_send:
        await webhook_handler(event, AsyncMock())

    sent_payload = mock_send.call_args[0][1]
    assert sent_payload.custom_params == params


async def test_send_error_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    event = TaskCreated(
        task_id=TaskId(99),
        webhook_url=URL,
        webhook_custom_params={},
        engine_name="fleur",
    )
    resp = AsyncMock()
    resp.ok = False
    resp.status = 500
    resp.text = AsyncMock(return_value="Internal Server Error")
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    http = MagicMock()
    http.post.return_value = cm

    with caplog.at_level(logging.DEBUG):
        await webhook_handler(event, http)
    assert any(
        r.getMessage() == "RETRY" and extra_fields(r).get("url") == URL
        for r in caplog.records
    )


async def test_send_webhook_retries_on_client_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from yascheduler.infra.notifier.webhook import _send_webhook

    payload = WebhookPayload(task_id=88, status=0, custom_params={})
    call_count = 0

    def _post_side_effect(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise aiohttp.ClientError("connection failed")
        resp = AsyncMock()
        resp.ok = True
        resp.text = AsyncMock(return_value="OK")
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    http = MagicMock()
    http.post.side_effect = _post_side_effect

    with caplog.at_level(logging.DEBUG):
        await _send_webhook(URL, payload, http)

    assert call_count == 2


class TestWebhookPayload:
    """Tests for WebhookPayload dataclass (relocated from tests/unit/test_scheduler.py)."""

    def test_webhookpayload_construction(self) -> None:
        payload = WebhookPayload(task_id=1, status=0, custom_params={"k": "v"})
        assert payload.task_id == 1
        assert payload.status == 0
        assert payload.custom_params == {"k": "v"}

    def test_webhookpayload_default_custom_params(self) -> None:
        payload = WebhookPayload(task_id=42, status=1)
        assert payload.custom_params == {}
