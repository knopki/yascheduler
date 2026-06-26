# FILE: tests/integration/test_ssh_gateway.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for SSHMachineGateway against a Docker SSH server via testcontainers.
#   SCOPE: Connection lifecycle, command execution, SFTP upload/download, machine state transitions.
#   DEPENDS: M-SSH-GATEWAY, M-DOMAIN-MODEL
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ssh_container - session-scoped fixture: starts Docker SSH container, generates key pair
#   gateway - function-scoped fixture: SSHMachineGateway connected to test container
#   TestSSHGatewayIntegration - connection lifecycle, command exec, SFTP, state transitions
#   TestOccupancyIntegration - occupancy_check via check_pname/check_cmd against real SSH
#   TestOccupancyRaceCondition - regression for ConnectedMachine state sync bug
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.1 - Update TestOccupancyRaceCondition for new get_machine_state contract returning ConnectedMachine (gateway-port-cleanup).
#   PREVIOUS_CHANGE: v1.2.0 - Add TestOccupancyRaceCondition: regression for two-level state desync bug.
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
from yascheduler.infra.ssh.gateway import SSHMachineGateway

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


@pytest.fixture
async def gateway(
    ssh_container: dict[str, Any],  # type: ignore[type-arg]
) -> AsyncGenerator[SSHMachineGateway, None]:
    """Create SSHMachineGateway connected to test container."""
    gw = SSHMachineGateway()
    await gw.connect(
        ip=ssh_container["host"],
        username=ssh_container["username"],
        client_keys=[ssh_container["key_path"]],
        port=ssh_container["port"],
    )
    yield gw
    await gw.disconnect_all()


