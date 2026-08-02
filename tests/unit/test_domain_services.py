# region MODULE_CONTRACT
# PURPOSE: Unit tests for domain services: match_task_to_node.
# SCOPE: Test allocation logic: compatible machines, busy filtering, empty lists, ordering.
# KEYWORDS: match_task_to_node, allocation logic, compatible machines
# endregion MODULE_CONTRACT

from datetime import datetime

from yascheduler.domain.model import (
    ConnectedMachine,
    Engine,
    MachineState,
    NodeId,
    Task,
    TaskId,
    Todo,
)
from yascheduler.domain.services import match_task_to_node


def _make_task(task_id: int = 1) -> Task:
    """Build a Task with minimal defaults for match_task_to_node tests."""
    return Task(
        task_id=TaskId(task_id),
        label="test",
        engine="fleur",
        state=Todo(),
        webhook_url=None,
        webhook_custom_params={},
        extra={},
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )


def test_match_found() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(node_id=NodeId(1), platform="linux")
    result = match_task_to_node(task, engine, [m1])
    assert result is m1


def test_no_compatible_machine() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(node_id=NodeId(1), platform="windows")
    result = match_task_to_node(task, engine, [m1])
    assert result is None


def test_all_busy_machines() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(
        node_id=NodeId(1),
        platform="linux",
        state=MachineState.BUSY,
    )
    m2 = ConnectedMachine(
        node_id=NodeId(2),
        platform="linux",
        state=MachineState.BUSY,
    )
    result = match_task_to_node(task, engine, [m1, m2])
    assert result is None


def test_empty_list() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    result = match_task_to_node(task, engine, [])
    assert result is None


def test_multiple_compatible_returns_first() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(node_id=NodeId(1), platform="linux")
    m2 = ConnectedMachine(node_id=NodeId(2), platform="linux")
    result = match_task_to_node(task, engine, [m1, m2])
    assert result is m1
    assert result is not m2


def test_multiple_machines_skips_busy() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(
        node_id=NodeId(1),
        platform="linux",
        state=MachineState.BUSY,
    )
    m2 = ConnectedMachine(node_id=NodeId(2), platform="linux")
    result = match_task_to_node(task, engine, [m1, m2])
    assert result is m2
