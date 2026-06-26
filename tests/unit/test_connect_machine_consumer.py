# FILE: tests/unit/test_connect_machine_consumer.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Orchestrator._connect_machine_consumer never-connected-node grace timer + abandon dispatch.
#   SCOPE: Failure-within-grace retries, failure-past-grace abandons, success resets timer, unknown-cloud fallback, abandon-failed isolation, daemon-restart reset, _connect_grace_for pure helper, producer excludes static nodes.
#   DEPENDS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE, M-DOMAIN-PORTS, M-CLOUD-CONFIGS
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestConnectMachineConsumerGraceTimer - Within-grace retries, past-grace abandons, success resets, abandon-failed isolation
#   TestConnectGraceFor - _connect_grace_for pure helper: per-cloud lookup + 120s fallback
#   TestDaemonRestartResetsFailureTimers - Fresh Orchestrator has empty _connect_failures
#   TestConnectMachineProducerExcludesStaticNodes - cloud=None nodes never yielded to the consumer / abandon path
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Add TestConnectMachineProducerExcludesStaticNodes covering the v6.2.1 producer filter (static nodes never reach the abandon path). Regression guard for the non-cloud-node auto-removal scope creep found in review.
#   PREVIOUS_CHANGE: v1.0.0 - Initial tests for the never-connected-node grace timer + abandon dispatch (fix-never-connected-node-leak).
# END_CHANGE_SUMMARY
"""Unit tests for Orchestrator._connect_machine_consumer grace timer + abandon dispatch.

Covers the in-memory per-IP connect-failure timer introduced by the
fix-never-connected-node-leak change:

- Within grace → log + retry (no abandon call, IP stays in timer)
- Past grace → abandon_node called, IP popped from timer
- Successful connect pops the IP from the timer
- Unknown cloud falls back to 120s grace
- Abandon failure is caught (worker survives)
- Fresh Orchestrator starts with an empty timer (daemon-restart reset)
- Producer excludes static (cloud=None) nodes from the abandon path
"""

from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.orchestrator import Orchestrator
from yascheduler.application.queue import UMessage
from yascheduler.domain import Engine, EngineRepository, LocalSettings, RemoteDefaults
from yascheduler.domain.exceptions import MachineConnectionError
from yascheduler.domain.model import Node
from yascheduler.entrypoints import Config
from yascheduler.infra.cloud.cloud_configs import (
    ConfigCloudAzure,
    ConfigCloudHetzner,
)

if TYPE_CHECKING:
    from yascheduler.application.uow import AbstractUnitOfWork


def _make_node(ip: str = "10.0.0.5", cloud: str | None = "hetzner") -> Node:
    return Node(ip=ip, ncpus=2, cloud=cloud, username="root", port=22, enabled=True)


def make_orchestrator(
    config_clouds: list | None = None,
    allocation_tracker: AllocationTracker | None = None,
) -> Orchestrator:
    """Build a real Orchestrator with mocked externals (no I/O)."""
    local = MagicMock(spec=LocalSettings)
    local.conn_machine_pending = 10
    local.allocate_pending = 5
    local.consume_pending = 3
    local.deallocate_pending = 2
    local.conn_machine_limit = 1
    local.allocate_limit = 1
    local.consume_limit = 1
    local.deallocate_limit = 1
    local.keys_dir = Path("/tmp/keys")

    remote = MagicMock(spec=RemoteDefaults)
    remote.tasks_dir = PurePosixPath("/tmp/tasks")
    remote.data_dir = PurePosixPath("/tmp/data")
    remote.engines_dir = PurePosixPath("/tmp/engines")
    remote.username = "root"
    remote.jump_host = None
    remote.jump_username = None

    cfg = MagicMock(spec=Config)
    cfg.local = local
    cfg.remote = remote

    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)

    def uow_factory() -> AbstractUnitOfWork:
        return mock_uow

    gateway = MagicMock()
    gateway.__len__ = MagicMock(return_value=0)

    engine = MagicMock(spec=Engine, sleep_interval=0)
    engine.name = "test_engine"
    engines = MagicMock(spec=EngineRepository)
    engines.values.return_value = [engine]

    clouds = AsyncMock()

    if allocation_tracker is None:
        allocation_tracker = AllocationTracker()
    if config_clouds is None:
        config_clouds = []

    return Orchestrator(
        local_settings=local,
        remote_defaults=remote,
        uow_factory=uow_factory,
        clouds=clouds,
        gateway=gateway,
        engines=engines,
        log=MagicMock(),
        config_clouds=config_clouds,
        local_tasks_dir=Path("/tmp"),
        allocation_tracker=allocation_tracker,
        active_clouds=[],
        allocation_lock=asyncio.Lock(),
        list_private_keys_fn=lambda _keys_dir: [],
    )


