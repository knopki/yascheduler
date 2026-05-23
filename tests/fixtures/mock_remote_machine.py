# FILE: tests/fixtures/mock_remote_machine.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Mock RemoteMachine factory for scheduler and repository unit tests.
#   SCOPE: make_mock_remote_machine helper returning MagicMock(spec=RemoteMachine) with configurable meta, platforms, hostname.
#   DEPENDS: M-REMOTE
#   LINKS: M-REMOTE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_mock_remote_machine - Create a mock RemoteMachine with configured busy state, platforms, and hostname
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial mock RemoteMachine fixture.
# END_CHANGE_SUMMARY
#

from unittest.mock import MagicMock

from yascheduler.remote_machine.remote_machine import (
    RemoteMachine,
    RemoteMachineMetadata,
)


def make_mock_remote_machine(ip, platforms, busy=None, hostname=None):
    meta = RemoteMachineMetadata()
    if busy is True:
        meta.busy = True
    elif busy is False:
        meta.busy = False

    mock = MagicMock(spec=RemoteMachine)
    mock.meta = meta
    mock.platforms = platforms
    mock.hostname = hostname if hostname is not None else ip
    return mock
