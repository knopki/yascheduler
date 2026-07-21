# region MODULE_CONTRACT
# PURPOSE: Unit tests for domain entities: TaskStatus, MachineState, ProcessResult, Engine, Task, Node, ConnectedMachine.
# SCOPE: Enum values, dataclass defaults/frozen semantics, Engine validation, Task lifecycle methods (run/reject/complete/fail/abandon), ConnectedMachine state transitions, materialize_task, Task.error column format contract, public events field.
# KEYWORDS: TaskStatus, MachineState, ConnectedMachine, Engine, Task lifecycle
# endregion MODULE_CONTRACT

import time
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from yascheduler.domain.events import (
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
from yascheduler.domain.exceptions import (
    MachineBusyError,
    MissingInputFileError,
    TaskNotRunningError,
    TaskNotTodoError,
)
from yascheduler.domain.model import (
    ConnectedMachine,
    Engine,
    MachineState,
    NewNode,
    NewTask,
    Node,
    NodeId,
    NodeStatus,
    ProcessResult,
    Task,
    TaskId,
    TaskStatus,
    materialize_task,
)

_DT = datetime(2025, 1, 1)


def _node(node_id: int = 7, hostname: str = "10.0.0.1") -> Node:
    """Construct a minimal Node for allocate_to tests."""
    return Node(node_id=NodeId(node_id), hostname=hostname, ncpus=4)


def _make_task(**overrides: object) -> Task:
    """Build a Task with typed fields; all 11 required fields supplied."""
    base: dict[str, object] = {
        "task_id": TaskId(1),
        "label": "test",
        "engine": "cp2k",
        "remote_folder": None,
        "local_folder": None,
        "webhook_url": None,
        "webhook_custom_params": {},
        "error": None,
        "extra": {},
        "created_at": _DT,
        "updated_at": _DT,
    }
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


class TestTaskStatus:
    def test_values(self) -> None:
        assert TaskStatus.TO_DO == 0
        assert TaskStatus.RUNNING == 1
        assert TaskStatus.DONE == 2

    def test_is_int(self) -> None:
        assert isinstance(TaskStatus.TO_DO, int)

    def test_members(self) -> None:
        assert TaskStatus.TO_DO is TaskStatus(0)
        assert TaskStatus.RUNNING is TaskStatus(1)
        assert TaskStatus.DONE is TaskStatus(2)


class TestMachineState:
    def test_free_not_equal_busy(self) -> None:
        assert MachineState.FREE != MachineState.BUSY

    def test_members(self) -> None:
        assert MachineState.FREE is MachineState(1)
        assert MachineState.BUSY is MachineState(2)


class TestProcessResult:
    def test_defaults(self) -> None:
        r = ProcessResult(exit_code=0)
        assert r.exit_code == 0
        assert r.stdout == ""
        assert r.stderr == ""

    def test_all_fields(self) -> None:
        r = ProcessResult(exit_code=1, stdout="out", stderr="err")
        assert r.exit_code == 1
        assert r.stdout == "out"
        assert r.stderr == "err"


class TestEngine:
    def test_validate_inputs_passes_when_all_present(self) -> None:
        engine = Engine(name="cp2k", spawn="cp2k", input_files=("inp", "xyz"))
        engine.validate_inputs({"inp": "content", "xyz": "content"})  # no exception

    def test_validate_inputs_raises_when_file_missing(self) -> None:
        engine = Engine(name="cp2k", spawn="cp2k", input_files=("inp", "xyz"))
        with pytest.raises(MissingInputFileError) as exc_info:
            engine.validate_inputs({"inp": "content"})
        assert "xyz" in str(exc_info.value)
        assert "cp2k" in str(exc_info.value)

    def test_validate_inputs_no_input_files(self) -> None:
        engine = Engine(name="cp2k", spawn="cp2k")
        engine.validate_inputs({})  # no exception


class TestTask:
    def make_task(self, **overrides: object) -> Task:
        return _make_task(**overrides)

    def test_construction_default_status(self) -> None:
        task = self.make_task()
        assert task.task_id == TaskId(1)
        assert task.label == "test"
        assert task.engine == "cp2k"
        assert task.status == TaskStatus.TO_DO
        assert task.allocated_node_id is None
        assert not hasattr(task, "allocated_ip")
        assert isinstance(task.created_at, datetime)
        assert isinstance(task.updated_at, datetime)

    def test_immutability(self) -> None:
        task = self.make_task()
        with pytest.raises(FrozenInstanceError):
            task.status = TaskStatus.RUNNING  # type: ignore[misc]

    def test_run(self) -> None:
        task = self.make_task()
        running = task.run(NodeId(7), "/r")
        assert running.status == TaskStatus.RUNNING
        assert running.allocated_node_id == NodeId(7)
        assert running.remote_folder == "/r"
        assert running.task_id == task.task_id
        assert len(running.events) == 1
        evt = running.events[0]
        assert isinstance(evt, TaskAllocated)
        assert evt.node_id == NodeId(7)
        assert evt.engine_name == "cp2k"

    def test_run_on_non_todo_raises(self) -> None:
        task = self.make_task(status=TaskStatus.RUNNING)
        with pytest.raises(TaskNotTodoError) as exc_info:
            task.run(NodeId(7), "/r")
        assert "1" in str(exc_info.value)

    def test_complete_on_running(self) -> None:
        task = self.make_task()
        running = task.run(NodeId(7), "/r")
        done = running.complete(local_folder="/l", remote_folder="/r")
        assert done.status == TaskStatus.DONE
        assert done.error is None
        assert done.local_folder == "/l"
        assert done.remote_folder == "/r"
        assert len(done.events) == 2
        assert isinstance(done.events[1], TaskCompleted)
        assert done.events[1].local_folder == "/l"

    def test_complete_on_todo_raises(self) -> None:
        task = self.make_task()
        with pytest.raises(TaskNotRunningError) as exc_info:
            task.complete(local_folder="/l", remote_folder="/r")
        assert "1" in str(exc_info.value)

    def test_fail_on_running(self) -> None:
        task = self.make_task()
        running = task.run(NodeId(7), "/r")
        failed = running.fail("out of memory", local_folder="/l", remote_folder="/r")
        assert failed.status == TaskStatus.DONE
        assert failed.error == "out of memory"
        assert failed.local_folder == "/l"
        assert failed.remote_folder == "/r"
        assert len(failed.events) == 2
        assert isinstance(failed.events[1], TaskFailed)
        assert failed.events[1].reason == "out of memory"

    def test_fail_on_todo_raises(self) -> None:
        task = self.make_task()
        with pytest.raises(TaskNotRunningError) as exc_info:
            task.fail("reason", local_folder="/l", remote_folder="/r")
        assert "1" in str(exc_info.value)

    def test_reject_on_todo(self) -> None:
        task = self.make_task()
        rejected = task.reject("unsupported engine")
        assert rejected.status == TaskStatus.DONE
        assert rejected.error == "unsupported engine"
        assert len(rejected.events) == 1
        assert isinstance(rejected.events[0], TaskFailed)
        assert rejected.events[0].reason == "unsupported engine"

    def test_reject_on_running_raises(self) -> None:
        task = self.make_task()
        running = task.run(NodeId(7), "/r")
        with pytest.raises(TaskNotTodoError):
            running.reject("reason")

    def test_abandon_with_node_id(self) -> None:
        task = self.make_task()
        running = task.run(NodeId(7), "/r")
        abandoned = running.abandon(NodeId(7))
        assert abandoned.status == TaskStatus.DONE
        assert abandoned.error == "node is gone"
        assert len(abandoned.events) == 2
        assert isinstance(abandoned.events[1], TaskAbandoned)
        assert abandoned.events[1].node_id == NodeId(7)

    def test_abandon_none_no_event(self) -> None:
        task = self.make_task()
        running = task.run(NodeId(7), "/r")
        abandoned = running.abandon(None)
        assert abandoned.status == TaskStatus.DONE
        assert abandoned.error == "node is gone"
        # No TaskAbandoned event when node_id is None
        assert len(abandoned.events) == 1  # only the TaskAllocated from run

    def test_abandon_on_todo_raises(self) -> None:
        task = self.make_task()
        with pytest.raises(TaskNotRunningError) as exc_info:
            task.abandon(NodeId(7))
        assert "1" in str(exc_info.value)


class TestNodeStatus:
    def test_other_value(self) -> None:
        """NodeStatus.OTHER is defined with value 'OTHER'."""
        assert NodeStatus.OTHER == "OTHER"
        assert NodeStatus.OTHER.value == "OTHER"

    def test_is_strenum(self) -> None:
        """NodeStatus members are str instances (StrEnum)."""
        assert isinstance(NodeStatus.OTHER, str)

    def test_name_lookup(self) -> None:
        """NodeStatus['OTHER'] returns NodeStatus.OTHER (name-based lookup)."""
        assert NodeStatus["OTHER"] is NodeStatus.OTHER


class TestNode:
    def test_defaults(self) -> None:
        node = Node(node_id=NodeId(1), hostname="10.0.0.1", ncpus=4)
        assert node.node_id == NodeId(1)
        assert node.hostname == "10.0.0.1"
        assert node.ncpus == 4
        assert node.enabled is True
        assert node.cloud is None
        assert node.username == "root"
        assert node.port == 22
        assert node.jump_host is None
        assert node.jump_port == 22
        assert node.jump_username == "root"
        assert node.external_id is None
        assert node.status == NodeStatus.OTHER
        assert isinstance(node.created_at, datetime)
        assert isinstance(node.updated_at, datetime)

    def test_ncpus_none_means_discover_at_spawn(self) -> None:
        """Node with ncpus=None: orchestrator discovers at spawn via session cache."""
        node = Node(node_id=NodeId(1), hostname="10.0.0.1", ncpus=None)
        assert node.ncpus is None

    def test_full_construction(self) -> None:
        node = Node(
            node_id=NodeId(7),
            hostname="10.0.0.1",
            ncpus=8,
            enabled=False,
            cloud="hetzner",
            username="admin",
            port=2222,
            jump_host="jump.example.com",
            jump_port=2222,
            jump_username="jumpuser",
            external_id="ext-123",
            status=NodeStatus.OTHER,
        )
        assert node.node_id == NodeId(7)
        assert node.hostname == "10.0.0.1"
        assert node.ncpus == 8
        assert node.enabled is False
        assert node.cloud == "hetzner"
        assert node.username == "admin"
        assert node.port == 2222
        assert node.jump_host == "jump.example.com"
        assert node.jump_port == 2222
        assert node.jump_username == "jumpuser"
        assert node.external_id == "ext-123"
        assert node.status == NodeStatus.OTHER


class TestNodeId:
    def test_post_init_rejects_non_positive(self) -> None:
        for bad in (0, -1, -100):
            with pytest.raises(ValueError):
                NodeId(bad)

    def test_post_init_accepts_positive(self) -> None:
        NodeId(1)
        NodeId(99999)

    def test_str_renders_bare_int(self) -> None:
        assert str(NodeId(5)) == "5"
        assert f"{NodeId(42)}" == "42"

    def test_not_equal_to_int(self) -> None:
        assert (NodeId(5) == 5) is False
        assert (NodeId(5) != 5) is True

    def test_hashable_and_usable_as_dict_key(self) -> None:
        assert hash(NodeId(5)) == hash(NodeId(5))
        d = {NodeId(1): "a"}
        assert d[NodeId(1)] == "a"

    def test_equality_same_value(self) -> None:
        assert NodeId(5) == NodeId(5)
        assert NodeId(5) != NodeId(6)


class TestNewNode:
    def test_has_no_node_id_attribute(self) -> None:
        n = NewNode()
        assert not hasattr(n, "node_id")

    def test_defaults(self) -> None:
        n = NewNode(hostname="x", ncpus=4)
        assert n.enabled is True
        assert n.cloud is None
        assert n.username == "root"
        assert n.port == 22
        assert n.jump_host is None
        assert n.jump_port == 22
        assert n.jump_username == "root"
        assert n.external_id is None
        assert n.status == NodeStatus.OTHER

    def test_full_construction(self) -> None:
        n = NewNode(
            hostname="10.0.0.1",
            ncpus=8,
            enabled=False,
            cloud="aws",
            username="admin",
            port=2222,
            jump_host="jump.example.com",
            jump_port=2222,
            jump_username="jumpuser",
            external_id="ext-123",
            status=NodeStatus.OTHER,
        )
        assert n.hostname == "10.0.0.1"
        assert n.ncpus == 8
        assert n.enabled is False
        assert n.cloud == "aws"
        assert n.username == "admin"
        assert n.port == 2222
        assert n.jump_host == "jump.example.com"
        assert n.jump_port == 2222
        assert n.jump_username == "jumpuser"
        assert n.external_id == "ext-123"
        assert n.status == NodeStatus.OTHER

    def test_defaults_ncpus_to_none(self) -> None:
        """NewNode instantiated with only cloud and enabled defaults ncpus to None."""
        n = NewNode(cloud="aws", enabled=False)
        assert n.ncpus is None

    def test_tmp_reservation_defaults(self) -> None:
        n = NewNode(cloud="aws", enabled=False)
        assert n.hostname == ""
        assert n.ncpus is None
        assert n.username == "root"
        assert n.port == 22
        assert n.jump_host is None
        assert n.jump_port == 22
        assert n.jump_username == "root"
        assert n.external_id is None
        assert n.status == NodeStatus.OTHER
        assert n.enabled is False
        assert n.cloud == "aws"

    def test_explicit_hostname_ncpus_override_defaults(self) -> None:
        n = NewNode(hostname="10.0.0.1", ncpus=4)
        assert n.hostname == "10.0.0.1"
        assert n.ncpus == 4


class TestConnectedMachine:
    def make_machine(self, **overrides: object) -> ConnectedMachine:
        defaults: dict[str, object] = {"node_id": NodeId(1), "platform": "linux"}
        defaults.update(overrides)
        return ConnectedMachine(**defaults)  # type: ignore[arg-type]

    def test_is_compatible_free_and_match(self) -> None:
        m = self.make_machine(state=MachineState.FREE, platform="linux")
        assert m.is_compatible(("linux", "windows")) is True

    def test_is_compatible_busy_not_match(self) -> None:
        m = self.make_machine(state=MachineState.BUSY, platform="linux")
        assert m.is_compatible(("linux",)) is False

    def test_is_compatible_platform_no_match(self) -> None:
        m = self.make_machine(state=MachineState.FREE, platform="windows")
        assert m.is_compatible(("linux",)) is False

    def test_is_compatible_empty_platforms(self) -> None:
        m = self.make_machine(state=MachineState.FREE, platform="linux")
        assert m.is_compatible(()) is False

    def test_occupy_transitions_to_busy(self) -> None:
        m = self.make_machine(state=MachineState.FREE)
        occupied = m.occupy()
        assert occupied.state == MachineState.BUSY
        assert m.state == MachineState.FREE

    def test_occupy_when_already_busy(self) -> None:
        m = self.make_machine(state=MachineState.BUSY)
        with pytest.raises(MachineBusyError) as exc_info:
            m.occupy()
        assert exc_info.value.node_id == NodeId(1)
        assert not hasattr(exc_info.value, "hostname")

    def test_release_sets_free_and_timestamp(self) -> None:
        before = time.monotonic()
        m = self.make_machine(state=MachineState.BUSY)
        released = m.release()
        after = time.monotonic()
        assert released.state == MachineState.FREE
        assert released.free_since is not None
        assert before <= released.free_since <= after
        assert m.state == MachineState.BUSY
        assert m.free_since is None


class TestTaskErrorFormat:
    def test_error_is_none_on_success(self) -> None:
        task = _make_task()
        running = task.run(NodeId(7), "/r")
        done = running.complete(local_folder="/l", remote_folder="/r")
        assert done.error is None

    def test_error_is_bare_reason_on_reject(self) -> None:
        task = _make_task()
        rejected = task.reject("unsupported engine")
        assert rejected.error == "unsupported engine"

    def test_error_is_bare_reason_on_fail(self) -> None:
        task = _make_task()
        running = task.run(NodeId(7), "/r")
        failed = running.fail("node is gone", local_folder="/l", remote_folder="/r")
        assert failed.error == "node is gone"


class TestMaterializeTask:
    def test_materialize_task_adds_task_created_event(self) -> None:
        task = _make_task(events=())
        result = materialize_task(task)
        assert len(result.events) == 1
        evt = result.events[0]
        assert isinstance(evt, TaskCreated)
        assert evt.task_id == task.task_id
        assert evt.webhook_url == task.webhook_url
        assert evt.webhook_custom_params == task.webhook_custom_params
        assert evt.engine_name == task.engine
        # All other fields preserved
        assert result.label == task.label
        assert result.status == task.status
        assert result.remote_folder == task.remote_folder


class TestTaskId:
    def test_post_init_rejects_non_positive(self) -> None:
        for bad in (0, -1):
            with pytest.raises(ValueError):
                TaskId(bad)

    def test_post_init_accepts_positive(self) -> None:
        TaskId(1)
        TaskId(99999)

    def test_str_renders_bare_int(self) -> None:
        assert str(TaskId(5)) == "5"
        assert f"{TaskId(5)}" == "5"

    def test_not_equal_to_int(self) -> None:
        assert (TaskId(5) == 5) is False
        assert (TaskId(5) != 5) is True

    def test_hashable_and_usable_as_dict_key(self) -> None:
        assert hash(TaskId(5)) == hash(TaskId(5))
        d = {TaskId(1): "a"}
        assert d[TaskId(1)] == "a"

    def test_equality_same_value(self) -> None:
        assert TaskId(5) == TaskId(5)
        assert TaskId(5) != TaskId(6)


class TestNewTask:
    def test_constructs_with_defaults(self) -> None:
        nt = NewTask(label="x", engine="cp2k")
        assert nt.label == "x"
        assert nt.engine == "cp2k"
        assert nt.local_folder is None
        assert nt.webhook_url is None
        assert nt.webhook_custom_params == {}
        assert nt.extra == {}
        assert not hasattr(nt, "allocated_ip")
        assert not hasattr(nt, "created_at")
        assert not hasattr(nt, "updated_at")
        assert not hasattr(nt, "status")
        assert not hasattr(nt, "allocated_node_id")

    def test_has_no_task_id(self) -> None:
        nt = NewTask(label="x", engine="cp2k")
        assert not hasattr(nt, "task_id")

    def test_has_no_events_attribute(self) -> None:
        nt = NewTask(label="x", engine="cp2k")
        assert not hasattr(nt, "_events")

    def test_has_no_remote_folder_or_error(self) -> None:
        nt = NewTask(label="x", engine="cp2k")
        assert not hasattr(nt, "remote_folder")
        assert not hasattr(nt, "error")

    def test_has_no_lifecycle_methods(self) -> None:
        nt = NewTask(label="x", engine="cp2k")
        for method in (
            "run",
            "complete",
            "fail",
            "reject",
            "abandon",
        ):
            assert not hasattr(nt, method)