class TestConnectMachineConsumerGraceTimer:
    """Grace-timer behavior in _connect_machine_consumer."""

    @pytest.mark.asyncio
    async def test_connect_failure_within_grace_retries_without_abandoning(
        self,
    ) -> None:
        """Within grace: gateway.connect raises, age < grace → no abandon, IP stays in timer."""
        cfg_cloud = MagicMock(prefix="hetzner", connect_grace=60)
        cfg_cloud.jump_host = None
        cfg_cloud.jump_username = None
        orch = make_orchestrator(config_clouds=[cfg_cloud])
        orch._gateway.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=MachineConnectionError("10.0.0.5", "refused")
        )

        # monotonic sequence: first failure records first_seen=100.0; the second
        # read for `age` returns 110.0 → age=10s < grace=60s → retry path.
        with (
            patch(
                "yascheduler.application.orchestrator.time.monotonic",
                side_effect=[100.0, 110.0],
            ) as mock_mono,
            patch(
                "yascheduler.application.orchestrator.abandon_node",
                new=AsyncMock(),
            ) as mock_abandon,
        ):
            await orch._connect_machine_consumer(UMessage("10.0.0.5", _make_node()))

        assert mock_mono.call_count == 2
        mock_abandon.assert_not_called()
        # IP stays in the timer (retry path)
        assert "10.0.0.5" in orch._connect_failures
        orch._log.warning.assert_called_once()  # type: ignore[attr-defined]
        # CONNECT_RETRY marker is logged
        warning_args = orch._log.warning.call_args.args  # type: ignore[attr-defined]
        assert "CONNECT_RETRY" in warning_args[0]

    @pytest.mark.asyncio
    async def test_connect_failure_past_grace_triggers_abandon(self) -> None:
        """Past grace: gateway.connect raises, age >= grace → abandon_node called, IP popped."""
        cfg_cloud = MagicMock(prefix="hetzner", connect_grace=60)
        cfg_cloud.jump_host = None
        cfg_cloud.jump_username = None
        orch = make_orchestrator(config_clouds=[cfg_cloud])
        orch._gateway.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=MachineConnectionError("10.0.0.5", "refused")
        )

        with (
            patch(
                "yascheduler.application.orchestrator.time.monotonic",
                side_effect=[100.0, 165.0],
            ),
            patch(
                "yascheduler.application.orchestrator.abandon_node",
                new=AsyncMock(),
            ) as mock_abandon,
        ):
            await orch._connect_machine_consumer(UMessage("10.0.0.5", _make_node()))

        mock_abandon.assert_awaited_once()
        # abandon_node called with (node, gateway, clouds, uow_factory, tracker)
        args = mock_abandon.call_args.args
        assert args[1] is orch._gateway
        assert args[2] is orch._clouds
        assert args[4] is orch._tracker
        # IP popped after abandon
        assert "10.0.0.5" not in orch._connect_failures
        # CONNECT_ABANDON logged at error level
        error_calls = orch._log.error.call_args_list  # type: ignore[attr-defined]
        assert any("CONNECT_ABANDON" in c.args[0] for c in error_calls)

    @pytest.mark.asyncio
    async def test_successful_connect_resets_failure_timer(self) -> None:
        """First call records first_seen; second call (success) pops the IP."""
        cfg_cloud = MagicMock(prefix="hetzner", connect_grace=60)
        cfg_cloud.jump_host = None
        cfg_cloud.jump_username = None
        orch = make_orchestrator(config_clouds=[cfg_cloud])
        orch._gateway.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=MachineConnectionError("10.0.0.5", "x")
        )

        # First call: failure within grace → IP recorded.
        with (
            patch(
                "yascheduler.application.orchestrator.time.monotonic",
                side_effect=[100.0, 105.0],
            ),
            patch("yascheduler.application.orchestrator.abandon_node", new=AsyncMock()),
        ):
            await orch._connect_machine_consumer(UMessage("10.0.0.5", _make_node()))
        assert "10.0.0.5" in orch._connect_failures

        # Second call: success → IP popped.
        orch._gateway.connect = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]  # success
        await orch._connect_machine_consumer(UMessage("10.0.0.5", _make_node()))
        assert "10.0.0.5" not in orch._connect_failures

    @pytest.mark.asyncio
    async def test_abandon_failed_does_not_kill_worker(self) -> None:
        """When abandon_node raises, the consumer catches it and returns without propagating."""
        cfg_cloud = MagicMock(prefix="hetzner", connect_grace=60)
        cfg_cloud.jump_host = None
        cfg_cloud.jump_username = None
        orch = make_orchestrator(config_clouds=[cfg_cloud])
        orch._gateway.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=MachineConnectionError("10.0.0.5", "x")
        )

        with (
            patch(
                "yascheduler.application.orchestrator.time.monotonic",
                side_effect=[100.0, 200.0],
            ),
            patch(
                "yascheduler.application.orchestrator.abandon_node",
                new=AsyncMock(side_effect=RuntimeError("abandon failed")),
            ) as mock_abandon,
        ):
            # Must NOT raise — consumer swallows to keep the worker alive.
            await orch._connect_machine_consumer(UMessage("10.0.0.5", _make_node()))

        mock_abandon.assert_awaited_once()
        # IP is still popped after a failed abandon (no infinite loop on next cycle)
        assert "10.0.0.5" not in orch._connect_failures
        # ABANDON_FAILED marker logged at error level
        error_calls = orch._log.error.call_args_list  # type: ignore[attr-defined]
        assert any("ABANDON_FAILED" in c.args[0] for c in error_calls)


