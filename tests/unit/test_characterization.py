# FILE: tests/unit/test_characterization.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Characterization tests — verify Yascheduler client queue-submit behaviour.
#   SCOPE: Client.queue_submit_task_async uses CLIDeps via make_cli_deps.
#   DEPENDS: M-CLIENT, M-DI
#   LINKS: M-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestClientQueueSubmitTaskAsync - Client.queue_submit_task_async uses CLIDeps, no Scheduler
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Drop Scheduler.* characterization classes after scheduler.py deletion; retain Client queue-submit coverage.
#   PREVIOUS_CHANGE: v1.0.0 - Initial characterization tests for v2.0.0 refactoring.
# END_CHANGE_SUMMARY

"""Characterization tests: verify Client.queue_submit_task_async delegates to make_cli_deps."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestClientQueueSubmitTaskAsync:
    """Client.queue_submit_task_async uses CLIDeps (no Scheduler import)."""

    @pytest.mark.asyncio
    @patch("yascheduler.client.Config.from_config_parser")
    @patch("yascheduler.di.make_cli_deps")
    async def test_queue_submit_task_async_uses_cli_deps(
        self,
        mock_make_cli_deps: MagicMock,
        mock_from_cfg: MagicMock,
    ) -> None:
        """queue_submit_task_async calls deps.submit() via make_cli_deps, not Scheduler."""
        from yascheduler.client import Yascheduler

        # Arrange
        mock_deps = MagicMock()
        mock_deps.submit = AsyncMock(return_value=99)
        mock_make_cli_deps.return_value = mock_deps
        mock_from_cfg.return_value = MagicMock()

        client = Yascheduler()

        # Act
        result = await client.queue_submit_task_async(
            label="test-job",
            metadata={"key": "val"},
            engine_name="fleur",
        )

        # Assert
        assert result == 99
        mock_make_cli_deps.assert_called_once_with(client.config)
        mock_deps.submit.assert_awaited_once_with("test-job", {"key": "val"}, "fleur")
