# FILE: tests/integration/test_never_connected_node_abandon.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Integration tests for the never-connected-node abandon path against real PostgreSQL.
#   SCOPE: Real-DB verification that _connect_machine_consumer -> abandon_node removes the yascheduler_nodes row + releases the tracker entry, and that _connect_grace_for resolves per-cloud via real ConfigCloud DTOs.
#   DEPENDS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE, M-PERSISTENCE-UOW, M-CLOUD-CONFIGS
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE, M-PERSISTENCE-UOW
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_never_connected_node_abandoned_and_task_reallocated - Real PostgreSQL: dead node + TO_DO task + tracker entry → consumer abandon → row removed + tracker released + task still TO_DO (re-allocatable)
#   test_connect_grace_lookup_uses_cloud_prefix                - Orchestrator wired with the 4 real ConfigCloud DTOs resolves per-cloud connect_grace via prefix match
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - task-schema-and-entity-cleanup: removed allocated_ip=dead_ip from NewTask constructor (field removed); assert matching[0].allocated_node_id == persisted_node.node_id instead of allocated_ip.
#   PREVIOUS_CHANGE: v1.1.0 - cloud-port-node-arg: assert orch._clouds.deallocate awaited with persisted_node (was ("hetzner", dead_ip)).
# END_CHANGE_SUMMARY
"""Integration tests for the never-connected-node abandon path.

Two tests:

1. `test_never_connected_node_abandoned_and_task_reallocated` — against real
   PostgreSQL, seeds a never-connected cloud node + a stuck TO_DO task whose
   `allocated_ip` matches + a tracker entry pinning that task. Drives
   `_connect_machine_consumer` past `connect_grace` with a mocked gateway
   (raises `MachineConnectionError`) and mocked cloud provisioner. Asserts:

   - the `yascheduler_nodes` row is removed from the DB
   - the cloud-VM delete stub was called
   - the task's AllocationTracker entry is discarded
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
    TaskContext,
    TaskStatus,
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
    operations = MagicMock()

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
        operations=operations,
        engines=engines,
        log=MagicMock(),
        config_clouds=config_clouds,
        local_tasks_dir=Path("/tmp"),
        allocation_tracker=tracker,
        active_clouds=[],
        allocation_lock=asyncio.Lock(),
        list_private_keys_fn=lambda _keys_dir: [],
    )


# START_CONTRACT: test_never_connected_node_abandoned_and_task_reallocated
#   PURPOSE: Verify the connect-machine consumer abandon path removes the DB row, releases the tracker, and leaves the task re-allocatable against real PostgreSQL.
#   INPUTS: { uow_factory: Callable[[], PostgresUnitOfWork] }
#   OUTPUTS: { None - assertions only }
#   SIDE_EFFECTS: Inserts a node + a TO_DO task + a tracker entry; drives _connect_machine_consumer past connect_grace; verifies post-abandon DB state.
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE, M-PERSISTENCE-UOW
# END_CONTRACT: test_never_connected_node_abandoned_and_task_reallocated
async def test_never_connected_node_abandoned_and_task_reallocated(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Real-DB abandon: dead node row removed, cloud delete called, tracker released, task still TO_DO."""
    # Hetzner has connect_grace=60; we'll advance monotonic past it in one cycle.
    config_clouds = [ConfigCloudHetzner()]

    # START_BLOCK_SEED
    # Use a TEST-NET-1 address so the gateway mock's failure is realistic.
    dead_ip = "192.0.2.7"
    node = NewNode(
        ip=dead_ip,
        ncpus=2,
        cloud="hetzner",
        username="root",
        port=22,
        enabled=True,
    )
    async with uow_factory() as uow:
        persisted_node = await uow.nodes.insert(node)
        inserted_task = await uow.tasks.insert(
            NewTask(
                label="stuck",
                context=TaskContext(engine="test_engine"),
                status=TaskStatus.TO_DO,
                allocated_node_id=persisted_node.node_id,
            )
        )
        await uow.commit()
    task_id = inserted_task.task_id

    tracker = AllocationTracker()
    assert tracker.add(task_id) is True
    # END_BLOCK_SEED

    orch = _build_orchestrator(
        uow_factory, config_clouds=config_clouds, tracker=tracker
    )
    # Simulate SSH connect always failing for the dead IP.
    orch._repository.connect = AsyncMock(  # type: ignore[method-assign]
        side_effect=MachineConnectionError(dead_ip, "connection refused")
    )

    # START_BLOCK_DRIVE_PAST_GRACE
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
            UMessage(persisted_node.node_id, persisted_node)
        )
    # END_BLOCK_DRIVE_PAST_GRACE

    # START_BLOCK_VERIFY_DB_ROW_REMOVED
    async with uow_factory() as uow:
        removed_node = await uow.nodes.get_by_id(persisted_node.node_id)
    assert removed_node is None, "yascheduler_nodes row must be removed after abandon"
    # END_BLOCK_VERIFY_DB_ROW_REMOVED

    # START_BLOCK_VERIFY_CLOUD_DELETE_CALLED
    orch._clouds.deallocate.assert_awaited_once_with(persisted_node)  # type: ignore[attr-defined]
    # END_BLOCK_VERIFY_CLOUD_DELETE_CALLED

    # START_BLOCK_VERIFY_TRACKER_RELEASED
    assert task_id not in tracker, (
        "tracker slot must be discarded so the task re-allocates"
    )
    # END_BLOCK_VERIFY_TRACKER_RELEASED

    # START_BLOCK_VERIFY_TASK_REALLOCATABLE
    async with uow_factory() as uow:
        todos = await uow.tasks.list_by_status({TaskStatus.TO_DO})
    matching = [t for t in todos if t.task_id == task_id]
    assert len(matching) == 1, (
        "task must remain TO_DO so the allocate producer re-yields it"
    )
    # The node was removed (abandoned), so the FK ON DELETE SET NULL
    # nulled allocated_node_id — the task is re-allocatable.
    assert matching[0].allocated_node_id is None
    # END_BLOCK_VERIFY_TASK_REALLOCATABLE


# START_CONTRACT: test_connect_grace_lookup_uses_cloud_prefix
#   PURPOSE: Verify _connect_grace_for resolves per-cloud via ConfigCloud.prefix against real DTOs.
#   INPUTS: { uow_factory: Callable[[], PostgresUnitOfWork] }
#   OUTPUTS: { None - assertions only }
#   SIDE_EFFECTS: None — pure lookup against real ConfigCloud DTOs wired into the Orchestrator.
#   LINKS: M-APPLICATION-ORCHESTRATOR, M-CLOUD-CONFIGS
# END_CONTRACT: test_connect_grace_lookup_uses_cloud_prefix
async def test_connect_grace_lookup_uses_cloud_prefix(
    uow_factory: Callable[[], PostgresUnitOfWork],
) -> None:
    """Orchestrator wired with real ConfigCloud DTOs resolves per-cloud connect_grace by prefix."""
    config_clouds = [
        ConfigCloudHetzner(),
        ConfigCloudUpcloud(),
        ConfigCloudAzure(),
        ConfigCloudVastAI(),
    ]
    orch = _build_orchestrator(uow_factory, config_clouds=config_clouds)

    # Hetzner matches its prefix → DTO default 60.
    assert orch._connect_grace_for("hetzner") == 60
    # Azure's actual prefix is "az" → DTO default 120.
    assert orch._connect_grace_for("az") == 120
    # Upcloud and VastAI also resolve correctly from the same instance.
    assert orch._connect_grace_for("upcloud") == 60
    assert orch._connect_grace_for("vastai") == 120
