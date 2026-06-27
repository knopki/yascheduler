# FILE: tests/unit/test_connect_machine_consumer.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Orchestrator._connect_machine_consumer never-connected-node grace timer + abandon dispatch.
#   SCOPE: Failure-within-grace retries, failure-past-grace abandons, success resets timer, unknown-cloud fallback, abandon-failed isolation, daemon-restart reset, _connect_grace_for pure helper, producer yields static nodes (cloud is None); static nodes retried without abandon.
#   DEPENDS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE, M-DOMAIN-PORTS, M-CLOUD-CONFIGS
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestConnectMachineConsumerGraceTimer - Within-grace retries, past-grace abandons, success resets, abandon-failed isolation
#   TestConnectGraceFor - _connect_grace_for pure helper: per-cloud lookup + 120s fallback
#   TestDaemonRestartResetsFailureTimers - Fresh Orchestrator has empty _connect_failures
#   TestConnectMachineProducerYieldsStaticNodes - cloud=None nodes ARE yielded to the consumer; static node failures retried without abandon (consumer-side guard before grace-check)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Rewrite TestConnectMachineProducerExcludesStaticNodes → TestConnectMachineProducerYieldsStaticNodes for fix-static-node-connect-exclusion: the producer filter no longer excludes cloud=None nodes (over-broad v6.2.1 FILTER_CLOUD_ONLY filter broke the yasetnode → daemon handoff, leaving tasks stuck in TO_DO). New contract: static nodes ARE yielded; a consumer-side guard before the grace-check retries them indefinitely without ever calling abandon_node. Added test_static_node_past_grace_does_not_abandon temporal guard.
#   PREVIOUS_CHANGE: v1.1.0 - Add TestConnectMachineProducerExcludesStaticNodes covering the v6.2.1 producer filter (static nodes never reach the abandon path). Regression guard for the non-cloud-node auto-removal scope creep found in review.
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
- Producer yields static (cloud=None) nodes; static node failures retry
  without abandon (consumer-side guard before the grace-check)
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

    repository = MagicMock()
    repository.__len__ = MagicMock(return_value=0)
    operations = MagicMock()

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
        repository=repository,
        operations=operations,
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
        orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
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
        orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
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
        # abandon_node called with (node, clouds, uow_factory, tracker) — gateway dropped
        args = mock_abandon.call_args.args
        assert args[1] is orch._clouds
        assert args[3] is orch._tracker
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
        orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
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
        orch._repository.connect = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]  # success
        await orch._connect_machine_consumer(UMessage("10.0.0.5", _make_node()))
        assert "10.0.0.5" not in orch._connect_failures

    @pytest.mark.asyncio
    async def test_abandon_failed_does_not_kill_worker(self) -> None:
        """When abandon_node raises, the consumer catches it and returns without propagating."""
        cfg_cloud = MagicMock(prefix="hetzner", connect_grace=60)
        cfg_cloud.jump_host = None
        cfg_cloud.jump_username = None
        orch = make_orchestrator(config_clouds=[cfg_cloud])
        orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
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