class TestConnectGraceFor:
    """_connect_grace_for: per-cloud lookup with conservative fallback."""

    def test_known_cloud_returns_dto_default(self) -> None:
        """hetzner config → connect_grace=60."""
        orch = make_orchestrator(config_clouds=[ConfigCloudHetzner()])
        assert orch._connect_grace_for("hetzner") == 60

    def test_azure_returns_120(self) -> None:
        """Azure (prefix 'az') → connect_grace=120."""
        orch = make_orchestrator(
            config_clouds=[ConfigCloudHetzner(), ConfigCloudAzure()]
        )
        assert orch._connect_grace_for("az") == 120

    def test_unknown_cloud_falls_back_to_120s_grace(self) -> None:
        """cloud='unknown' (no matching prefix) → 120."""
        orch = make_orchestrator(config_clouds=[ConfigCloudHetzner()])
        assert orch._connect_grace_for("unknown") == 120

    def test_none_cloud_falls_back_to_120s_grace(self) -> None:
        """cloud=None → 120."""
        orch = make_orchestrator(config_clouds=[ConfigCloudHetzner()])
        assert orch._connect_grace_for(None) == 120

    def test_empty_config_clouds_falls_back_to_120(self) -> None:
        """No clouds configured → 120."""
        orch = make_orchestrator(config_clouds=[])
        assert orch._connect_grace_for("hetzner") == 120


class TestDaemonRestartResetsFailureTimers:
    """Fresh Orchestrator starts with an empty _connect_failures dict."""

    def test_daemon_restart_resets_failure_timers(self) -> None:
        """A newly-constructed Orchestrator has _connect_failures == {}.

        Enforces the in-memory-only contract from the orchestrator spec's
        "Daemon restart resets failure timers" scenario.
        """
        orch = make_orchestrator()
        assert orch._connect_failures == {}


