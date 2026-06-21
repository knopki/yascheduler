# FILE: tests/unit/test_ssh_gateway_connect.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineGateway.connect two-method pattern and error translation.
#   SCOPE: Transaction of asyncssh.misc.Error → MachineConnectionError,
#     OSError → MachineConnectionError, and successful return.
#   DEPENDS: M-SSH-GATEWAY, M-DOMAIN-EXCEPTIONS
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_connect_translates_asyncssh_error - asyncssh.misc.Error → MachineConnectionError with ip and cause
#   test_connect_translates_oserror - OSError → MachineConnectionError with ip
#   test_connect_returns_machine_on_success - Successful connect returns ConnectedMachine
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial tests for connect error translation (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from unittest.mock import AsyncMock

import asyncssh
import pytest

from yascheduler.adapters.ssh.gateway import SSHMachineGateway
from yascheduler.domain import ConnectedMachine, MachineState
from yascheduler.domain.exceptions import MachineConnectionError


# START_CONTRACT: test_connect_translates_asyncssh_error
#   PURPOSE: Verify _connect_impl raising asyncssh.misc.Error raises MachineConnectionError with correct ip and cause.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-SSH-GATEWAY, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: test_connect_translates_asyncssh_error
@pytest.mark.asyncio
async def test_connect_translates_asyncssh_error() -> None:
    gw = SSHMachineGateway()
    err = asyncssh.misc.PermissionDenied("denied")
    gw._connect_impl = AsyncMock(side_effect=err)  # type: ignore[method-assign]
    with pytest.raises(MachineConnectionError) as exc_info:
        await gw.connect("10.0.0.1", "root", None)
    assert exc_info.value.ip == "10.0.0.1"
    assert "denied" in exc_info.value.reason
    assert isinstance(exc_info.value.__cause__, asyncssh.misc.Error)


# START_CONTRACT: test_connect_translates_oserror
#   PURPOSE: Verify _connect_impl raising OSError raises MachineConnectionError with ip.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-SSH-GATEWAY, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: test_connect_translates_oserror
@pytest.mark.asyncio
async def test_connect_translates_oserror() -> None:
    gw = SSHMachineGateway()
    gw._connect_impl = AsyncMock(side_effect=OSError("refused"))  # type: ignore[method-assign]
    with pytest.raises(MachineConnectionError) as exc_info:
        await gw.connect("10.0.0.1", "root", None)
    assert exc_info.value.ip == "10.0.0.1"
    assert "refused" in exc_info.value.reason


# START_CONTRACT: test_connect_returns_machine_on_success
#   PURPOSE: Verify connect returns ConnectedMachine unchanged when _connect_impl succeeds.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-SSH-GATEWAY
# END_CONTRACT: test_connect_returns_machine_on_success
@pytest.mark.asyncio
async def test_connect_returns_machine_on_success() -> None:
    gw = SSHMachineGateway()
    machine = ConnectedMachine(
        ip="10.0.0.1",
        platform="linux",
        ncpus=4,
        state=MachineState.FREE,
        free_since=0.0,
    )
    gw._connect_impl = AsyncMock(return_value=machine)  # type: ignore[method-assign]
    result = await gw.connect("10.0.0.1", "root", None)
    assert result is machine
