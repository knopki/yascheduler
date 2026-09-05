# region MODULE_CONTRACT
# PURPOSE: Unit tests for SSHMachineRepository.connect two-method pattern and error translation.
# SCOPE: Transaction of asyncssh.misc.Error → MachineConnectionError, OSError → MachineConnectionError, and successful return of a MachineSession.
# KEYWORDS: SSHMachineRepository.connect, MachineConnectionError, error translation
# endregion MODULE_CONTRACT

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from tests.unit.test_ssh_gateway import _make_state
from yascheduler.domain.exceptions import MachineConnectionError
from yascheduler.domain.model import Node, NodeId
from yascheduler.infra.ssh.repository import SSHMachineRepository

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
def repository() -> SSHMachineRepository:
    return SSHMachineRepository()


@pytest.fixture
def mock_conn() -> MagicMock:
    """Mock SSHClientConnection with all async methods stubbed."""
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
    conn.run = AsyncMock(return_value=MagicMock())
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()

    sftp_client = AsyncMock()
    sftp_client.put = AsyncMock()
    sftp_client.get = AsyncMock()

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[Any, None]:
        yield sftp_client

    conn.start_sftp_client = _sftp_ctx
    return conn


@pytest.fixture
def mock_adapter() -> MagicMock:
    """Mock RemoteMachineAdapter with callable stubs."""
    adapter = MagicMock()
    adapter.platform = "linux"
    adapter.path = PurePosixPath
    adapter.quote = lambda s: s
    adapter.run = AsyncMock()
    adapter.run_bg = AsyncMock()
    adapter.get_cpu_cores = AsyncMock(return_value=4)
    adapter.list_processes = MagicMock()
    adapter.pgrep = MagicMock()
    adapter.setup_node = AsyncMock()
    return adapter


@pytest.mark.asyncio
async def test_connect_translates_asyncssh_error() -> None:
    gw = SSHMachineRepository()
    err = asyncssh.misc.PermissionDenied("denied")
    gw._connect_impl = AsyncMock(side_effect=err)  # type: ignore[method-assign]
    node = Node(
        node_id=NodeId(1),
        hostname="10.0.0.1",
        ncpus=4,
        username="root",
        port=22,
    )
    with pytest.raises(MachineConnectionError) as exc_info:
        await gw.connect(node, None)
    assert exc_info.value.hostname == "10.0.0.1"
    assert "denied" in exc_info.value.reason
    assert isinstance(exc_info.value.__cause__, asyncssh.misc.Error)


@pytest.mark.asyncio
async def test_connect_translates_oserror() -> None:
    gw = SSHMachineRepository()
    gw._connect_impl = AsyncMock(side_effect=OSError("refused"))  # type: ignore[method-assign]
    node = Node(
        node_id=NodeId(1),
        hostname="10.0.0.1",
        ncpus=4,
        username="root",
        port=22,
    )
    with pytest.raises(MachineConnectionError) as exc_info:
        await gw.connect(node, None)
    assert exc_info.value.hostname == "10.0.0.1"
    assert "refused" in exc_info.value.reason


@pytest.mark.asyncio
async def test_connect_translates_key_import_error() -> None:
    """KeyImportError (ValueError) from a stray .pub in client_keys is translated
    to MachineConnectionError instead of escaping raw past the orchestrator's
    retry/abandon path."""
    gw = SSHMachineRepository()
    gw._connect_impl = AsyncMock(  # type: ignore[method-assign]
        side_effect=asyncssh.public_key.KeyImportError("Invalid private key")
    )
    node = Node(
        node_id=NodeId(1),
        hostname="10.0.0.1",
        ncpus=4,
        username="root",
        port=22,
    )
    with pytest.raises(MachineConnectionError) as exc_info:
        await gw.connect(node, None)
    assert exc_info.value.hostname == "10.0.0.1"
    assert "Invalid private key" in exc_info.value.reason
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_connect_returns_session_on_success() -> None:
    gw = SSHMachineRepository()
    session = _make_state(hostname="10.0.0.1")
    gw._connect_impl = AsyncMock(return_value=session)  # type: ignore[method-assign]
    node = Node(
        node_id=NodeId(1),
        hostname="10.0.0.1",
        ncpus=4,
        username="root",
        port=22,
    )
    result = await gw.connect(node, None)
    assert result is session
    assert result.hostname == "10.0.0.1"
    assert isinstance(result, type(session))


@pytest.mark.asyncio
async def test_connect_primes_session_cache(
    repository: SSHMachineRepository,
    mock_conn: MagicMock,
    mock_adapter: MagicMock,
) -> None:
    """Connect primes the session cache; first get_cpu_cores returns cached value without adapter call."""
    with (
        patch(
            "yascheduler.infra.ssh.repository.asyncssh.connection.connect",
            AsyncMock(return_value=mock_conn),
        ),
        patch(
            "yascheduler.infra.ssh.repository._detect_platform",
            AsyncMock(return_value=(mock_adapter, ["linux", "debian-like"])),
        ),
        patch(
            "yascheduler.infra.ssh.repository._init_paths",
            return_value=(
                PurePosixPath("./data"),
                PurePosixPath("./data/engines"),
                PurePosixPath("./data/tasks"),
            ),
        ),
    ):
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            username="root",
            port=22,
        )
        session = await repository.connect(node=node, client_keys=[])

    adapter_mock = mock_adapter.get_cpu_cores
    result = await session.get_cpu_cores()
    assert result == 4
    adapter_mock.assert_awaited_once()
