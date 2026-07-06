# FILE: tests/unit/test_domain_services.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain services: match_task_to_node.
#   SCOPE: Test allocation logic: compatible machines, busy filtering, empty lists, ordering.
#   DEPENDS: none
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_match_found - One compatible FREE machine returns it
#   test_no_compatible_machine - Zero machines matching platform returns None
#   test_all_busy_machines - All machines BUSY returns None
#   test_empty_list - Empty free_machines returns None
#   test_multiple_compatible_returns_first - Returns first compatible, not second
#   test_multiple_machines_skips_busy - Skips BUSY, returns first FREE compatible
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - drop-task-context-entity: replace TaskContext with flat Task fields; remove TaskContext imports.
#   PREVIOUS_CHANGE: v1.0.0 - Initial domain service unit tests
# END_CHANGE_SUMMARY

from datetime import datetime

from yascheduler.domain.model import (
    ConnectedMachine,
    Engine,
    MachineState,
    NodeId,
    Task,
    TaskId,
)
from yascheduler.domain.services import match_task_to_node


def _make_task(task_id: int = 1) -> Task:
    """Build a Task with minimal defaults for match_task_to_node tests."""
    return Task(
        task_id=TaskId(task_id),
        label="test",
        engine="fleur",
        remote_folder=None,
        local_folder=None,
        webhook_url=None,
        webhook_custom_params={},
        error=None,
        extra={},
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )


# START_CONTRACT: test_match_found
#   PURPOSE: When one compatible FREE machine is available, return it.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_match_found
def test_match_found() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(node_id=NodeId(1), ip="10.0.0.1", platform="linux", ncpus=4)
    result = match_task_to_node(task, engine, [m1])
    assert result is m1


# START_CONTRACT: test_no_compatible_machine
#   PURPOSE: When no machine's platform matches the engine platforms, return None.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_no_compatible_machine
def test_no_compatible_machine() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(node_id=NodeId(1), ip="10.0.0.1", platform="windows", ncpus=4)
    result = match_task_to_node(task, engine, [m1])
    assert result is None


# START_CONTRACT: test_all_busy_machines
#   PURPOSE: When all machines have state=BUSY, return None (is_compatible filters them out).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_all_busy_machines
def test_all_busy_machines() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(
        node_id=NodeId(1),
        ip="10.0.0.1",
        platform="linux",
        ncpus=4,
        state=MachineState.BUSY,
    )
    m2 = ConnectedMachine(
        node_id=NodeId(2),
        ip="10.0.0.2",
        platform="linux",
        ncpus=8,
        state=MachineState.BUSY,
    )
    result = match_task_to_node(task, engine, [m1, m2])
    assert result is None


# START_CONTRACT: test_empty_list
#   PURPOSE: When free_machines is empty, return None.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_empty_list
def test_empty_list() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    result = match_task_to_node(task, engine, [])
    assert result is None


# START_CONTRACT: test_multiple_compatible_returns_first
#   PURPOSE: When multiple machines are FREE and compatible, ensure the first one is returned, not the second.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_multiple_compatible_returns_first
def test_multiple_compatible_returns_first() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(node_id=NodeId(1), ip="10.0.0.1", platform="linux", ncpus=4)
    m2 = ConnectedMachine(node_id=NodeId(2), ip="10.0.0.2", platform="linux", ncpus=8)
    result = match_task_to_node(task, engine, [m1, m2])
    assert result is m1
    assert result is not m2


# START_CONTRACT: test_multiple_machines_skips_busy
#   PURPOSE: When first machine is BUSY and second is FREE+compatible, skip the busy one and return the second.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_multiple_machines_skips_busy
def test_multiple_machines_skips_busy() -> None:
    task = _make_task()
    engine = Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))
    m1 = ConnectedMachine(
        node_id=NodeId(1),
        ip="10.0.0.1",
        platform="linux",
        ncpus=4,
        state=MachineState.BUSY,
    )
    m2 = ConnectedMachine(node_id=NodeId(2), ip="10.0.0.2", platform="linux", ncpus=8)
    result = match_task_to_node(task, engine, [m1, m2])
    assert result is m2
