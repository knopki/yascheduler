# FILE: tests/unit/test_domain_model.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain entities: TaskStatus, MachineState, ProcessResult, Engine, Task, Node, ConnectedMachine.
#   SCOPE: Enum values, dataclass defaults/frozen semantics, Engine validation, Task lifecycle methods, ConnectedMachine state transitions, Task.with_remote_folder, Task.with_download_results, Task.allocate_to(node) binding allocated_node_id (sole allocation signal), Task.error column format contract.
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_task_status_values - TO_DO=0, RUNNING=1, DONE=2, is int
#   test_machine_state_distinct - FREE != BUSY
#   test_process_result - construction defaults and all fields
#   test_engine_validate_inputs - ok when files present, raises MissingInputFileError when missing
#   test_task_construction - default TO_DO status
#   test_task_immutability - FrozenInstanceError on mutation
#   test_allocate_to_takes_node_and_binds_allocated_node_id - allocate_to(node) sets allocated_node_id (sole allocation signal)
#   test_allocate_to_rejects_already_allocated - raises TaskAlreadyAllocatedError, allocated_node_id unchanged
#   test_mark_running_raises_when_allocated_node_id_none - mark_running guard on allocated_node_id
#   test_task_mark_running - transitions to RUNNING
#   test_task_complete - transitions RUNNING->DONE
#   test_task_fail - transitions to DONE with error set
#   test_task_fail_not_running - raises TaskNotRunningError
#   test_task_reject - transitions TO_DO->DONE with error set
#   test_new_task_defaults - NewTask typed-field defaults, no task_id, no remote_folder, no error
#   TestTaskWithRemoteFolder - with_remote_folder sets the field, preserves others, no validation, chains
#   TestTaskWithDownloadResults - with_download_results sets both fields, preserves extra, keyword-only, no validation, chains
#   TestTaskErrorFormat - Task.error column format contract (bare on reject/fail, None on success)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - drop-task-context-entity: remove TestTaskContext, TestTaskContextReplace, TestTaskWithContext; add TestTaskWithRemoteFolder, TestTaskWithDownloadResults, TestTaskErrorFormat; update Task/NewTask construction to typed fields; Engine.validate_inputs takes extra dict (was TaskContext).
#   PREVIOUS_CHANGE: v1.6.0 - task-schema-and-entity-cleanup: drop allocated_ip from Task/NewTask.
# END_CHANGE_SUMMARY

import time
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from yascheduler.domain.events import TaskCreated
from yascheduler.domain.exceptions import (
    MachineBusyError,
    MissingInputFileError,
    TaskAlreadyAllocatedError,
    TaskNotAllocatedError,
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
    ProcessResult,
    Task,
    TaskId,
    TaskStatus,
)

_DT = datetime(2025, 1, 1)


def _node(node_id: int = 7, ip: str = "10.0.0.1") -> Node:
    """Construct a minimal Node for allocate_to tests."""
    return Node(node_id=NodeId(node_id), ip=ip, ncpus=4)


def _make_task(**overrides: object) -> Task:
    """Build a Task with typed fields; all 11 required fields supplied."""
    base: dict[str, object] = dict(
        task_id=TaskId(1),
        label="test",
        engine="cp2k",
        remote_folder=None,
        local_folder=None,
        webhook_url=None,
        webhook_custom_params={},
        error=None,
        extra={},
        created_at=_DT,
        updated_at=_DT,
    )
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


# START_CONTRACT: test_task_status_values
#   PURPOSE: Verify TaskStatus enum values and int compatibility
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: TaskStatus]
# END_CONTRACT: test_task_status_values
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


# START_CONTRACT: test_machine_state_distinct
#   PURPOSE: Verify FREE and BUSY are distinct members
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: MachineState]
# END_CONTRACT: test_machine_state_distinct
class TestMachineState:
    def test_free_not_equal_busy(self) -> None:
        assert MachineState.FREE != MachineState.BUSY

    def test_members(self) -> None:
        assert MachineState.FREE is MachineState(1)
        assert MachineState.BUSY is MachineState(2)