class TestConnectMachineProducerYieldsStaticNodes:
    """The connect-machine producer yields static (cloud=None) nodes; static
    node failures are retried without abandon.

    Coverage for fix-static-node-connect-exclusion: the v6.2.1 producer filter
    (`n.cloud is not None`) was over-broad — it excluded static nodes from the
    connect path entirely, breaking the yasetnode → daemon handoff (tasks
    stuck in TO_DO). The filter is removed; a consumer-side guard before the
    grace-check now retries static nodes indefinitely without ever calling
    abandon_node, preserving the task 4.7 intent (static nodes never
    auto-removed) with a narrower mechanism.
    """

    @pytest.mark.asyncio
    async def test_static_node_yielded_to_consumer(self) -> None:
        """cloud=None enabled node not in gateway → producer YIELDS it.

        Drives the producer to completion and collects every yielded message's
        IP. A static node MUST appear (the daemon connects it), alongside the
        cloud node.
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
        # Gateway contains neither IP → both are yielded.
        orch._repository.contains = MagicMock(return_value=False)  # type: ignore[method-assign]
        orch._uow_factory = MagicMock(  # type: ignore[method-assign]
            return_value=_uow_with_nodes([static_node, cloud_node])
        )

        yielded_ips = [msg.id async for msg in orch._connect_machine_producer()]

        assert "10.0.0.9" in yielded_ips, (
            "static node (cloud=None) MUST be yielded to the connect consumer — "
            "the daemon must connect operator-managed nodes"
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
        orch._repository.contains = MagicMock(return_value=True)  # type: ignore[method-assign]
        orch._uow_factory = MagicMock(  # type: ignore[method-assign]
            return_value=_uow_with_nodes([static_node])
        )

        yielded_ips = [msg.id async for msg in orch._connect_machine_producer()]
        assert yielded_ips == []

    @pytest.mark.asyncio
    async def test_static_node_failure_retries_without_abandon(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A static node that fails SSH is retried without reaching abandon_node.

        Drives _connect_machine_consumer directly with a static node whose
        gateway.connect raises MachineConnectionError. The consumer-side guard
        (START_BLOCK_STATIC_NODE_RETRY) fires before the grace-check, so:
        - abandon_node is never called
        - _connect_failures is never populated for the static IP
        - a CONNECT_RETRY_STATIC warning is emitted
        """
        import logging

        from yascheduler.domain.exceptions import MachineConnectionError
        from yascheduler.domain.model import Node

        static_node = Node(
            ip="10.0.0.9", ncpus=2, cloud=None, username="root", port=22, enabled=True
        )

        orch = make_orchestrator(config_clouds=[])
        # Use a real logger so caplog can capture the CONNECT_RETRY_STATIC
        # warning emitted by the consumer-side guard.
        orch._log = logging.getLogger("orch.test_static_retry")  # type: ignore[method-assign]
        orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=MachineConnectionError("10.0.0.9", "refused")
        )

        with (
            patch(
                "yascheduler.application.orchestrator.abandon_node",
                new=AsyncMock(),
            ) as mock_abandon,
        ):
            await orch._connect_machine_consumer(UMessage("10.0.0.9", static_node))

        mock_abandon.assert_not_called()
        assert "10.0.0.9" not in orch._connect_failures, (
            "static node IP must never enter the failure timer "
            "(consumer-side guard bypasses the grace-check)"
        )
        assert any(
            "CONNECT_RETRY_STATIC" in rec.message
            and "10.0.0.9" in rec.message
            and rec.levelno == logging.WARNING
            for rec in caplog.records
        ), "expected a CONNECT_RETRY_STATIC warning for the static node"

    @pytest.mark.asyncio
    async def test_static_node_past_grace_does_not_abandon(self) -> None:
        """A static node that has been failing >120s is still NOT abandoned.

        Temporal guard: even if the failure timer hypothetically accumulated
        past the 120s conservative fallback, the consumer-side guard fires
        before the grace-check so abandon_node is never reached and the DB
        row is preserved. Mirrors the test_connect_failure_past_grace_triggers_abandon
        pattern in TestConnectMachineConsumerGraceTimer, but with cloud=None
        and patched monotonic timestamps >120s apart.
        """
        from yascheduler.domain.exceptions import MachineConnectionError
        from yascheduler.domain.model import Node

        static_node = Node(
            ip="10.0.0.9", ncpus=2, cloud=None, username="root", port=22, enabled=True
        )

        orch = make_orchestrator(config_clouds=[])
        orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
            side_effect=MachineConnectionError("10.0.0.9", "refused")
        )

        with (
            patch(
                "yascheduler.application.orchestrator.time.monotonic",
                side_effect=[100.0, 250.0],
            ),
            patch(
                "yascheduler.application.orchestrator.abandon_node",
                new=AsyncMock(),
            ) as mock_abandon,
        ):
            await orch._connect_machine_consumer(UMessage("10.0.0.9", static_node))

        mock_abandon.assert_not_called()
        # The DB row is preserved because abandon_node (the only path that
        # removes the yascheduler_nodes row) is structurally unreachable for
        # static nodes — the consumer-side guard returns before the
        # grace-check / abandon block.
        assert "10.0.0.9" not in orch._connect_failures


def _uow_with_nodes(nodes: list) -> AsyncMock:
    """Build a UoW mock whose nodes.list_enabled returns the given nodes."""
    uow = AsyncMock()
    uow.nodes = AsyncMock()
    uow.nodes.list_enabled = AsyncMock(return_value=nodes)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return uow
