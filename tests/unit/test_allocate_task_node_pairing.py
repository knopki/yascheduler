# FILE: tests/unit/test_allocate_task_node_pairing.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for the task-allocated-node-id application-layer changes: _find_free_machines session↔Node pairing and _try_start_on_machine node_id logging.
#   SCOPE: _find_free_machines returns list[tuple[MachineSession, Node]] paired by ip (dup-IP collapses to last-wins); _try_start_on_machine takes (session, node), calls allocate_to(node), logs node_id=%s.
#   DEPENDS: M-APPLICATION-ALLOCATE
#   LINKS: M-APPLICATION-ALLOCATE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestFindFreeMachinesNodePairing - _find_free_machines pairs sessions with Nodes by ip; dup-IP collapses
#   TestTryStartOnMachineNodeIdLogging - _try_start_on_machine log lines include node_id=%s alongside ip=%s
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - task-allocated-node-id: extract _find_free_machines pairing + _try_start_on_machine node_id-logging tests from test_application_use_cases.py into a focused module (the parent file exceeded the 1000-line GRACE-lite hard limit after the additions).
# END_CHANGE_SUMMARY

import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.allocate_task import (
    _find_free_machines,
    _try_start_on_machine,
)
from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.uow import AbstractUnitOfWork
from yascheduler.domain.model import (
    Engine,
    Node,
    NodeId,
    Task,
    TaskContext,
    TaskId,
    TaskStatus,
)


class TestFindFreeMachinesNodePairing:
    """_find_free_machines returns list[tuple[MachineSession, Node]] paired by ip."""

    async def test_pairs_session_with_node_by_ip(self, engine: Engine) -> None:
        """Two enabled nodes (distinct ips) + two matching sessions → paired correctly."""
        from yascheduler.domain.model import ConnectedMachine, MachineState

        node_a = Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4, enabled=True)
        node_b = Node(node_id=NodeId(2), ip="10.0.0.2", ncpus=4, enabled=True)

        m_a = MagicMock(spec=ConnectedMachine)
        m_a.node_id = NodeId(1)
        m_a.ip = "10.0.0.1"
        m_a.state = MachineState.FREE
        m_a.free_since = time.monotonic()
        m_b = MagicMock(spec=ConnectedMachine)
        m_b.node_id = NodeId(2)
        m_b.ip = "10.0.0.2"
        m_b.state = MachineState.FREE
        m_b.free_since = time.monotonic()
        session_a = SimpleNamespace(machine=m_a, ip="10.0.0.1")
        session_b = SimpleNamespace(machine=m_b, ip="10.0.0.2")

        repository = MagicMock()
        repository.list_free = MagicMock(return_value=[session_a, session_b])

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.list_by_status = AsyncMock(return_value=[])  # nothing busy
        uow.nodes = AsyncMock()
        uow.nodes.list_enabled = AsyncMock(return_value=[node_a, node_b])
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        pairs = await _find_free_machines(engine, uow_factory, repository)

        assert len(pairs) == 2
        # Each session paired with the matching Node by ip.
        ips_to_nodes = {s.ip: n for s, n in pairs}
        assert ips_to_nodes == {"10.0.0.1": node_a, "10.0.0.2": node_b}
        # Each Node carries node_id.
        for _s, n in pairs:
            assert isinstance(n.node_id, NodeId)

    async def test_dup_ip_collapses_to_one_node(self, engine: Engine) -> None:
        """Dup-IP enabled nodes collapse to one Node in nodes_by_ip (last wins).

        Documents the same-ambiguity-as-today behavior: the prior
        ``enabled_ips = {n.ip}`` set membership collapsed duplicates too; this
        change records allocated_node_id from one of the duplicates (arbitrary).
        Full disambiguation lands with Surface A.
        """
        from yascheduler.domain.model import ConnectedMachine, MachineState

        node_first = Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4, enabled=True)
        node_last = Node(node_id=NodeId(2), ip="10.0.0.1", ncpus=4, enabled=True)

        m = MagicMock(spec=ConnectedMachine)
        m.node_id = NodeId(2)
        m.ip = "10.0.0.1"
        m.state = MachineState.FREE
        m.free_since = time.monotonic()
        session = SimpleNamespace(machine=m, ip="10.0.0.1")

        repository = MagicMock()
        repository.list_free = MagicMock(return_value=[session])

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes = AsyncMock()
        # list_enabled returns both dup-IP nodes; dict comprehension last-wins.
        uow.nodes.list_enabled = AsyncMock(return_value=[node_first, node_last])
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        pairs = await _find_free_machines(engine, uow_factory, repository)

        # One pair (one session, one ip); the Node is the last-wins one.
        assert len(pairs) == 1
        _s, paired_node = pairs[0]
        assert paired_node.ip == "10.0.0.1"
        assert paired_node.node_id in (NodeId(1), NodeId(2))


class TestTryStartOnMachineNodeIdLogging:
    """_try_start_on_machine log lines include node_id=%s alongside ip=%s."""

    async def test_logs_node_id(
        self, engine: Engine, caplog: pytest.LogCaptureFixture
    ) -> None:
        from yascheduler.domain.model import ConnectedMachine, MachineState

        node = Node(node_id=NodeId(7), ip="10.0.0.1", ncpus=4, enabled=True)
        m = MagicMock(spec=ConnectedMachine)
        m.ip = "10.0.0.1"
        m.state = MachineState.FREE
        m.free_since = time.monotonic()
        session = SimpleNamespace(machine=m, ip="10.0.0.1")

        task = Task(
            task_id=TaskId(1),
            label="t",
            context=TaskContext(engine="test_engine"),
            status=TaskStatus.TO_DO,
        )

        operations = MagicMock()
        operations.start_occupancy_check = MagicMock()
        start_on_machine = AsyncMock(return_value=True)
        tracker = MagicMock(spec=AllocationTracker)

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        with caplog.at_level(
            logging.DEBUG,
            logger="yascheduler.application.allocate_task",
        ):
            result = await _try_start_on_machine(
                session,
                node,
                engine,
                task,
                operations,
                uow_factory,
                start_on_machine,
                tracker,
            )

        assert result is True
        # The allocation log line carries node_id alongside ip.
        alloc_lines = [
            r.getMessage() for r in caplog.records if "[ALLOCATED]" in r.getMessage()
        ]
        assert alloc_lines, "expected an [ALLOCATED] debug log line"
        line = alloc_lines[0]
        assert "ip=10.0.0.1" in line
        assert "node_id=7" in line
        # tracker.discard called with the task_id
        tracker.discard.assert_called_once_with(task.task_id)