# START_CONTRACT: test_process_result
#   PURPOSE: Verify ProcessResult dataclass default and full construction
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: ProcessResult]
# END_CONTRACT: test_process_result
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


# START_CONTRACT: test_engine_validate_inputs
#   PURPOSE: Verify Engine.validate_inputs passes when files present, fails with MissingInputFileError when missing
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Engine, MissingInputFileError]
# END_CONTRACT: test_engine_validate_inputs
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


# START_CONTRACT: test_task
#   PURPOSE: Verify Task construction, immutability, and lifecycle methods
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Task, TaskAlreadyAllocatedError, TaskNotAllocatedError]
# END_CONTRACT: test_task
class TestTask:
    def make_task(self, **overrides: object) -> Task:
        return _make_task(**overrides)

    @staticmethod
    def _node(node_id: int = 7, ip: str = "10.0.0.1") -> Node:
        return Node(node_id=NodeId(node_id), ip=ip, ncpus=4)

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

    def test_allocate_to_takes_node_and_binds_allocated_node_id(self) -> None:
        task = self.make_task()
        node = self._node(node_id=7, ip="10.0.0.1")
        allocated = task.allocate_to(node)
        assert allocated.allocated_node_id == NodeId(7)
        assert allocated.task_id == task.task_id
        assert allocated.status == task.status
        assert task.allocated_node_id is None
        assert not hasattr(allocated, "allocated_ip")

    def test_allocate_to_rejects_already_allocated(self) -> None:
        task = self.make_task(allocated_node_id=NodeId(7))
        node = self._node(node_id=8, ip="10.0.0.2")
        with pytest.raises(TaskAlreadyAllocatedError) as exc_info:
            task.allocate_to(node)
        assert "1" in str(exc_info.value)
        assert task.allocated_node_id == NodeId(7)

    def test_mark_running_raises_when_allocated_node_id_none(self) -> None:
        task = self.make_task()
        with pytest.raises(TaskNotAllocatedError) as exc_info:
            task.mark_running()
        assert "1" in str(exc_info.value)

    def test_mark_running(self) -> None:
        task = self.make_task()
        running = task.allocate_to(self._node()).mark_running()
        assert running.status == TaskStatus.RUNNING
        assert running.task_id == task.task_id

    def test_complete_on_running(self) -> None:
        task = self.make_task()
        running = task.allocate_to(self._node()).mark_running()
        done = running.complete()
        assert done.status == TaskStatus.DONE
        assert done.error is None

    def test_complete_on_todo_raises(self) -> None:
        task = self.make_task()
        with pytest.raises(TaskNotRunningError) as exc_info:
            task.complete()
        assert "1" in str(exc_info.value)

    def test_fail_on_running(self) -> None:
        task = self.make_task()
        running = task.allocate_to(self._node()).mark_running()
        failed = running.fail("out of memory")
        assert failed.status == TaskStatus.DONE
        assert failed.error == "out of memory"

    def test_fail_on_todo_raises(self) -> None:
        task = self.make_task()
        with pytest.raises(TaskNotRunningError) as exc_info:
            task.fail("reason")
        assert "1" in str(exc_info.value)

    def test_reject_on_todo(self) -> None:
        task = self.make_task()
        rejected = task.reject("unsupported engine")
        assert rejected.status == TaskStatus.DONE
        assert rejected.error == "unsupported engine"

    def test_reject_on_running_raises(self) -> None:
        task = self.make_task()
        running = task.allocate_to(self._node()).mark_running()
        with pytest.raises(TaskNotTodoError):
            running.reject("reason")


# START_CONTRACT: test_node
#   PURPOSE: Verify Node dataclass defaults and full construction
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Node]
# END_CONTRACT: test_node
class TestNode:
    def test_defaults(self) -> None:
        node = Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4)
        assert node.node_id == NodeId(1)
        assert node.ip == "10.0.0.1"
        assert node.ncpus == 4
        assert node.enabled is True
        assert node.cloud is None
        assert node.username == "root"
        assert node.port == 22

    def test_full_construction(self) -> None:
        node = Node(
            node_id=NodeId(7),
            ip="10.0.0.1",
            ncpus=8,
            enabled=False,
            cloud="hetzner",
            username="admin",
            port=2222,
        )
        assert node.node_id == NodeId(7)
        assert node.ip == "10.0.0.1"
        assert node.ncpus == 8
        assert node.enabled is False
        assert node.cloud == "hetzner"
        assert node.username == "admin"
        assert node.port == 2222


