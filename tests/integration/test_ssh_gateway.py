# FILE: tests/integration/test_ssh_gateway.py
# VERSION: 1.3.2
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for SSHMachineRepository + SSHMachineOperations against a Docker SSH server via testcontainers.
#   SCOPE: Connection lifecycle, command execution, SFTP upload/download, machine state transitions.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-DOMAIN-MODEL
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ssh_container - session-scoped fixture: starts Docker SSH container, generates key pair
#   ssh_container_2 - session-scoped fixture for the second container (multi-machine regression), yields bridge IP + internal port 2222
#   repository - function-scoped fixture: SSHMachineRepository connected to test container
#   operations - function-scoped fixture: SSHMachineOperations from that repository
#   TestSSHGatewayIntegration - connection lifecycle, command exec, SFTP, state transitions
#   TestOccupancyIntegration - occupancy_check via check_pname/check_cmd against real SSH
#   TestOccupancyRaceCondition - regression for ConnectedMachine state sync bug
#   TestMultiMachineBgTaskLeak - real-asyncssh regression: disconnect(A) must not cancel B's monitor
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.2 - Restore TestMultiMachineBgTaskLeak as a working real-asyncssh regression: ssh_container_2 now yields the container bridge IP (from docker SDK NetworkSettings.IPAddress, with a fallback to the first network's IPAddress) plus the internal port 2222, so machine B is reached at a genuinely distinct IP from machine A (localhost). The original variant keyed both testcontainers by 'localhost' and was guaranteed to fail because SSHMachineGateway keys _machines/_bg_tasks by IP only; the YASCHED_MULTI_CONTAINER=1 skip guard was added by mistake and only hid the unavoidable failure. Drops the env-guard entirely.
#   PREVIOUS_CHANGE: v1.3.1 - Remove TestMultiMachineBgTaskLeak and ssh_container_2 fixture: the integration test was architecturally broken on a single Docker host (both testcontainers report host 'localhost', but SSHMachineGateway keys _machines/_bg_tasks by IP only, so the second connect overwrote the first and disconnect cancelled the only surviving monitor). The skip guard YASCHED_MULTI_CONTAINER=1 was added by mistake; enabling it surfaced the unavoidable failure. The unit test test_disconnect_does_not_cancel_other_machines_monitors (three distinct IPs) remains the primary guard for fix-disconnect-bg-task-leak.
#   PREVIOUS_CHANGE: v1.3.0 - Migrate _bg_tasks accesses from list(set) to dict[ip]; add TestMultiMachineBgTaskLeak regression (skipped unless YASCHED_MULTI_CONTAINER=1, since the unit test is the primary guard) for fix-disconnect-bg-task-leak.
#   PREVIOUS_CHANGE: v1.2.1 - Update TestOccupancyRaceCondition for new get_machine_state contract returning ConnectedMachine (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import asyncssh
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from yascheduler.domain import Engine
from yascheduler.domain.model import ConnectedMachine, MachineState
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.repository import SSHMachineRepository

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(scope="session")
async def ssh_container(tmp_path_factory: Any) -> AsyncGenerator[dict[str, Any], None]:  # noqa: ANN401
    """Start Docker SSH container, generate key pair, yield connection info."""
    key_dir = tmp_path_factory.mktemp("ssh_keys")
    key_path = key_dir / "id_rsa"

    key = asyncssh.generate_private_key("ssh-rsa")
    public_key_str = key.export_public_key("openssh").decode().strip()
    key.write_private_key(str(key_path))

    container = DockerContainer("lscr.io/linuxserver/openssh-server:10.2_p1-r0-ls222")
    container.with_env("USER_NAME", "testuser")
    container.with_env("PUBLIC_KEY", public_key_str)
    container.with_exposed_ports(2222)
    container.waiting_for(LogMessageWaitStrategy("sshd is listening"))

    container.start()
    try:
        await asyncio.sleep(1)

        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(2222))

        yield {
            "host": host,
            "port": port,
            "username": "testuser",
            "key_path": PurePosixPath(str(key_path)),
        }
    finally:
        container.stop()


