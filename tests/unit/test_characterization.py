# FILE: tests/unit/test_characterization.py
# VERSION: 2.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Characterization tests — verify Yascheduler client queue-submit behaviour.
#   SCOPE: Client.queue_submit_task_async delegates to CLIDeps.submit via the deps_factory seam.
#   DEPENDS: M-CLIENT, M-DI
#   LINKS: M-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestClientQueueSubmitTaskAsync - Client.queue_submit_task_async delegates to deps.submit via deps_factory
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.0 - Switch submit characterization from module-patch of make_cli_deps to the deps_factory constructor seam.
#   PREVIOUS_CHANGE: v2.0.0 - Drop Scheduler.* characterization classes after scheduler.py deletion; retain Client queue-submit coverage.
# END_CHANGE_SUMMARY

"""Characterization tests: verify Client.queue_submit_task_async delegates to deps.submit via deps_factory."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestClientQueueSubmitTaskAsync:
    """Client.queue_submit_task_async delegates to deps.submit via the deps_factory seam."""

    @pytest.mark.asyncio
    @patch("yascheduler.client.Config.from_config_parser")
    async def test_queue_submit_task_async_uses_cli_deps(
        self, mock_from_cfg: MagicMock
    ) -> None:
        """queue_submit_task_async calls deps.submit() via the injected deps_factory, not Scheduler."""
        from yascheduler.client import Yascheduler

        # Arrange — inject fake deps via the constructor seam
        mock_deps = MagicMock()
        mock_deps.submit = AsyncMock(return_value=99)
        factory_calls: list = []
        mock_from_cfg.return_value = MagicMock()

        def counting_factory(cfg: object) -> MagicMock:
            factory_calls.append(cfg)
            return mock_deps

        client = Yascheduler(deps_factory=counting_factory)  # type: ignore[arg-type]

        # Act
        result = await client.queue_submit_task_async(
            label="test-job",
            metadata={"key": "val"},
            engine_name="fleur",
        )

        # Assert
        assert result == 99
        assert factory_calls == [client.config]
        mock_deps.submit.assert_awaited_once_with("test-job", {"key": "val"}, "fleur")
