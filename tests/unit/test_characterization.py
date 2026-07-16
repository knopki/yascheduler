"""Characterization tests: verify Client.queue_submit_task_async delegates to deps.submit via deps_factory."""
# region MODULE_CONTRACT
# PURPOSE: Characterization tests — verify Yascheduler client queue-submit behaviour.
# SCOPE: Client.queue_submit_task_async delegation via deps_factory seam.
# KEYWORDS: client queue, submit, deps_factory
# endregion MODULE_CONTRACT

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.domain import TaskId


class TestClientQueueSubmitTaskAsync:
    """Client.queue_submit_task_async delegates to deps.submit via the deps_factory seam."""

    @pytest.mark.asyncio
    @patch("yascheduler.entrypoints.client.parse_config")
    async def test_queue_submit_task_async_uses_cli_deps(
        self,
        mock_from_cfg: MagicMock,
    ) -> None:
        """queue_submit_task_async calls deps.submit() via the injected deps_factory, not Scheduler."""
        from yascheduler.entrypoints.client import Yascheduler

        # Arrange — inject fake deps via the constructor seam.
        # deps.submit returns TaskId; the facade extracts .value → public int contract.
        mock_deps = MagicMock()
        mock_deps.submit = AsyncMock(return_value=TaskId(99))
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
