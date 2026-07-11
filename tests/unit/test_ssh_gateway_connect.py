# FILE: tests/unit/test_ssh_gateway_connect.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineRepository.connect two-method pattern and error translation.
#   SCOPE: Transaction of asyncssh.misc.Error → MachineConnectionError,
#     OSError → MachineConnectionError, and successful return of a MachineSession.
#   DEPENDS: M-SSH-REPOSITORY, M-DOMAIN-EXCEPTIONS, M-SSH-SESSION
#   LINKS: M-SSH-REPOSITORY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_connect_translates_asyncssh_error - asyncssh.misc.Error → MachineConnectionError with ip and cause
#   test_connect_translates_oserror - OSError → MachineConnectionError with ip
#   test_connect_returns_session_on_success - Successful connect returns MachineSession
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - node-rename-and-fields: Node(hostname=…)→Node(hostname=…), exc.ip→exc.hostname, _make_state(ip=…)→_make_state(hostname=…), result.hostname→result.hostname.
#   PREVIOUS_CHANGE: v1.2.0 - simplify-cloud-connect-node-args: the three `gw.connect(node, "root", None)` calls drop the `"root"` username arg; client_keys (`None`) shifts to the 2nd positional slot.
#   PREVIOUS_CHANGE: v1.1.0 - session-based-machine-handle: connect returns MachineSession (was ConnectedMachine).
# END_CHANGE_SUMMARY

from unittest.mock import AsyncMock

import asyncssh
import pytest

from tests.unit.test_ssh_gateway import _make_state
from yascheduler.domain.exceptions import MachineConnectionError
from yascheduler.domain.model import Node, NodeId
from yascheduler.infra.ssh.repository import SSHMachineRepository


# START_CONTRACT: test_connect_translates_asyncssh_error
#   PURPOSE: Verify _connect_impl raising asyncssh.misc.Error raises MachineConnectionError with correct ip and cause.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-SSH-REPOSITORY, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: test_connect_translates_asyncssh_error
@pytest.mark.asyncio
async def test_connect_translates_asyncssh_error() -> None:
    gw = SSHMachineRepository()
    err = asyncssh.misc.PermissionDenied("denied")
    gw._connect_impl = AsyncMock(side_effect=err)  # type: ignore[method-assign]
    node = Node(
        node_id=NodeId(1), hostname="10.0.0.1", ncpus=4, username="root", port=22
    )
    with pytest.raises(MachineConnectionError) as exc_info:
        await gw.connect(node, None)
    assert exc_info.value.hostname == "10.0.0.1"
    assert "denied" in exc_info.value.reason
    assert isinstance(exc_info.value.__cause__, asyncssh.misc.Error)


# START_CONTRACT: test_connect_translates_oserror
#   PURPOSE: Verify _connect_impl raising OSError raises MachineConnectionError with ip.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-SSH-REPOSITORY, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: test_connect_translates_oserror
@pytest.mark.asyncio
async def test_connect_translates_oserror() -> None:
    gw = SSHMachineRepository()
    gw._connect_impl = AsyncMock(side_effect=OSError("refused"))  # type: ignore[method-assign]
    node = Node(
        node_id=NodeId(1), hostname="10.0.0.1", ncpus=4, username="root", port=22
    )
    with pytest.raises(MachineConnectionError) as exc_info:
        await gw.connect(node, None)
    assert exc_info.value.hostname == "10.0.0.1"
    assert "refused" in exc_info.value.reason


# START_CONTRACT: test_connect_returns_session_on_success
#   PURPOSE: Verify connect returns the MachineSession produced by _connect_impl unchanged.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
# END_CONTRACT: test_connect_returns_session_on_success
@pytest.mark.asyncio
async def test_connect_returns_session_on_success() -> None:
    gw = SSHMachineRepository()
    session = _make_state(hostname="10.0.0.1")
    gw._connect_impl = AsyncMock(return_value=session)  # type: ignore[method-assign]
    node = Node(
        node_id=NodeId(1), hostname="10.0.0.1", ncpus=4, username="root", port=22
    )
    result = await gw.connect(node, None)
    assert result is session
    assert result.hostname == "10.0.0.1"
    assert isinstance(result, type(session))
