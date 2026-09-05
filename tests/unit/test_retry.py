# region MODULE_CONTRACT
# PURPOSE: Unit tests for yascheduler.shared.retry retry utility.
# SCOPE: Decorator, partial, and direct-call forms; exception filtering; giveup; max_time deadline.
# KEYWORDS: retry, backoff, exponential backoff, async retry
# endregion MODULE_CONTRACT

import asyncio
from unittest.mock import AsyncMock

import pytest

from yascheduler.shared.retry import retry


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.sleep with a near-instant yield for fast tests."""
    original_sleep = asyncio.sleep

    async def _noop_sleep(delay: float) -> None:
        await original_sleep(0)  # yield control, no real wait

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)


class TestRetryDecorator:
    """Tests for the @retry(...) decorator form."""

    async def test_retries_on_matching_exception(self) -> None:
        """Decorator retries when matching exception is raised."""
        mock_fn = AsyncMock(side_effect=[ValueError("first"), "success"])

        @retry(on=ValueError, max_time=10)
        async def decorated() -> str:
            return await mock_fn()

        result = await decorated()

        assert result == "success"
        assert mock_fn.call_count == 2

    async def test_non_matching_exception_propagates(self) -> None:
        """Non-matching exception propagates immediately without retry."""
        mock_fn = AsyncMock(side_effect=TypeError("wrong type"))

        @retry(on=ValueError, max_time=10)
        async def decorated() -> None:
            await mock_fn()

        with pytest.raises(TypeError, match="wrong type"):
            await decorated()

        assert mock_fn.call_count == 1

    async def test_giveup_stops_retry(self) -> None:
        """giveup returning True propagates exception immediately."""
        mock_fn = AsyncMock(side_effect=ValueError("nope"))

        @retry(on=ValueError, max_time=60, giveup=lambda e: True)
        async def decorated() -> None:
            await mock_fn()

        with pytest.raises(ValueError, match="nope"):
            await decorated()

        assert mock_fn.call_count == 1

    async def test_max_time_deadline_honored(self) -> None:
        """max_time deadline causes last exception to propagate."""
        mock_fn = AsyncMock(side_effect=ValueError("timeout"))

        @retry(on=ValueError, max_time=0.001)
        async def decorated() -> None:
            await mock_fn()

        with pytest.raises(ValueError, match="timeout"):
            await decorated()

        assert mock_fn.call_count >= 1

    async def test_successful_call_returns_result(self) -> None:
        """Successful call after retry returns the result."""
        mock_fn = AsyncMock(side_effect=[ValueError("first"), "done"])

        @retry(on=ValueError, max_time=10)
        async def decorated() -> str:
            return await mock_fn()

        result = await decorated()

        assert result == "done"
        assert mock_fn.call_count == 2


class TestRetryPartial:
    """Tests for the partial form: my_retry = partial(retry, ...) then @my_retry()."""

    async def test_partial_form_works(self) -> None:
        """Partial form behaves identically to direct @retry(...)."""
        from functools import partial

        my_retry = partial(retry, on=ValueError, max_time=10)
        mock_fn = AsyncMock(side_effect=[ValueError("first"), "ok"])

        @my_retry()
        async def decorated() -> str:
            return await mock_fn()

        result = await decorated()

        assert result == "ok"
        assert mock_fn.call_count == 2


class TestRetryDirectCall:
    """Tests for the direct-call form: file_get_retry = my_retry() then await file_get_retry(some_fn)(arg)."""

    async def test_direct_call_form_works(self) -> None:
        """Direct-call form retries the function with the same policy."""
        from functools import partial

        my_retry = partial(retry, on=ValueError, max_time=10)
        file_get_retry = my_retry()
        mock_fn = AsyncMock(side_effect=[ValueError("first"), "result"])

        result = await file_get_retry(mock_fn)()

        assert result == "result"
        assert mock_fn.call_count == 2


class TestRetryEdgeCases:
    """Edge-case tests for the retry utility."""

    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError propagates immediately without retry."""
        mock_fn = AsyncMock(side_effect=asyncio.CancelledError())

        @retry(on=ValueError, max_time=10)
        async def decorated() -> None:
            await mock_fn()

        with pytest.raises(asyncio.CancelledError):
            await decorated()

        assert mock_fn.call_count == 1

    async def test_giveup_returns_false_retries(self) -> None:
        """giveup returning False allows retry."""
        mock_fn = AsyncMock(side_effect=[ValueError("first"), "ok"])

        @retry(on=ValueError, max_time=10, giveup=lambda e: False)
        async def decorated() -> str:
            return await mock_fn()

        result = await decorated()

        assert result == "ok"
        assert mock_fn.call_count == 2

    async def test_on_tuple_of_exceptions(self) -> None:
        """on accepts a tuple of exception types."""
        mock_fn = AsyncMock(side_effect=[TypeError("type"), "ok"])

        @retry(on=(ValueError, TypeError), max_time=10)
        async def decorated() -> str:
            return await mock_fn()

        result = await decorated()

        assert result == "ok"
        assert mock_fn.call_count == 2