# START_CONTRACT: test_node_id
#   PURPOSE: Verify NodeId value object validation, str, equality, hashability.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: NodeId]
# END_CONTRACT: test_node_id
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


# START_CONTRACT: test_new_node
#   PURPOSE: Verify NewNode dataclass defaults (including ip/ncpus defaults), full construction, absence of node_id.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: NewNode]
# END_CONTRACT: test_new_node
class TestNewNode:
    def test_has_no_node_id_attribute(self) -> None:
        NewNode()

    def test_defaults(self) -> None:
        n = NewNode(ip="x", ncpus=4)
        assert n.enabled is True
        assert n.cloud is None
        assert n.username == "root"
        assert n.port == 22

    def test_full_construction(self) -> None:
        n = NewNode(
            ip="10.0.0.1",
            ncpus=8,
            enabled=False,
            cloud="aws",
            username="admin",
            port=2222,
        )
        assert n.ip == "10.0.0.1"
        assert n.ncpus == 8
        assert n.enabled is False
        assert n.cloud == "aws"
        assert n.username == "admin"
        assert n.port == 2222

    def test_tmp_reservation_defaults(self) -> None:
        n = NewNode(cloud="aws", enabled=False)
        assert n.ip == ""
        assert n.ncpus == 0
        assert n.username == "root"
        assert n.port == 22
        assert n.enabled is False
        assert n.cloud == "aws"

    def test_explicit_ip_ncpus_override_defaults(self) -> None:
        n = NewNode(ip="10.0.0.1", ncpus=4)
        assert n.ip == "10.0.0.1"
        assert n.ncpus == 4


# START_CONTRACT: test_connected_machine
#   PURPOSE: Verify ConnectedMachine compatibility check, occupy, and release
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: ConnectedMachine, MachineBusyError]
# END_CONTRACT: test_connected_machine
class TestConnectedMachine:
    def make_machine(self, **overrides: object) -> ConnectedMachine:
        defaults: dict[str, object] = dict(
            node_id=NodeId(1), ip="10.0.0.1", platform="linux", ncpus=4
        )
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
        assert "10.0.0.1" in str(exc_info.value)

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


# START_CONTRACT: test_with_remote_folder
#   PURPOSE: Verify Task.with_remote_folder sets the field, preserves all others, no status validation, chains with with_event/fail/complete.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Task.with_remote_folder]
# END_CONTRACT: test_with_remote_folder
class TestTaskWithRemoteFolder:
    def test_sets_remote_folder(self) -> None:
        task = _make_task(remote_folder=None)
        result = task.with_remote_folder("/remote/20240101_000000_7")
        assert result.remote_folder == "/remote/20240101_000000_7"
        assert result.task_id == task.task_id
        assert result.label == task.label
        assert result.engine == task.engine
        assert result.local_folder == task.local_folder
        assert result.webhook_url == task.webhook_url
        assert result.webhook_custom_params == task.webhook_custom_params
        assert result.error == task.error
        assert result.extra == task.extra
        assert result.status == task.status
        assert result.allocated_node_id == task.allocated_node_id
        assert result._events == task._events

    def test_preserves_original(self) -> None:
        task = _make_task(remote_folder=None)
        result = task.with_remote_folder("/r/new")
        assert task.remote_folder is None
        assert result.remote_folder == "/r/new"

    @pytest.mark.parametrize("status", list(TaskStatus))
    def test_no_status_validation(self, status: TaskStatus) -> None:
        task = _make_task(status=status)
        result = task.with_remote_folder("/r")
        assert result.remote_folder == "/r"
        assert result.status == status

    def test_chains_with_with_event(self) -> None:
        task = _make_task(engine="cp2k")
        result = task.with_remote_folder("/r").with_event(
            TaskCreated, engine_name="cp2k"
        )
        assert result.remote_folder == "/r"
        assert len(result._events) == 1
        evt = result._events[0]
        assert isinstance(evt, TaskCreated)
        assert evt.engine_name == "cp2k"
        assert evt.task_id == task.task_id

    def test_chains_with_fail(self) -> None:
        task = _make_task()
        running = task.allocate_to(_node()).mark_running()
        result = running.with_remote_folder("/r").fail("reason")
        assert result.status == TaskStatus.DONE
        assert result.error == "reason"
        assert result.remote_folder == "/r"


