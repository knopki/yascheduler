# FILE: tests/unit/test_models.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for TaskStatus, TaskModel, and NodeModel from yascheduler.db.
#   SCOPE: Enum values, model construction, immutability, hash determinism, defaults.
#   DEPENDS: M-DB
#   LINKS: M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_task_status_values - verify TO_DO==0, RUNNING==1, DONE==2, int subclass
#   test_task_status_is_int - verify isinstance(TaskStatus.TO_DO, int)
#   test_taskmodel_construction - verify all fields and TaskStatus converter
#   test_taskmodel_frozen_immutable - verify FrozenInstanceError on mutation
#   test_taskmodel_hash_deterministic - identical fields → equal hashes
#   test_nodemodel_defaults - minimal args → expected defaults
#   test_nodemodel_all_args - full args → all fields match
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial data model unit tests
# END_CHANGE_SUMMARY

import pytest
import attrs

from yascheduler.db import NodeModel, TaskModel, TaskStatus


# START_CONTRACT: test_task_status_values
#   PURPOSE: Verify TaskStatus enum values: TO_DO==0, RUNNING==1, DONE==2.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_task_status_values
def test_task_status_values():
    assert TaskStatus.TO_DO == 0
    assert TaskStatus.RUNNING == 1
    assert TaskStatus.DONE == 2


# START_CONTRACT: test_task_status_is_int
#   PURPOSE: Verify TaskStatus values are instances of int (int subclass).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_task_status_is_int
def test_task_status_is_int():
    assert isinstance(TaskStatus.TO_DO, int)
    assert isinstance(TaskStatus.RUNNING, int)
    assert isinstance(TaskStatus.DONE, int)


# START_CONTRACT: test_taskmodel_construction
#   PURPOSE: Verify TaskModel construction with all fields and TaskStatus converter.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_taskmodel_construction
def test_taskmodel_construction():
    task = TaskModel(
        task_id=1,
        label="test",
        ip="10.0.0.1",
        status=TaskStatus.TO_DO,
        metadata={"k": "v"},
        cloud="az",
    )
    assert task.task_id == 1
    assert task.label == "test"
    assert task.ip == "10.0.0.1"
    assert task.status == TaskStatus.TO_DO
    assert task.metadata == {"k": "v"}
    assert task.cloud == "az"


# START_CONTRACT: test_taskmodel_frozen_immutable
#   PURPOSE: Verify TaskModel is frozen and raises FrozenInstanceError on mutation.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_taskmodel_frozen_immutable
def test_taskmodel_frozen_immutable():
    task = TaskModel(task_id=1, label="test", ip="10.0.0.1", status=TaskStatus.TO_DO)
    with pytest.raises(attrs.exceptions.FrozenInstanceError):
        task.label = "new"  # type: ignore[misc]


# START_CONTRACT: test_taskmodel_hash_deterministic
#   PURPOSE: Verify identical TaskModel fields produce equal hashes.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_taskmodel_hash_deterministic
def test_taskmodel_hash_deterministic():
    t1 = TaskModel(task_id=1, label="test", ip="10.0.0.1", status=TaskStatus.TO_DO)
    t2 = TaskModel(task_id=1, label="test", ip="10.0.0.1", status=TaskStatus.TO_DO)
    assert hash(t1) == hash(t2)


# START_CONTRACT: test_nodemodel_defaults
#   PURPOSE: Verify NodeModel construction with minimal args produces expected defaults.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_nodemodel_defaults
def test_nodemodel_defaults():
    node = NodeModel(ip="10.0.0.1", ncpus=4)
    assert node.ip == "10.0.0.1"
    assert node.ncpus == 4
    assert node.enabled is True
    assert node.cloud is None
    assert node.username == "root"
    assert node.port == 22


# START_CONTRACT: test_nodemodel_all_args
#   PURPOSE: Verify NodeModel construction with all args produces matching field values.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DB
# END_CONTRACT: test_nodemodel_all_args
def test_nodemodel_all_args():
    node = NodeModel(
        ip="10.0.0.1",
        ncpus=4,
        enabled=False,
        cloud="hetzner",
        username="admin",
        port=2222,
    )
    assert node.ip == "10.0.0.1"
    assert node.ncpus == 4
    assert node.enabled is False
    assert node.cloud == "hetzner"
    assert node.username == "admin"
    assert node.port == 2222