class TestConnectMachineProducerExcludesStaticNodes:
    """The connect-machine producer must not yield static (cloud=None) nodes.

    Regression guard for the v6.2.1 scope fix: the never-connected-node abandon
    path bounds cloud billing only. Static operator-managed nodes were never
    auto-removed by the application and must never reach the abandon dispatch,
    even across daemon restarts or transient SSH outages.
    """

    @pytest.mark.asyncio
    async def test_static_node_not_yielded_to_consumer(self) -> None:
        """cloud=None enabled node not in gateway → producer yields nothing for it.

        Drives the producer to completion and collects every yielded message's
        IP. A static node must not appear, so it can never reach the consumer
        (and thus never reach abandon_node / DB-row removal).
        """
        from yascheduler.domain.model import Node

        static_node = Node(
            ip="10.0.0.9", ncpus=2, cloud=None, username="root", port=22, enabled=True
        )
        cloud_node = Node(
            ip="10.0.0.10",
            ncpus=2,
            cloud="hetzner",
            username="root",
            port=22,
            enabled=True,
        )

        orch = make_orchestrator(config_clouds=[])
        # Gateway contains neither IP → both would have been yielded pre-fix.
        orch._gateway.contains = MagicMock(return_value=False)  # type: ignore[method-assign]
        orch._uow_factory = MagicMock(  # type: ignore[method-assign]
            return_value=_uow_with_nodes([static_node, cloud_node])
        )

        yielded_ips = [msg.id async for msg in orch._connect_machine_producer()]

        assert "10.0.0.9" not in yielded_ips, (
            "static node (cloud=None) must NOT be yielded to the connect consumer — "
            "operator-managed nodes must never reach the abandon path"
        )
        assert "10.0.0.10" in yielded_ips, "cloud node must still be yielded normally"

    @pytest.mark.asyncio
    async def test_gateway_registered_static_node_not_yielded(self) -> None:
        """A static node already in the gateway is not re-yielded (pre-existing behavior)."""
        from yascheduler.domain.model import Node

        static_node = Node(
            ip="10.0.0.9", ncpus=2, cloud=None, username="root", port=22, enabled=True
        )

        orch = make_orchestrator(config_clouds=[])
        orch._gateway.contains = MagicMock(return_value=True)  # type: ignore[method-assign]
        orch._uow_factory = MagicMock(  # type: ignore[method-assign]
            return_value=_uow_with_nodes([static_node])
        )

        yielded_ips = [msg.id async for msg in orch._connect_machine_producer()]
        assert yielded_ips == []

    @pytest.mark.asyncio
    async def test_static_node_never_reaches_abandon_even_past_grace(self) -> None:
        """End-to-end guard: a static node that fails SSH forever is never abandoned.

        Confirms the producer filter is the defense — even if a bug elsewhere
        tried to drive a static node, the consumer path is never entered for it
        because the producer does not enqueue it.
        """
        from yascheduler.domain.exceptions import MachineConnectionError
        from yascheduler.domain.model import Node

        static_node = Node(
            ip="10.0.0.9", ncpus=2, cloud=None, username="root", port=22, enabled=True
        )

        orch = make_orchestrator(config_clouds=[])
        orch._gateway.contains = MagicMock(return_value=False)  # type: ignore[method-assign]
        orch._uow_factory = MagicMock(  # type: ignore[method-assign]
            return_value=_uow_with_nodes([static_node])
        )
        # If the producer (incorrectly) yielded the static node, connect would
        # raise and, past 120s grace, abandon would fire. Set both up to prove
        # neither is ever called.
        orch._gateway.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=MachineConnectionError("10.0.0.9", "refused")
        )

        yielded = [msg async for msg in orch._connect_machine_producer()]
        assert yielded == [], "static node must not be yielded"

        # Nothing was enqueued, so connect/abandon were never invoked.
        orch._gateway.connect.assert_not_called()  # type: ignore[attr-defined]
        assert "10.0.0.9" not in orch._connect_failures


def _uow_with_nodes(nodes: list) -> AsyncMock:
    """Build a UoW mock whose nodes.list_enabled returns the given nodes."""
    uow = AsyncMock()
    uow.nodes = AsyncMock()
    uow.nodes.list_enabled = AsyncMock(return_value=nodes)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return uow
