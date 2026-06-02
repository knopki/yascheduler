# FILE: tests/fixtures/mock_clouds.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Mock CloudProvisionerImpl factory with configurable capacity for scheduler unit tests.
#   SCOPE: make_mock_clouds helper returning MagicMock with stubbed allocate, deallocate, get_capacity, mark_task_done, configs, stop.
#   DEPENDS: M-CLOUD-PROVISIONER
#   LINKS: M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_mock_clouds - Create a mock CloudProvisionerImpl with configurable max/current cloud capacity
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Update to mock CloudProvisionerImpl interface (Phase 4 wiring).
#   PREVIOUS_CHANGE: v1.0.0 - Initial mock CloudAPIManager fixture.
# END_CHANGE_SUMMARY
#

from unittest.mock import AsyncMock, MagicMock

from yascheduler.adapters.cloud.protocols import CloudCapacity


def make_mock_clouds(max_nodes: int = 10, current_nodes: int = 5) -> MagicMock:
    """Create a mock CloudProvisionerImpl with stubbed cloud API methods.

    Returns a MagicMock with the following attributes:
        allocate - AsyncMock returning None
        deallocate - AsyncMock returning None
        get_capacity - AsyncMock returning dict with CloudCapacity
        mark_task_done - MagicMock (synchronous)
        configs - MagicMock whose .values() returns config dicts with max_nodes
        stop - AsyncMock returning None
    """
    mock = MagicMock(spec=None)

    mock.allocate = AsyncMock(return_value=None)
    mock.deallocate = AsyncMock(return_value=None)
    mock.get_capacity = AsyncMock(
        return_value={
            "provider": CloudCapacity(
                name="provider", max=max_nodes, current=current_nodes
            )
        }
    )
    mock.mark_task_done = MagicMock()
    mock.stop = AsyncMock(return_value=None)

    mock_config = MagicMock()
    mock_config.max_nodes = max_nodes
    mock.configs = MagicMock()
    mock.configs.values.return_value = [mock_config]

    return mock