# START_CONTRACT: test_with_download_results
#   PURPOSE: Verify Task.with_download_results sets local_folder+remote_folder, preserves extra, keyword-only, no status validation, chains.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Task.with_download_results]
# END_CONTRACT: test_with_download_results
class TestTaskWithDownloadResults:
    def test_sets_both_fields(self) -> None:
        task = _make_task(local_folder=None, remote_folder=None)
        result = task.with_download_results(
            local_folder="/local/out", remote_folder="/remote/out"
        )
        assert result.local_folder == "/local/out"
        assert result.remote_folder == "/remote/out"
        assert result.task_id == task.task_id
        assert result.engine == task.engine
        assert result.status == task.status

    def test_does_not_touch_extra(self) -> None:
        task = _make_task(extra={"input.in": "ATOMS"})
        result = task.with_download_results(local_folder="/l", remote_folder="/r")
        assert result.extra == {"input.in": "ATOMS"}

    def test_accepts_equal_values(self) -> None:
        task = _make_task(local_folder="/l", remote_folder="/r")
        result = task.with_download_results(local_folder="/l", remote_folder="/r")
        assert result.local_folder == "/l"
        assert result.remote_folder == "/r"

    def test_keyword_only(self) -> None:
        task = _make_task()
        with pytest.raises(TypeError):
            task.with_download_results("/l", "/r")  # type: ignore[call-arg, misc]

    @pytest.mark.parametrize("status", list(TaskStatus))
    def test_no_status_validation(self, status: TaskStatus) -> None:
        task = _make_task(status=status)
        result = task.with_download_results(local_folder="/l", remote_folder="/r")
        assert result.local_folder == "/l"
        assert result.remote_folder == "/r"
        assert result.status == status

    def test_chains_with_complete(self) -> None:
        task = _make_task()
        running = task.allocate_to(_node()).mark_running()
        result = running.with_download_results(
            local_folder="/l", remote_folder="/r"
        ).complete()
        assert result.status == TaskStatus.DONE
        assert result.local_folder == "/l"
        assert result.remote_folder == "/r"


# START_CONTRACT: test_error_format
#   PURPOSE: Verify Task.error column format contract — bare on reject/fail, None on success.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Task.error column format contract]
# END_CONTRACT: test_error_format
class TestTaskErrorFormat:
    def test_error_is_none_on_success(self) -> None:
        task = _make_task()
        running = task.allocate_to(_node()).mark_running()
        done = running.complete()
        assert done.error is None

    def test_error_is_bare_reason_on_reject(self) -> None:
        task = _make_task()
        rejected = task.reject("unsupported engine")
        assert rejected.error == "unsupported engine"

    def test_error_is_bare_reason_on_fail(self) -> None:
        task = _make_task()
        running = task.allocate_to(_node()).mark_running()
        failed = running.fail("node is gone")
        assert failed.error == "node is gone"


# START_CONTRACT: test_task_id
#   PURPOSE: Verify TaskId value object validation, str, equality, hashability.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: TaskId]
# END_CONTRACT: test_task_id
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


# START_CONTRACT: test_new_task
#   PURPOSE: Verify NewTask typed-field defaults, no task_id, no remote_folder, no error, no lifecycle methods.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: NewTask]
# END_CONTRACT: test_new_task
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
            "allocate_to",
            "mark_running",
            "complete",
            "fail",
            "reject",
            "with_remote_folder",
            "with_download_results",
            "with_event",
            "pull_events",
            "record_event",
        ):
            assert not hasattr(nt, method)