@pytest.fixture(scope="session")
async def ssh_container_2(
    tmp_path_factory: Any,  # noqa: ANN401
) -> AsyncGenerator[dict[str, Any], None]:
    """Start a second Docker SSH container for multi-machine regression tests.

    Yields the bridge-network IP of the container (reachable from the host on
    the Docker/Podman bridge) plus the internal SSH port 2222, so the gateway
    sees a genuinely distinct IP from the first container. ``get_container_host_ip``
    returns ``localhost`` for both testcontainers, which would collide with
    ``ssh_container`` because SSHMachineRepository keys machines by IP only.
    """
    key_dir = tmp_path_factory.mktemp("ssh_keys_2")
    key_path = key_dir / "id_rsa"

    key = asyncssh.generate_private_key("ssh-rsa")
    public_key_str = key.export_public_key("openssh").decode().strip()
    key.write_private_key(str(key_path))

    container = DockerContainer("lscr.io/linuxserver/openssh-server:10.2_p1-r0-ls222")
    container.with_env("USER_NAME", "testuser")
    container.with_env("PUBLIC_KEY", public_key_str)
    container.with_exposed_ports(2222)
    container.waiting_for(LogMessageWaitStrategy("sshd is listening"))

    container.start()
    try:
        await asyncio.sleep(1)

        wrapped = container.get_wrapped_container()
        wrapped.reload()
        bridge_ip = wrapped.attrs["NetworkSettings"]["IPAddress"]
        if not bridge_ip:
            # Fallback: first network's IPAddress (e.g. podman net)
            nets = wrapped.attrs["NetworkSettings"].get("Networks", {})
            bridge_ip = next(
                (cfg.get("IPAddress") for cfg in nets.values() if cfg.get("IPAddress")),
                "",
            )
        if not bridge_ip:
            pytest.skip(
                "Could not resolve container bridge IP for ssh_container_2; "
                "multi-machine disconnect regression needs a distinct IP from ssh_container."
            )

        yield {
            "host": bridge_ip,
            "port": 2222,
            "username": "testuser",
            "key_path": PurePosixPath(str(key_path)),
        }
    finally:
        container.stop()


@pytest.fixture
async def repository(
    ssh_container: dict[str, Any],  # type: ignore[type-arg]
) -> AsyncGenerator[SSHMachineRepository, None]:
    """Create SSHMachineRepository connected to test container."""
    repo = SSHMachineRepository()
    await repo.connect(
        ip=ssh_container["host"],
        username=ssh_container["username"],
        client_keys=[ssh_container["key_path"]],
        port=ssh_container["port"],
    )
    yield repo
    await repo.disconnect_all()


@pytest.fixture
async def operations(
    repository: SSHMachineRepository,  # type: ignore[type-arg]
) -> SSHMachineOperations:
    """Create SSHMachineOperations from the connected repository."""
    return SSHMachineOperations(repository=repository)


