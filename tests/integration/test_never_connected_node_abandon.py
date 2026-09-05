"""Integration tests for the never-connected-node abandon path.

Two tests:

1. `test_never_connected_node_abandoned_and_task_reallocated` — against real
   PostgreSQL, seeds a never-connected cloud node + a stuck TO_DO task
   (persisted with `allocated_node_id = NULL`, the real in-flight
   cloud-allocation shape) + a tracker entry pinning that task. Drives
   `_connect_machine_consumer` past `connect_grace` with a mocked gateway
   (raises `MachineConnectionError`) and mocked cloud provisioner. Asserts:

    - the `yascheduler_nodes` row is removed from the DB
    - the cloud-VM delete stub was called
    - the tracker entry for the task is released (discard_by_node closes
      the leak — the task-to-node link is seeded via set_node, mirroring
      the real allocate_task flow)
    - the task remains in TO_DO and is returned by `list_by_status({TO_DO})`,
      i.e. it is ready for re-allocation on the next producer cycle

   The "second-VM-with-working-SSH → RUNNING" portion of the spec scenario is
   exercised end-to-end by the unit tests + the existing e2e `test_full_cycle`;
   this integration test focuses on the DB-backed abandon + re-allocate
   readiness contract.

2. `test_connect_grace_lookup_uses_cloud_prefix` — the orchestrator wired with
   the 4 real ConfigCloud DTOs resolves `_connect_grace_for("hetzner") == 60`
   and `_connect_grace_for("az") == 120` (Azure's actual prefix). Hetzner and
   Azure are in `config_clouds` together so a single Orchestrator instance
   resolves both per-cloud windows correctly.
"""
# region MODULE_CONTRACT
# PURPOSE: Integration tests for the never-connected-node abandon path against real PostgreSQL.
# SCOPE: Real-DB verification that _connect_machine_consumer -> abandon_node removes the yascheduler_nodes row + releases the tracker entry, and that _connect_grace_for resolves per-cloud via real ConfigCloud DTOs.
# KEYWORDS: abandon_node, never-connected, Postgres, traverse
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.orchestrator import Orchestrator
from yascheduler.application.queue import UMessage
from yascheduler.domain import Engine, EngineRepository, LocalSettings, RemoteDefaults
from yascheduler.domain.exceptions import MachineConnectionError
from yascheduler.domain.model import (
    NewNode,
    NewTask,
    NodeId,
    TaskStatus,
    allocated_node_id_of,
)
from yascheduler.infra.cloud.cloud_configs import (
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigCloudVastAI,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.infra.persistence.postgres_uow import PostgresUnitOfWork


def _build_orchestrator(
    uow_factory: Callable[[], PostgresUnitOfWork],
    config_clouds: list | None = None,
    tracker: AllocationTracker | None = None,
) -> Orchestrator:
    """Build a real Orchestrator against the real UoW factory; gateway + clouds mocked."""
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

    engine = MagicMock(spec=Engine, sleep_interval=0)
    engine.name = "test_engine"
    engines = MagicMock(spec=EngineRepository)
    engines.values.return_value = [engine]

    repository = MagicMock()
    repository.__len__ = MagicMock(return_value=0)
    task_deployer = MagicMock()
    output_downloader = MagicMock()
    occupancy_checker = MagicMock()

    if tracker is None:
        tracker = AllocationTracker()
    if config_clouds is None:
        config_clouds = []

    return Orchestrator(
        local_settings=local,
        remote_defaults=remote,
        uow_factory=uow_factory,
        clouds=AsyncMock(),
        repository=repository,
        task_deployer=task_deployer,
        output_downloader=output_downloader,
        occupancy_checker=occupancy_checker,
        engines=engines,
        config_clouds=config_clouds,
        local_tasks_dir=Path("/tmp"),
        allocation_tracker=tracker,
        active_clouds=[],
        allocation_lock=asyncio.Lock(),
        list_private_keys_fn=lambda _keys_dir: [],
    )


async def test_never_connected_node_abandoned_and_task_reallocated(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Real-DB abandon: dead node row removed, cloud delete called, task still TO_DO + re-allocatable."""
    # Hetzner has connect_grace=60; we'll advance monotonic past it in one cycle.
    config_clouds = [ConfigCloudHetzner(token="test-token")]

    # Use a TEST-NET-1 address so the gateway mock's failure is realistic.
    # The task is persisted as TO_DO with allocated_node_id = NULL — the real
    # persisted shape during in-flight cloud allocation. The in-memory
    # AllocationTracker (seeded below with task_id) holds the binding; the DB
    # never sees TO_DO + allocated_node_id (that combination is now rejected
    # by the task_status_field_invariants CHECK on yascheduler_tasks).
    dead_ip = "192.0.2.7"
    node = NewNode(
        hostname=dead_ip,
        ncpus=2,
        cloud="hetzner",
        username="root",
        port=22,
        enabled=True,
    )
    async with uow_factory() as uow:
        persisted_node = await uow.nodes.insert(node)
        inserted_task = await uow.tasks.insert(
            NewTask(label="stuck", engine="test_engine"),
        )
        await uow.commit()
    task_id = inserted_task.task_id

    tracker = AllocationTracker()
    # Pre-seed the tracker mirroring the real production flow: allocate_task
    # calls tracker.add(task_id) at the dedup gate (before the tmp node
    # exists), then tracker.set_node(task_id, tmp_node_id) after the tmp
    # node is inserted. The persisted node here IS the tmp node (enabled=True
    # for the test so the connect-machine consumer yields it); set_node
    # links the task to it so abandon_node's discard_by_node can release it.
    assert tracker.add(task_id) is True
    tracker.set_node(task_id, persisted_node.node_id)

    orch = _build_orchestrator(
        uow_factory,
        config_clouds=config_clouds,
        tracker=tracker,
    )
    # Simulate SSH connect always failing for the dead IP.
    orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
        side_effect=MachineConnectionError(NodeId(999), dead_ip, "connection refused"),
    )

    # Drive the failure timer past connect_grace robustly. Pre-seed first_seen
    # and pin monotonic to a constant past-grace value via return_value (never
    # exhausts). Both a side_effect list AND an order-sensitive callable break
    # under Python 3.12, whose asyncio calls time.monotonic during the await
    # chain: it would drain a list (StopIteration) or consume the callable's
    # "first" value, shifting first_seen so the consumer sees age=0 → retry.
    # Pre-seeding decouples first_seen from any call: age = 200 - 100 = 100s
    # >= grace = 60s → abandon fires.
    orch._connect_failures[persisted_node.node_id] = 100.0

    with patch(
        "yascheduler.application.orchestrator.time.monotonic",
        return_value=200.0,
    ):
        await orch._connect_machine_consumer(
            UMessage(persisted_node.node_id, persisted_node),
        )

    async with uow_factory() as uow:
        removed_node = await uow.nodes.get_by_id(persisted_node.node_id)
    assert removed_node is None, "yascheduler_nodes row must be removed after abandon"

    orch._clouds.deallocate.assert_awaited_once_with(persisted_node)  # type: ignore[attr-defined]

    # The leak is closed: abandon_node calls tracker.discard_by_node(node_id),
    # which removes the entry linked to the abandoned node. The seed called
    # tracker.set_node(task_id, persisted_node.node_id), so the entry is
    # linked and discard_by_node removes it.
    assert task_id not in tracker

    async with uow_factory() as uow:
        todos = await uow.tasks.list_by_status({TaskStatus.TO_DO})
    matching = [t for t in todos if t.task_id == task_id]
    assert len(matching) == 1, (
        "task must remain TO_DO so the allocate producer re-yields it"
    )
    # The task was persisted with allocated_node_id = NULL (the real in-flight
    # cloud-allocation shape), and the abandoned node row is gone — so the
    # task is re-allocatable.
    assert allocated_node_id_of(matching[0]) is None


async def test_connect_grace_lookup_uses_cloud_prefix(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Orchestrator wired with real ConfigCloud DTOs resolves per-cloud connect_grace by prefix."""
    config_clouds = [
        ConfigCloudHetzner(token="test-token"),
        ConfigCloudUpcloud(login="test", password="test"),
        ConfigCloudAzure(
            tenant_id="test-tid",
            client_id="test-cid",
            client_secret="test-secret",
            subscription_id="test-sub",
        ),
        ConfigCloudVastAI(api_key="test-key"),
    ]
    orch = _build_orchestrator(uow_factory, config_clouds=config_clouds)

    # Hetzner matches its prefix → DTO default 60.
    assert orch._connect_grace_for("hetzner") == 60
    # Azure's actual prefix is "az" → DTO default 120.
    assert orch._connect_grace_for("az") == 120
    # Upcloud and VastAI also resolve correctly from the same instance.
    assert orch._connect_grace_for("upcloud") == 60
    assert orch._connect_grace_for("vastai") == 300