class TestSSHGatewayIntegration:
    """Integration tests for SSHMachineGateway against real Docker SSH server."""

    async def _get_machine(self, gateway: SSHMachineGateway) -> ConnectedMachine:
        machines = gateway.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_connect_returns_connected_machine(
        self,
        gateway: SSHMachineGateway,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
    ) -> None:
        """connect() returns a ConnectedMachine with correct ip, platform, and FREE state."""
        machine = await self._get_machine(gateway)
        assert machine.ip == ssh_container["host"]
        assert machine.platform == "linux"
        assert machine.state == MachineState.FREE
        assert machine.ncpus > 0

    async def test_run_echo(self, gateway: SSHMachineGateway) -> None:
        """gateway.run() executes command and returns output."""
        machine = await self._get_machine(gateway)
        result = await gateway.run(machine, "echo hello_world")
        assert result.exit_code == 0
        assert "hello_world" in result.stdout

    async def test_run_stderr(self, gateway: SSHMachineGateway) -> None:
        """gateway.run() captures stderr."""
        machine = await self._get_machine(gateway)
        result = await gateway.run(machine, "echo error_msg >&2")
        assert "error_msg" in result.stderr

    async def test_run_exit_code_nonzero(self, gateway: SSHMachineGateway) -> None:
        """gateway.run() returns non-zero exit code on failure."""
        machine = await self._get_machine(gateway)
        result = await gateway.run(machine, "exit 42")
        assert result.exit_code == 42

    async def test_run_multiline_output(self, gateway: SSHMachineGateway) -> None:
        """gateway.run() handles multiline stdout."""
        machine = await self._get_machine(gateway)
        result = await gateway.run(machine, "echo line1; echo line2")
        assert "line1" in result.stdout
        assert "line2" in result.stdout

    async def test_upload_download_roundtrip(
        self,
        gateway: SSHMachineGateway,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
        tmp_path: Path,
    ) -> None:
        """upload then download returns original content."""
        machine = await self._get_machine(gateway)

        local_upload = tmp_path / "upload.txt"
        local_upload.write_text("test content")

        remote = "/tmp/test_upload.txt"
        await gateway.upload(machine, local_upload, remote)

        local_download = tmp_path / "downloaded.txt"
        await gateway.download(machine, remote, local_download)

        assert local_download.read_text() == "test content"

    async def test_list_free_after_connect(self, gateway: SSHMachineGateway) -> None:
        """Connected machine appears in list_free with matching platform."""
        machines_all = gateway.list_free(None)
        assert len(machines_all) >= 1
        assert machines_all[0].platform == "linux"

        machines_linux = gateway.list_free(["linux"])
        assert len(machines_linux) >= 1

        machines_windows = gateway.list_free(["windows"])
        assert len(machines_windows) == 0

    async def test_list_free_excludes_busy(self, gateway: SSHMachineGateway) -> None:
        """list_free excludes BUSY machines."""
        machine = await self._get_machine(gateway)
        busy = machine.occupy()
        gateway.update_machine(busy)

        assert len(gateway.list_free(None)) == 0

    async def test_disconnect_removes_machine(
        self,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
    ) -> None:
        """disconnect() removes machine from gateway registry."""
        gw = SSHMachineGateway()
        machine = await gw.connect(
            ip=ssh_container["host"],
            username=ssh_container["username"],
            client_keys=[ssh_container["key_path"]],
            port=ssh_container["port"],
        )
        assert machine.ip in gw

        await gw.disconnect(machine.ip)
        assert machine.ip not in gw

    async def test_run_multiple_commands(self, gateway: SSHMachineGateway) -> None:
        """Multiple sequential run() calls work on same connection."""
        machine = await self._get_machine(gateway)

        r1 = await gateway.run(machine, "echo first")
        assert "first" in r1.stdout
        assert r1.exit_code == 0

        r2 = await gateway.run(machine, "echo second")
        assert "second" in r2.stdout
        assert r2.exit_code == 0

        r3 = await gateway.run(machine, "echo third")
        assert "third" in r3.stdout
        assert r3.exit_code == 0

    async def test_connect_with_env_variable(self, gateway: SSHMachineGateway) -> None:
        """Run command that reads env variable to verify shell works."""
        machine = await self._get_machine(gateway)
        result = await gateway.run(machine, "echo $HOME")
        assert result.exit_code == 0
        assert result.stdout.strip() != ""

    async def test_upload_and_check_via_run(
        self, gateway: SSHMachineGateway, tmp_path: Path
    ) -> None:
        """Upload a file, then run cat to verify content remotely."""
        machine = await self._get_machine(gateway)

        local = tmp_path / "verify.txt"
        local.write_text("verify me")

        remote = "/tmp/verify_test.txt"
        await gateway.upload(machine, local, remote)

        result = await gateway.run(machine, "cat /tmp/verify_test.txt")
        assert "verify me" in result.stdout

    async def test_disconnect_all(
        self,
        ssh_container: dict[str, Any],  # type: ignore[type-arg]
    ) -> None:
        """disconnect_all() removes all machines."""
        gw = SSHMachineGateway()
        await gw.connect(
            ip=ssh_container["host"],
            username=ssh_container["username"],
            client_keys=[ssh_container["key_path"]],
            port=ssh_container["port"],
        )
        assert len(gw) > 0

        await gw.disconnect_all()
        assert len(gw) == 0