class TestSSHGatewayIntegration:
    """Integration tests for SSHMachineRepository + SSHMachineOperations against real Docker SSH server."""

    async def _get_machine(self, repository: SSHMachineRepository) -> ConnectedMachine:
        machines = repository.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_connect_returns_connected_machine(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
    ) -> None:
        """connect() returns a ConnectedMachine with correct ip, platform, and FREE state."""
        machine = await self._get_machine(repository)
        assert machine.ip == ssh_container["host"]
        assert machine.platform == "linux"
        assert machine.state == MachineState.FREE
        assert machine.ncpus > 0

    async def test_run_echo(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """operations.run() executes command and returns output."""
        machine = await self._get_machine(repository)
        result = await operations.run(machine, "echo hello_world")
        assert result.exit_code == 0
        assert "hello_world" in result.stdout

    async def test_run_stderr(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """operations.run() captures stderr."""
        machine = await self._get_machine(repository)
        result = await operations.run(machine, "echo error_msg >&2")
        assert "error_msg" in result.stderr

    async def test_run_exit_code_nonzero(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """operations.run() returns non-zero exit code on failure."""
        machine = await self._get_machine(repository)
        result = await operations.run(machine, "exit 42")
        assert result.exit_code == 42

    async def test_run_multiline_output(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """operations.run() handles multiline stdout."""
        machine = await self._get_machine(repository)
        result = await operations.run(machine, "echo line1; echo line2")
        assert "line1" in result.stdout
        assert "line2" in result.stdout

    async def test_upload_download_roundtrip(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
        tmp_path: Path,
    ) -> None:
        """upload then download returns original content."""
        machine = await self._get_machine(repository)

        local_upload = tmp_path / "upload.txt"
        local_upload.write_text("test content")

        remote = "/tmp/test_upload.txt"
        await operations.upload(machine, local_upload, remote)

        local_download = tmp_path / "downloaded.txt"
        async with operations.get_sftp(machine.ip) as sftp:
            await sftp.get(remote, str(local_download))

        assert local_download.read_text() == "test content"

    async def test_list_free_after_connect(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """Connected machine appears in list_free with matching platform."""
        machines_all = repository.list_free(None)
        assert len(machines_all) >= 1
        assert machines_all[0].platform == "linux"

        machines_linux = repository.list_free(["linux"])
        assert len(machines_linux) >= 1

        machines_windows = repository.list_free(["windows"])
        assert len(machines_windows) == 0

    async def test_list_free_excludes_busy(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """list_free excludes BUSY machines."""
        machine = await self._get_machine(repository)
        busy = machine.occupy()
        repository.update_machine(busy)

        assert len(repository.list_free(None)) == 0

    async def test_disconnect_removes_machine(
        self,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
    ) -> None:
        """disconnect() removes machine from repository registry."""
        repo = SSHMachineRepository()
        machine = await repo.connect(
            ip=ssh_container["host"],
            username=ssh_container["username"],
            client_keys=[ssh_container["key_path"]],
            port=ssh_container["port"],
        )
        assert machine.ip in repo

        await repo.disconnect(machine.ip)
        assert machine.ip not in repo

    async def test_run_multiple_commands(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """Multiple sequential run() calls work on same connection."""
        machine = await self._get_machine(repository)

        r1 = await operations.run(machine, "echo first")
        assert "first" in r1.stdout
        assert r1.exit_code == 0

        r2 = await operations.run(machine, "echo second")
        assert "second" in r2.stdout
        assert r2.exit_code == 0

        r3 = await operations.run(machine, "echo third")
        assert "third" in r3.stdout
        assert r3.exit_code == 0

    async def test_connect_with_env_variable(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """Run command that reads env variable to verify shell works."""
        machine = await self._get_machine(repository)
        result = await operations.run(machine, "echo $HOME")
        assert result.exit_code == 0
        assert result.stdout.strip() != ""

    async def test_upload_and_check_via_run(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        tmp_path: Path,
    ) -> None:
        """Upload a file, then run cat to verify content remotely."""
        machine = await self._get_machine(repository)

        local = tmp_path / "verify.txt"
        local.write_text("verify me")

        remote = "/tmp/verify_test.txt"
        await operations.upload(machine, local, remote)

        result = await operations.run(machine, "cat /tmp/verify_test.txt")
        assert "verify me" in result.stdout

    async def test_disconnect_all(
        self,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
    ) -> None:
        """disconnect_all() removes all machines."""
        repo = SSHMachineRepository()
        await repo.connect(
            ip=ssh_container["host"],
            username=ssh_container["username"],
            client_keys=[ssh_container["key_path"]],
            port=ssh_container["port"],
        )
        assert len(repo) > 0

        await repo.disconnect_all()
        assert len(repo) == 0


class TestOccupancyRunBgLeak:
    """Reproduce bug: run_bg process killed when SSHClientProcess is not stored."""

    async def _get_machine(self, repository: SSHMachineRepository) -> ConnectedMachine:
        machines = repository.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_run_bg_process_survives_without_handle(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """run_bg process must survive even when returned handle is discarded.

        This reproduces the real-world bug: Orchestrator._exec_spawn_command
        calls `await machine.run_bg(cmd)` without storing the SSHClientProcess.
        When the handle is GC'd, the SSH channel closes and kills the remote
        process. The occupancy check then finds no process and marks the
        machine free, even though the task should still be running.
        """
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(repository)
        ip = machine.ip

        # Simulate what _exec_spawn_command does: run_bg without storing result
        await operations.run_bg(machine, "sleep 60")
        # (Handle intentionally not stored — simulating not storing it)
        import gc

        gc.collect()

        # Wait for the sleep_interval the daemon would use
        await asyncio.sleep(1.5)

        # The sleep process must still be running
        result = await operations.occupancy_check(ip, engine)
        assert result is True, "sleep 60 process was killed after handle was discarded"

        # Cleanup
        await operations.run(machine, "killall sleep 2>/dev/null || true")


def _make_pengine(
    *,
    check_pname: str | None = None,
    check_cmd: str | None = None,
    check_cmd_code: int = 0,
    sleep_interval: int = 1,
) -> MagicMock:
    """Create an Engine-like mock for occupancy checks."""
    engine = MagicMock(spec=Engine)
    engine.name = "test_engine"
    engine.check_pname = check_pname
    engine.check_cmd = check_cmd
    engine.check_cmd_code = check_cmd_code
    engine.sleep_interval = sleep_interval
    engine.deployable = ()
    engine.platforms = ("linux",)
    return engine


class TestOccupancyIntegration:
    """Integration tests for occupancy_check against real Docker SSH server."""

    async def _get_machine(self, repository: SSHMachineRepository) -> ConnectedMachine:
        machines = repository.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def _start_bg_process(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        cmd: str,
    ) -> None:
        """Start a detached background process on remote via nohup."""
        machine = await self._get_machine(repository)
        result = await operations.run(machine, f"nohup {cmd} >/dev/null 2>&1 &")
        assert result.exit_code == 0

    async def _kill_bg(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        name: str,
    ) -> None:
        """Kill all processes with given name on remote."""
        machine = await self._get_machine(repository)
        await operations.run(machine, f"killall {name} 2>/dev/null || true")

    async def test_occupancy_check_pname_detects_sleep(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_pname='sleep' finds running sleep via pgrep."""
        engine = _make_pengine(check_pname="sleep")
        ip = (await self._get_machine(repository)).ip

        try:
            await self._start_bg_process(repository, operations, "sleep 60")
            await asyncio.sleep(0.5)
            result = await operations.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(repository, operations, "sleep")

    async def test_occupancy_check_pname_no_match_after_kill(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_pname='sleep' returns False after sleep is killed."""
        engine = _make_pengine(check_pname="sleep")
        ip = (await self._get_machine(repository)).ip

        await self._start_bg_process(repository, operations, "sleep 60")
        await asyncio.sleep(0.5)

        busy = await operations.occupancy_check(ip, engine)
        assert busy is True

        await self._kill_bg(repository, operations, "sleep")
        await asyncio.sleep(0.5)

        busy = await operations.occupancy_check(ip, engine)
        assert busy is False

    async def test_occupancy_check_pname_nonexistent(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_pname with nonexistent process returns False."""
        engine = _make_pengine(check_pname="yascheduler_nonexistent_test_proc")
        ip = (await self._get_machine(repository)).ip

        result = await operations.occupancy_check(ip, engine)
        assert result is False

    async def test_occupancy_check_cmd_pgrep_detects_sleep(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_cmd='pgrep -x sleep' with code 0 detects running sleep."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=0)
        ip = (await self._get_machine(repository)).ip

        try:
            await self._start_bg_process(repository, operations, "sleep 60")
            await asyncio.sleep(0.5)
            result = await operations.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(repository, operations, "sleep")

    async def test_occupancy_check_cmd_pgrep_no_match_after_kill(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_cmd='pgrep -x sleep' returns False after sleep is killed."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=0)
        ip = (await self._get_machine(repository)).ip

        await self._start_bg_process(repository, operations, "sleep 60")
        await asyncio.sleep(0.5)

        busy = await operations.occupancy_check(ip, engine)
        assert busy is True

        await self._kill_bg(repository, operations, "sleep")
        await asyncio.sleep(0.5)

        busy = await operations.occupancy_check(ip, engine)
        assert busy is False

    async def test_occupancy_check_cmd_grep_q_detects_sleep(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_cmd='ps -eocomm= | grep -q sleep' detects running sleep."""
        engine = _make_pengine(
            check_cmd="ps -eocomm= | grep -q sleep", check_cmd_code=0
        )
        ip = (await self._get_machine(repository)).ip

        try:
            await self._start_bg_process(repository, operations, "sleep 60")
            await asyncio.sleep(0.5)
            result = await operations.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(repository, operations, "sleep")

    async def test_occupancy_check_cmd_grep_q_no_match_after_kill(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_cmd='ps -eocomm= | grep -q sleep' returns False after kill."""
        engine = _make_pengine(
            check_cmd="ps -eocomm= | grep -q sleep", check_cmd_code=0
        )
        ip = (await self._get_machine(repository)).ip

        await self._start_bg_process(repository, operations, "sleep 60")
        await asyncio.sleep(0.5)

        busy = await operations.occupancy_check(ip, engine)
        assert busy is True

        await self._kill_bg(repository, operations, "sleep")
        await asyncio.sleep(0.5)

        busy = await operations.occupancy_check(ip, engine)
        assert busy is False

    async def test_occupancy_check_pname_priority_over_cmd(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """When both check_pname and check_cmd are set, pgrep takes priority."""
        engine = _make_pengine(
            check_pname="sleep",
            check_cmd="pgrep -x nonexistent_process_xyz",
            check_cmd_code=0,
        )
        ip = (await self._get_machine(repository)).ip

        try:
            await self._start_bg_process(repository, operations, "sleep 60")
            await asyncio.sleep(0.5)
            result = await operations.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(repository, operations, "sleep")

    async def test_occupancy_check_cmd_nonzero_code(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_cmd with non-zero expected code (inverted logic)."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=1)
        ip = (await self._get_machine(repository)).ip

        # No sleep running: pgrep returns 1, which matches check_cmd_code=1
        result = await operations.occupancy_check(ip, engine)
        assert result is True

    async def test_occupancy_check_cmd_nonzero_code_no_match(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_cmd_code=1 does NOT match when process IS running (pgrep returns 0)."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=1)
        ip = (await self._get_machine(repository)).ip

        try:
            await self._start_bg_process(repository, operations, "sleep 60")
            await asyncio.sleep(0.5)
            result = await operations.occupancy_check(ip, engine)
            assert result is False
        finally:
            await self._kill_bg(repository, operations, "sleep")

    async def test_start_occupancy_check_releases_on_short_process(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """start_occupancy_check releases machine when short-lived process exits."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(repository)
        ip = machine.ip

        # Occupy machine
        busy = machine.occupy()
        repository.update_machine(busy)
        assert repository._machines[ip].machine.state == MachineState.BUSY

        try:
            # Start short-lived process (2 seconds)
            result = await operations.run(
                repository._machines[ip].machine,
                "nohup sleep 2 >/dev/null 2>&1 &",
            )
            assert result.exit_code == 0
            await asyncio.sleep(0.5)

            operations.start_occupancy_check(ip, engine)
            # Wait for checker to detect completion (sleep_interval + buffer)
            task = repository._monitors[ip]
            await asyncio.wait_for(task, timeout=5.0)

            # Machine should be released
            assert repository._machines[ip].machine.state == MachineState.FREE
        finally:
            await operations.run(
                repository._machines[ip].machine,
                "killall sleep 2>/dev/null || true",
            )


class TestOccupancyRaceCondition:
    """Test the two-level state sync between ConnectedMachine and RemoteMachineMetadata.

    Regression test for the bug where start_occupancy_check did NOT occupy
    ConnectedMachine at the repository level. The _meta_sync background task
    (in remote_machine.py) polls repository state every second and mirrors it
    to meta.busy. Without the fix, ConnectedMachine.state stayed FREE,
    causing _meta_sync to set meta.busy=False after 1 second, making the
    task consumer immediately consume (and fail) the running task.

    The fix: start_occupancy_check calls state.machine.occupy() before
    starting the _checker background task.
    """

    async def _get_machine(self, repository: SSHMachineRepository) -> ConnectedMachine:
        machines = repository.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_start_occupancy_check_sets_connected_machine_busy(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """start_occupancy_check must occupy ConnectedMachine (BUSY) at repository level.

        Before fix: ConnectedMachine.state stayed FREE → _meta_sync saw FREE →
        set meta.busy=False → consumer consumed running task immediately.
        """
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(repository)
        ip = machine.ip

        # Machine starts FREE
        assert repository._machines[ip].machine.state == MachineState.FREE

        # Start a background process (simulates run_bg spawn)
        await operations.run(machine, "nohup sleep 5 >/dev/null 2>&1 &")
        await asyncio.sleep(0.5)

        try:
            # THE FIX: start_occupancy_check must set ConnectedMachine to BUSY
            operations.start_occupancy_check(ip, engine)

            assert repository._machines[ip].machine.state == MachineState.BUSY, (
                "start_occupancy_check must occupy ConnectedMachine at repository level"
            )

            # Simulate _meta_sync: it polls repository state and would mirror to meta.busy
            # With the fix, it sees BUSY (not FREE), so meta.busy stays True
            gw_machine = repository.get_machine_state(ip)
            assert gw_machine is not None
            assert gw_machine.state == MachineState.BUSY, (
                "_meta_sync would see FREE without the fix, causing premature task consumption"
            )
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")

    async def test_meta_sync_pattern_does_not_prematurely_free(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """Simulating _meta_sync polling: must see BUSY while process runs."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(repository)
        ip = machine.ip

        # Start process, then start occupancy check
        await operations.run(machine, "nohup sleep 3 >/dev/null 2>&1 &")
        await asyncio.sleep(0.5)

        try:
            operations.start_occupancy_check(ip, engine)

            # Simulate _meta_sync: poll repository state for 2 seconds
            # Without the fix, at least one poll would see FREE
            for _ in range(4):
                await asyncio.sleep(0.5)
                gw_machine = repository.get_machine_state(ip)
                assert gw_machine is not None
                assert gw_machine.state == MachineState.BUSY, (
                    "_meta_sync must consistently see BUSY while process is running"
                )
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")

    async def test_machine_released_after_process_exits(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """After process exits, checker detects it and releases ConnectedMachine."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(repository)
        ip = machine.ip

        # Short-lived process (2 seconds)
        await operations.run(machine, "nohup sleep 2 >/dev/null 2>&1 &")
        await asyncio.sleep(0.5)

        try:
            operations.start_occupancy_check(ip, engine)
            assert repository._machines[ip].machine.state == MachineState.BUSY

            # Wait for checker to detect exit (sleep_interval + process time + buffer)
            task = repository._monitors[ip]
            await asyncio.wait_for(task, timeout=5.0)

            # Checker should have released the machine
            assert repository._machines[ip].machine.state == MachineState.FREE, (
                "ConnectedMachine must be FREE after process exits and checker releases it"
            )
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")

    async def test_already_busy_machine_stays_busy_on_occupancy_start(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """start_occupancy_check on already-BUSY machine is a no-op (idempotent)."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(repository)
        ip = machine.ip

        # Manually occupy
        repository.update_machine(machine.occupy())
        assert repository._machines[ip].machine.state == MachineState.BUSY

        await operations.run(
            repository._machines[ip].machine, "nohup sleep 3 >/dev/null 2>&1 &"
        )
        await asyncio.sleep(0.5)

        try:
            # start_occupancy_check on already-BUSY machine should not crash
            operations.start_occupancy_check(ip, engine)
            assert repository._machines[ip].machine.state == MachineState.BUSY
        finally:
            # Wait for checker to finish (if it was registered for this ip)
            task = repository._monitors.get(ip)
            if task is not None:
                await asyncio.wait_for(task, timeout=5.0)
            await operations.run(
                repository._machines[ip].machine, "killall sleep 2>/dev/null || true"
            )


class TestOccupancySpawnScenario:
    """Integration tests simulating the real spawn → occupancy_check flow.

    Uses run_bg (like orchestrator._exec_spawn_command) to start processes,
    not nohup. This catches bugs where the SSH channel lifecycle affects
    the remote process.
    """

    async def _get_machine(self, repository: SSHMachineRepository) -> ConnectedMachine:
        machines = repository.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_pgrep_detects_run_bg_process(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """pgrep finds a process started via run_bg (like spawn does)."""
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(repository)
        ip = machine.ip

        await operations.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(1)
            busy = await operations.occupancy_check(ip, engine)
            assert busy is True, "pgrep should find sleep process started via run_bg"
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")

    async def test_pname_detects_spawn_like_command_via_run_bg(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_pname finds process from spawn-like command via run_bg.

        Simulates: spawn = sleep 60 && cat 1.input > 1.input.out
        """
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(repository)
        ip = machine.ip

        # Simulate spawn command: cd to dir, then run sleep
        await operations.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(1)
            busy = await operations.occupancy_check(ip, engine)
            assert busy is True, "sleep process should be found by pgrep after run_bg"
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")

    async def test_pname_still_detects_after_handle_discarded(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """Process must survive even if run_bg handle is not stored.

        In real orchestrator, _exec_spawn_command calls
        `await machine.run_bg(cmd)` without storing the handle.
        When the handle is GC'd, the SSH channel should NOT close
        (asyncssh does not close on __del__). This test verifies that.
        """
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(repository)
        ip = machine.ip

        await operations.run_bg(machine, "sleep 60", cwd="/tmp")
        import gc

        gc.collect()

        try:
            await asyncio.sleep(1)
            busy = await operations.occupancy_check(ip, engine)
            assert busy is True, "sleep must survive SSHClientProcess handle GC"
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")

    async def test_cmd_grep_detects_run_bg_process(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """check_cmd with grep detects process started via run_bg."""
        engine = _make_pengine(
            check_cmd="ps -eocomm= | grep -q sleep", check_cmd_code=0
        )
        machine = await self._get_machine(repository)
        ip = machine.ip

        await operations.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(1)
            busy = await operations.occupancy_check(ip, engine)
            assert busy is True, "check_cmd should detect sleep via ps|grep"
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")

    async def test_occupancy_check_via_pgrep_raw_output(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """Diagnostic: show what pgrep -f actually finds on the remote machine."""
        machine = await self._get_machine(repository)

        # Start sleep via run_bg
        await operations.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(0.5)

            # List processes via pgrep -f sleep
            procs = []
            async for p in operations.pgrep(machine.ip, "sleep"):
                procs.append(p)

            # Must find at least the sleep process
            assert len(procs) >= 1, (
                f"pgrep should find at least 1 process, found: {procs}"
            )

            # At least one process should have 'sleep' in its command
            found_sleep = any(
                "sleep" in p.command.lower() or "sleep" in p.name.lower() for p in procs
            )
            assert found_sleep, (
                f"No process with 'sleep' in name/command found: {procs}"
            )
        finally:
            await operations.run(machine, "killall sleep 2>/dev/null || true")


# =============================================================================
# Multi-machine regression: disconnect must not cancel other machines' monitors
# =============================================================================
#
# Real-asyncssh counterpart to the unit test
# ``test_disconnect_does_not_cancel_other_machines_monitors``. Uses two SSH
# testcontainers reached via genuinely distinct IPs: machine A via
# ``ssh_container`` (host IP, mapped port) and machine B via ``ssh_container_2``
# (container bridge IP, internal port 2222). The bridge IP is required because
# ``get_container_host_ip`` returns ``localhost`` for both testcontainers, which
# would collide since SSHMachineRepository keys ``_machines``/``_monitors`` by IP
# only — that collision is exactly what made the original YASCHED_MULTI_CONTAINER
# variant always fail.


class TestMultiMachineBgTaskLeak:
    """Regression: disconnecting one machine must not cancel another's monitor."""

    async def test_disconnect_does_not_cancel_other_machines_monitors(
        self,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
        ssh_container_2: dict[str, Any],  # type: ignore[type-arg]
    ) -> None:
        """Disconnect A cancels only A's monitor; B's monitor stays alive."""
        repository = SSHMachineRepository()
        operations = SSHMachineOperations(repository=repository)
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)

        await repository.connect(
            ip=ssh_container["host"],
            username=ssh_container["username"],
            client_keys=[ssh_container["key_path"]],
            port=ssh_container["port"],
        )
        await repository.connect(
            ip=ssh_container_2["host"],
            username=ssh_container_2["username"],
            client_keys=[ssh_container_2["key_path"]],
            port=ssh_container_2["port"],
        )

        ip_a = ssh_container["host"]
        ip_b = ssh_container_2["host"]
        assert ip_a != ip_b, (
            f"test requires two distinct IPs, got ip_a={ip_a!r} ip_b={ip_b!r}"
        )

        try:
            # Start a long-running sleep on each so the monitors stay BUSY
            for ip in (ip_a, ip_b):
                await operations.run(
                    repository._machines[ip].machine,
                    "nohup sleep 300 >/dev/null 2>&1 &",
                )
            await asyncio.sleep(0.5)

            # Start occupancy monitors on each
            for ip in (ip_a, ip_b):
                operations.start_occupancy_check(ip, engine)

            assert ip_a in repository._monitors
            assert ip_b in repository._monitors
            task_b = repository._monitors[ip_b]

            # Disconnect A — must cancel only A's monitor
            await repository.disconnect(ip_a)

            assert ip_a not in repository._machines
            assert ip_a not in repository._monitors
            # B's monitor and machine are untouched
            assert not task_b.done(), "B monitor must survive disconnect(A)"
            assert repository._monitors[ip_b] is task_b
            assert ip_b in repository._machines

            await repository.disconnect(ip_b)
        finally:
            # Best-effort cleanup of any surviving monitor / remote process
            await repository.disconnect_all()