class TestOccupancyRunBgLeak:
    """Reproduce bug: run_bg process killed when SSHClientProcess is not stored."""

    async def _get_machine(self, gateway: SSHMachineGateway) -> ConnectedMachine:
        machines = gateway.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_run_bg_process_survives_without_handle(
        self, gateway: SSHMachineGateway
    ) -> None:
        """run_bg process must survive even when returned handle is discarded.

        This reproduces the real-world bug: Orchestrator._exec_spawn_command
        calls `await machine.run_bg(cmd)` without storing the SSHClientProcess.
        When the handle is GC'd, the SSH channel closes and kills the remote
        process. The occupancy check then finds no process and marks the
        machine free, even though the task should still be running.
        """
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(gateway)
        ip = machine.ip

        # Simulate what _exec_spawn_command does: run_bg without storing result
        await gateway.run_bg(machine, "sleep 60")
        # (Handle intentionally not stored — simulating not storing it)
        import gc

        gc.collect()

        # Wait for the sleep_interval the daemon would use
        await asyncio.sleep(1.5)

        # The sleep process must still be running
        result = await gateway.occupancy_check(ip, engine)
        assert result is True, "sleep 60 process was killed after handle was discarded"

        # Cleanup
        await gateway.run(machine, "killall sleep 2>/dev/null || true")


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

    async def _get_machine(self, gateway: SSHMachineGateway) -> ConnectedMachine:
        machines = gateway.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def _start_bg_process(self, gateway: SSHMachineGateway, cmd: str) -> None:
        """Start a detached background process on remote via nohup."""
        machine = await self._get_machine(gateway)
        result = await gateway.run(machine, f"nohup {cmd} >/dev/null 2>&1 &")
        assert result.exit_code == 0

    async def _kill_bg(self, gateway: SSHMachineGateway, name: str) -> None:
        """Kill all processes with given name on remote."""
        machine = await self._get_machine(gateway)
        await gateway.run(machine, f"killall {name} 2>/dev/null || true")

    async def test_occupancy_check_pname_detects_sleep(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_pname='sleep' finds running sleep via pgrep."""
        engine = _make_pengine(check_pname="sleep")
        ip = (await self._get_machine(gateway)).ip

        try:
            await self._start_bg_process(gateway, "sleep 60")
            await asyncio.sleep(0.5)
            result = await gateway.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(gateway, "sleep")

    async def test_occupancy_check_pname_no_match_after_kill(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_pname='sleep' returns False after sleep is killed."""
        engine = _make_pengine(check_pname="sleep")
        ip = (await self._get_machine(gateway)).ip

        await self._start_bg_process(gateway, "sleep 60")
        await asyncio.sleep(0.5)

        busy = await gateway.occupancy_check(ip, engine)
        assert busy is True

        await self._kill_bg(gateway, "sleep")
        await asyncio.sleep(0.5)

        busy = await gateway.occupancy_check(ip, engine)
        assert busy is False

    async def test_occupancy_check_pname_nonexistent(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_pname with nonexistent process returns False."""
        engine = _make_pengine(check_pname="yascheduler_nonexistent_test_proc")
        ip = (await self._get_machine(gateway)).ip

        result = await gateway.occupancy_check(ip, engine)
        assert result is False

    async def test_occupancy_check_cmd_pgrep_detects_sleep(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_cmd='pgrep -x sleep' with code 0 detects running sleep."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=0)
        ip = (await self._get_machine(gateway)).ip

        try:
            await self._start_bg_process(gateway, "sleep 60")
            await asyncio.sleep(0.5)
            result = await gateway.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(gateway, "sleep")

    async def test_occupancy_check_cmd_pgrep_no_match_after_kill(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_cmd='pgrep -x sleep' returns False after sleep is killed."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=0)
        ip = (await self._get_machine(gateway)).ip

        await self._start_bg_process(gateway, "sleep 60")
        await asyncio.sleep(0.5)

        busy = await gateway.occupancy_check(ip, engine)
        assert busy is True

        await self._kill_bg(gateway, "sleep")
        await asyncio.sleep(0.5)

        busy = await gateway.occupancy_check(ip, engine)
        assert busy is False

    async def test_occupancy_check_cmd_grep_q_detects_sleep(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_cmd='ps -eocomm= | grep -q sleep' detects running sleep."""
        engine = _make_pengine(
            check_cmd="ps -eocomm= | grep -q sleep", check_cmd_code=0
        )
        ip = (await self._get_machine(gateway)).ip

        try:
            await self._start_bg_process(gateway, "sleep 60")
            await asyncio.sleep(0.5)
            result = await gateway.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(gateway, "sleep")

    async def test_occupancy_check_cmd_grep_q_no_match_after_kill(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_cmd='ps -eocomm= | grep -q sleep' returns False after kill."""
        engine = _make_pengine(
            check_cmd="ps -eocomm= | grep -q sleep", check_cmd_code=0
        )
        ip = (await self._get_machine(gateway)).ip

        await self._start_bg_process(gateway, "sleep 60")
        await asyncio.sleep(0.5)

        busy = await gateway.occupancy_check(ip, engine)
        assert busy is True

        await self._kill_bg(gateway, "sleep")
        await asyncio.sleep(0.5)

        busy = await gateway.occupancy_check(ip, engine)
        assert busy is False

    async def test_occupancy_check_pname_priority_over_cmd(
        self, gateway: SSHMachineGateway
    ) -> None:
        """When both check_pname and check_cmd are set, pgrep takes priority."""
        engine = _make_pengine(
            check_pname="sleep",
            check_cmd="pgrep -x nonexistent_process_xyz",
            check_cmd_code=0,
        )
        ip = (await self._get_machine(gateway)).ip

        try:
            await self._start_bg_process(gateway, "sleep 60")
            await asyncio.sleep(0.5)
            result = await gateway.occupancy_check(ip, engine)
            assert result is True
        finally:
            await self._kill_bg(gateway, "sleep")

    async def test_occupancy_check_cmd_nonzero_code(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_cmd with non-zero expected code (inverted logic)."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=1)
        ip = (await self._get_machine(gateway)).ip

        # No sleep running: pgrep returns 1, which matches check_cmd_code=1
        result = await gateway.occupancy_check(ip, engine)
        assert result is True

    async def test_occupancy_check_cmd_nonzero_code_no_match(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_cmd_code=1 does NOT match when process IS running (pgrep returns 0)."""
        engine = _make_pengine(check_cmd="pgrep -x sleep", check_cmd_code=1)
        ip = (await self._get_machine(gateway)).ip

        try:
            await self._start_bg_process(gateway, "sleep 60")
            await asyncio.sleep(0.5)
            result = await gateway.occupancy_check(ip, engine)
            assert result is False
        finally:
            await self._kill_bg(gateway, "sleep")

    async def test_start_occupancy_check_releases_on_short_process(
        self, gateway: SSHMachineGateway
    ) -> None:
        """start_occupancy_check releases machine when short-lived process exits."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(gateway)
        ip = machine.ip

        # Occupy machine
        busy = machine.occupy()
        gateway.update_machine(busy)
        assert gateway._machines[ip].machine.state == MachineState.BUSY

        try:
            # Start short-lived process (2 seconds)
            result = await gateway.run(
                gateway._machines[ip].machine,
                "nohup sleep 2 >/dev/null 2>&1 &",
            )
            assert result.exit_code == 0
            await asyncio.sleep(0.5)

            gateway.start_occupancy_check(ip, engine)
            # Wait for checker to detect completion (sleep_interval + buffer)
            task = list(gateway._bg_tasks)[0]
            await asyncio.wait_for(task, timeout=5.0)

            # Machine should be released
            assert gateway._machines[ip].machine.state == MachineState.FREE
        finally:
            await gateway.run(
                gateway._machines[ip].machine,
                "killall sleep 2>/dev/null || true",
            )


class TestOccupancyRaceCondition:
    """Test the two-level state sync between ConnectedMachine and RemoteMachineMetadata.

    Regression test for the bug where start_occupancy_check did NOT occupy
    ConnectedMachine at the gateway level. The _meta_sync background task
    (in remote_machine.py) polls gateway state every second and mirrors it
    to meta.busy. Without the fix, ConnectedMachine.state stayed FREE,
    causing _meta_sync to set meta.busy=False after 1 second, making the
    task consumer immediately consume (and fail) the running task.

    The fix: start_occupancy_check calls state.machine.occupy() before
    starting the _checker background task.
    """

    async def _get_machine(self, gateway: SSHMachineGateway) -> ConnectedMachine:
        machines = gateway.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_start_occupancy_check_sets_connected_machine_busy(
        self, gateway: SSHMachineGateway
    ) -> None:
        """start_occupancy_check must occupy ConnectedMachine (BUSY) at gateway level.

        Before fix: ConnectedMachine.state stayed FREE → _meta_sync saw FREE →
        set meta.busy=False → consumer consumed running task immediately.
        """
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(gateway)
        ip = machine.ip

        # Machine starts FREE
        assert gateway._machines[ip].machine.state == MachineState.FREE

        # Start a background process (simulates run_bg spawn)
        await gateway.run(machine, "nohup sleep 5 >/dev/null 2>&1 &")
        await asyncio.sleep(0.5)

        try:
            # THE FIX: start_occupancy_check must set ConnectedMachine to BUSY
            gateway.start_occupancy_check(ip, engine)

            assert gateway._machines[ip].machine.state == MachineState.BUSY, (
                "start_occupancy_check must occupy ConnectedMachine at gateway level"
            )

            # Simulate _meta_sync: it polls gateway state and would mirror to meta.busy
            # With the fix, it sees BUSY (not FREE), so meta.busy stays True
            gw_machine = gateway.get_machine_state(ip)
            assert gw_machine is not None
            assert gw_machine.state == MachineState.BUSY, (
                "_meta_sync would see FREE without the fix, causing premature task consumption"
            )
        finally:
            await gateway.run(machine, "killall sleep 2>/dev/null || true")

    async def test_meta_sync_pattern_does_not_prematurely_free(
        self, gateway: SSHMachineGateway
    ) -> None:
        """Simulating _meta_sync polling: must see BUSY while process runs."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(gateway)
        ip = machine.ip

        # Start process, then start occupancy check
        await gateway.run(machine, "nohup sleep 3 >/dev/null 2>&1 &")
        await asyncio.sleep(0.5)

        try:
            gateway.start_occupancy_check(ip, engine)

            # Simulate _meta_sync: poll gateway state for 2 seconds
            # Without the fix, at least one poll would see FREE
            for _ in range(4):
                await asyncio.sleep(0.5)
                gw_machine = gateway.get_machine_state(ip)
                assert gw_machine is not None
                assert gw_machine.state == MachineState.BUSY, (
                    "_meta_sync must consistently see BUSY while process is running"
                )
        finally:
            await gateway.run(machine, "killall sleep 2>/dev/null || true")

    async def test_machine_released_after_process_exits(
        self, gateway: SSHMachineGateway
    ) -> None:
        """After process exits, checker detects it and releases ConnectedMachine."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(gateway)
        ip = machine.ip

        # Short-lived process (2 seconds)
        await gateway.run(machine, "nohup sleep 2 >/dev/null 2>&1 &")
        await asyncio.sleep(0.5)

        try:
            gateway.start_occupancy_check(ip, engine)
            assert gateway._machines[ip].machine.state == MachineState.BUSY

            # Wait for checker to detect exit (sleep_interval + process time + buffer)
            bg_tasks = list(gateway._bg_tasks)
            assert len(bg_tasks) > 0
            await asyncio.wait_for(bg_tasks[-1], timeout=5.0)

            # Checker should have released the machine
            assert gateway._machines[ip].machine.state == MachineState.FREE, (
                "ConnectedMachine must be FREE after process exits and checker releases it"
            )
        finally:
            await gateway.run(machine, "killall sleep 2>/dev/null || true")

    async def test_already_busy_machine_stays_busy_on_occupancy_start(
        self, gateway: SSHMachineGateway
    ) -> None:
        """start_occupancy_check on already-BUSY machine is a no-op (idempotent)."""
        engine = _make_pengine(check_pname="sleep", sleep_interval=1)
        machine = await self._get_machine(gateway)
        ip = machine.ip

        # Manually occupy
        gateway.update_machine(machine.occupy())
        assert gateway._machines[ip].machine.state == MachineState.BUSY

        await gateway.run(
            gateway._machines[ip].machine, "nohup sleep 3 >/dev/null 2>&1 &"
        )
        await asyncio.sleep(0.5)

        try:
            # start_occupancy_check on already-BUSY machine should not crash
            gateway.start_occupancy_check(ip, engine)
            assert gateway._machines[ip].machine.state == MachineState.BUSY
        finally:
            # Wait for checker to finish
            bg_tasks = list(gateway._bg_tasks)
            if bg_tasks:
                await asyncio.wait_for(bg_tasks[-1], timeout=5.0)
            await gateway.run(
                gateway._machines[ip].machine, "killall sleep 2>/dev/null || true"
            )


class TestOccupancySpawnScenario:
    """Integration tests simulating the real spawn → occupancy_check flow.

    Uses run_bg (like orchestrator._exec_spawn_command) to start processes,
    not nohup. This catches bugs where the SSH channel lifecycle affects
    the remote process.
    """

    async def _get_machine(self, gateway: SSHMachineGateway) -> ConnectedMachine:
        machines = gateway.list_free(None)
        assert len(machines) > 0
        return machines[0]

    async def test_pgrep_detects_run_bg_process(
        self, gateway: SSHMachineGateway
    ) -> None:
        """pgrep finds a process started via run_bg (like spawn does)."""
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(gateway)
        ip = machine.ip

        await gateway.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(1)
            busy = await gateway.occupancy_check(ip, engine)
            assert busy is True, "pgrep should find sleep process started via run_bg"
        finally:
            await gateway.run(machine, "killall sleep 2>/dev/null || true")

    async def test_pname_detects_spawn_like_command_via_run_bg(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_pname finds process from spawn-like command via run_bg.

        Simulates: spawn = sleep 60 && cat 1.input > 1.input.out
        """
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(gateway)
        ip = machine.ip

        # Simulate spawn command: cd to dir, then run sleep
        await gateway.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(1)
            busy = await gateway.occupancy_check(ip, engine)
            assert busy is True, "sleep process should be found by pgrep after run_bg"
        finally:
            await gateway.run(machine, "killall sleep 2>/dev/null || true")

    async def test_pname_still_detects_after_handle_discarded(
        self, gateway: SSHMachineGateway
    ) -> None:
        """Process must survive even if run_bg handle is not stored.

        In real orchestrator, _exec_spawn_command calls
        `await machine.run_bg(cmd)` without storing the handle.
        When the handle is GC'd, the SSH channel should NOT close
        (asyncssh does not close on __del__). This test verifies that.
        """
        engine = _make_pengine(check_pname="sleep")
        machine = await self._get_machine(gateway)
        ip = machine.ip

        await gateway.run_bg(machine, "sleep 60", cwd="/tmp")
        import gc

        gc.collect()

        try:
            await asyncio.sleep(1)
            busy = await gateway.occupancy_check(ip, engine)
            assert busy is True, "sleep must survive SSHClientProcess handle GC"
        finally:
            await gateway.run(machine, "killall sleep 2>/dev/null || true")

    async def test_cmd_grep_detects_run_bg_process(
        self, gateway: SSHMachineGateway
    ) -> None:
        """check_cmd with grep detects process started via run_bg."""
        engine = _make_pengine(
            check_cmd="ps -eocomm= | grep -q sleep", check_cmd_code=0
        )
        machine = await self._get_machine(gateway)
        ip = machine.ip

        await gateway.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(1)
            busy = await gateway.occupancy_check(ip, engine)
            assert busy is True, "check_cmd should detect sleep via ps|grep"
        finally:
            await gateway.run(machine, "killall sleep 2>/dev/null || true")

    async def test_occupancy_check_via_pgrep_raw_output(
        self, gateway: SSHMachineGateway
    ) -> None:
        """Diagnostic: show what pgrep -f actually finds on the remote machine."""
        machine = await self._get_machine(gateway)

        # Start sleep via run_bg
        await gateway.run_bg(machine, "sleep 60", cwd="/tmp")
        try:
            await asyncio.sleep(0.5)

            # List processes via pgrep -f sleep
            procs = []
            async for p in gateway.pgrep(machine.ip, "sleep"):
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
            await gateway.run(machine, "killall sleep 2>/dev/null || true")
