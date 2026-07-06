# FILE: tests/unit/test_domain_model.py
# VERSION: 1.5.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain entities: TaskStatus, MachineState, ProcessResult, TaskContext, Engine, Task, Node, ConnectedMachine.
#   SCOPE: Enum values, dataclass defaults/frozen semantics, Engine validation, Task lifecycle methods, ConnectedMachine state transitions, Task.with_context, TaskContext.replace, Task.allocate_to(node) binding allocated_node_id (sole allocation signal), allocated_node_id field defaults/preservation, Task has no allocated_ip attribute, created_at/updated_at field defaults.
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_task_status_values - TO_DO=0, RUNNING=1, DONE=2, is int
#   test_machine_state_distinct - FREE != BUSY
#   test_process_result - construction defaults and all fields
#   test_task_context - attribute access, extra defaults, arbitrary keys
#   test_engine_validate_inputs - ok when files present, raises MissingInputFileError when missing
#   test_task_construction - default TO_DO status
#   test_task_immutability - FrozenInstanceError on mutation
#   test_allocate_to_takes_node_and_binds_allocated_node_id - allocate_to(node) sets allocated_node_id (sole allocation signal)
#   test_allocate_to_rejects_already_allocated - raises TaskAlreadyAllocatedError, allocated_node_id unchanged
#   test_allocate_to_returns_task_without_allocated_ip - allocate_to result has no allocated_ip attribute
#   test_mark_running_raises_when_allocated_node_id_none - mark_running guard on allocated_node_id
#   test_task_mark_running - transitions to RUNNING
#   test_task_complete - transitions RUNNING->DONE
#   test_task_complete_not_running - raises TaskNotAllocatedError
#   test_task_fail - transitions to DONE with context.error set
#   test_task_fail_not_running - raises TaskNotRunningError
#   test_new_task_has_allocated_node_id_default_none - NewTask defaults allocated_node_id to None
#   test_task_with_context_preserves_allocated_node_id - with_context retains allocated_node_id
#   test_node_defaults - username, port, cloud, enabled defaults
#   test_node_full_construction - all positional args
#   TestNodeId - validation, str, equality, hashability
#   TestNewNode - NewNode dataclass defaults, full construction, no node_id
#   test_connected_machine_is_compatible - FREE+match, BUSY regardless, no match
#   test_connected_machine_occupy - FREE->BUSY
#   test_connected_machine_occupy_busy - raises MachineBusyError
#   test_connected_machine_release - FREE + free_since
#   TestTaskWithContext - with_context wholesale replace, immutability, event preservation, no-status-validation, chaining
#   TestTaskContextReplace - replace typed copy-with: single/multi override, original unchanged, equal copy, drift-lock, fail integration, with_context chain
#   TestTaskId - TaskId value object: validation, str, equality, hashability
#   TestNewTask - NewTask dataclass: defaults, no task_id, no lifecycle methods
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - task-schema-and-entity-cleanup: drop allocated_ip from Task/NewTask (allocated_node_id is the sole allocation signal); allocate_to/mark_running guards switch to allocated_node_id; add test_allocate_to_returns_task_without_allocated_ip, test_mark_running_raises_when_allocated_node_id_none; Task gains created_at/updated_at (DB-generated, default None on construction).
#   PREVIOUS_CHANGE: v1.5.0 - task-allocated-node-id: update test_task_allocate_to* tests to call allocate_to(node) with a constructed Node (was allocate_to("ip") — signature changed); add test_allocate_to_takes_node_and_binds_both_fields, test_allocate_to_rejects_already_allocated (asserts neither field changed), test_new_task_has_allocated_node_id_default_none, test_task_with_context_preserves_allocated_node_id.
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
    TaskContext,
    TaskContextOverrides,
    TaskId,
    TaskStatus,
)


def _node(node_id: int = 7, ip: str = "10.0.0.1") -> Node:
    """Construct a minimal Node for allocate_to tests (task-allocated-node-id)."""
    return Node(node_id=NodeId(node_id), ip=ip, ncpus=4)


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


# START_CONTRACT: test_task_context
#   PURPOSE: Verify TaskContext holds known fields and extra dict
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: TaskContext]
# END_CONTRACT: test_task_context
class TestTaskContext:
    def test_known_fields(self) -> None:
        ctx = TaskContext(engine="cp2k", remote_folder="/r", local_folder="/l")
        assert ctx.engine == "cp2k"
        assert ctx.remote_folder == "/r"
        assert ctx.local_folder == "/l"
        assert ctx.webhook_url is None
        assert ctx.webhook_custom_params == {}
        assert ctx.error is None

    def test_extra_defaults_to_empty_dict(self) -> None:
        ctx = TaskContext(engine="cp2k")
        assert ctx.extra == {}

    def test_extra_preserves_arbitrary_keys(self) -> None:
        ctx = TaskContext(engine="cp2k", extra={"input_xyz": "mol.xyz", "nproc": 4})
        assert ctx.extra["input_xyz"] == "mol.xyz"
        assert ctx.extra["nproc"] == 4

    def test_to_metadata_roundtrip(self) -> None:
        ctx = TaskContext(
            engine="cp2k",
            remote_folder="/remote",
            local_folder="/local",
            webhook_url="https://hook.example.com",
            webhook_custom_params={"key": "val"},
            extra={"input_xyz": "mol.xyz", "nproc": 4},
        )
        metadata = ctx.to_metadata()
        restored = TaskContext.from_metadata(metadata)
        assert restored == ctx

    def test_to_metadata_known_fields(self) -> None:
        ctx = TaskContext(
            engine="cp2k",
            remote_folder="/r",
            local_folder="/l",
            webhook_url="https://hook.example.com",
            webhook_custom_params={"p1": "v1", "p2": "v2"},
            error="something went wrong",
        )
        metadata = ctx.to_metadata()
        restored = TaskContext.from_metadata(metadata)
        assert restored.engine == "cp2k"
        assert restored.remote_folder == "/r"
        assert restored.local_folder == "/l"
        assert restored.webhook_url == "https://hook.example.com"
        assert restored.webhook_custom_params == {"p1": "v1", "p2": "v2"}
        assert restored.error == "something went wrong"

    def test_from_metadata_extra_keys(self) -> None:
        metadata: dict[str, object] = {
            "engine": "cp2k",
            "input_xyz": "mol.xyz",
            "nproc": 4,
            "some_unknown": "value",
        }
        ctx = TaskContext.from_metadata(metadata)
        assert ctx.engine == "cp2k"
        assert ctx.extra == {
            "input_xyz": "mol.xyz",
            "nproc": 4,
            "some_unknown": "value",
        }

    def test_to_metadata_omits_none_values(self) -> None:
        ctx = TaskContext(engine="cp2k")
        metadata = ctx.to_metadata()
        assert "remote_folder" not in metadata
        assert "local_folder" not in metadata
        assert "webhook_url" not in metadata
        assert "error" not in metadata
        assert metadata.get("webhook_custom_params") == {}
        assert metadata["engine"] == "cp2k"

    # START_CONTRACT: test_to_metadata_preserves_webhook_custom_params
    #   PURPOSE: Verify webhook_custom_params survives roundtrip even when empty.
    #   INPUTS: { None }
    #   OUTPUTS: { None - assertion-based test }
    #   SIDE_EFFECTS: None
    #   LINKS:
    # END_CONTRACT: test_to_metadata_preserves_webhook_custom_params
    def test_to_metadata_preserves_webhook_custom_params(self) -> None:
        """webhook_custom_params empty and non-empty survive serialization roundtrip."""
        ctx = TaskContext(engine="fleur", webhook_custom_params={"key": "val"})
        meta = ctx.to_metadata()
        assert meta["webhook_custom_params"] == {"key": "val"}
        roundtripped = TaskContext.from_metadata(meta)
        assert roundtripped.webhook_custom_params == {"key": "val"}

    # START_CONTRACT: test_to_metadata_preserves_empty_webhook_custom_params
    #   PURPOSE: Verify empty dict webhook_custom_params survives roundtrip.
    #   INPUTS: { None }
    #   OUTPUTS: { None - assertion-based test }
    #   SIDE_EFFECTS: None
    #   LINKS:
    # END_CONTRACT: test_to_metadata_preserves_empty_webhook_custom_params
    def test_to_metadata_preserves_empty_webhook_custom_params(self) -> None:
        """Empty webhook_custom_params is not dropped."""
        ctx = TaskContext(engine="fleur")
        meta = ctx.to_metadata()
        assert meta["webhook_custom_params"] == {}
        roundtripped = TaskContext.from_metadata(meta)
        assert roundtripped.webhook_custom_params == {}


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
        ctx = TaskContext(engine="cp2k", extra={"inp": "content", "xyz": "content"})
        engine.validate_inputs(ctx)  # no exception

    def test_validate_inputs_raises_when_file_missing(self) -> None:
        engine = Engine(name="cp2k", spawn="cp2k", input_files=("inp", "xyz"))
        ctx = TaskContext(engine="cp2k", extra={"inp": "content"})
        with pytest.raises(MissingInputFileError) as exc_info:
            engine.validate_inputs(ctx)
        assert "xyz" in str(exc_info.value)
        assert "cp2k" in str(exc_info.value)

    def test_validate_inputs_no_input_files(self) -> None:
        engine = Engine(name="cp2k", spawn="cp2k")
        ctx = TaskContext(engine="cp2k")
        engine.validate_inputs(ctx)  # no exception


# START_CONTRACT: test_task
#   PURPOSE: Verify Task construction, immutability, and lifecycle methods
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Task, TaskAlreadyAllocatedError, TaskNotAllocatedError]
# END_CONTRACT: test_task
class TestTask:
    def make_task(self, **overrides: object) -> Task:
        ctx = TaskContext(engine="cp2k")
        base: dict[str, object] = dict(task_id=TaskId(1), label="test", context=ctx)
        base.update(overrides)
        return Task(**base)  # type: ignore[arg-type]

    @staticmethod
    def _node(node_id: int = 7, ip: str = "10.0.0.1") -> Node:
        return Node(node_id=NodeId(node_id), ip=ip, ncpus=4)

    def test_construction_default_status(self) -> None:
        task = self.make_task()
        assert task.task_id == TaskId(1)
        assert task.label == "test"
        assert task.context.engine == "cp2k"
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
        # original unchanged
        assert task.allocated_node_id is None
        # allocate_to returns a Task with no allocated_ip attribute
        assert not hasattr(allocated, "allocated_ip")

    def test_allocate_to_rejects_already_allocated(self) -> None:
        task = self.make_task(allocated_node_id=NodeId(7))
        node = self._node(node_id=8, ip="10.0.0.2")
        with pytest.raises(TaskAlreadyAllocatedError) as exc_info:
            task.allocate_to(node)
        assert "1" in str(exc_info.value)
        # allocated_node_id unchanged
        assert task.allocated_node_id == NodeId(7)

    def test_allocate_to_returns_task_without_allocated_ip(self) -> None:
        """allocate_to returns a Task with no allocated_ip attribute (field removed)."""
        task = self.make_task()
        node = self._node(node_id=7, ip="10.0.0.1")
        allocated = task.allocate_to(node)
        assert not hasattr(allocated, "allocated_ip")
        assert not hasattr(task, "allocated_ip")

    def test_mark_running_raises_when_allocated_node_id_none(self) -> None:
        """mark_running guard keys on allocated_node_id (was allocated_ip)."""
        task = self.make_task()  # allocated_node_id defaults to None
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
        assert done.context.error is None

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
        assert failed.context.error == "out of memory"

    def test_fail_on_todo_raises(self) -> None:
        task = self.make_task()
        with pytest.raises(TaskNotRunningError) as exc_info:
            task.fail("reason")
        assert "1" in str(exc_info.value)


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
        n = NewNode(ip="10.0.0.1", ncpus=4)
        assert not hasattr(n, "node_id")

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
        # remove-tmp-node-fake-ip: NewNode(cloud=..., enabled=False) yields the
        # tmp-reservation defaults — empty-string ip sentinel, ncpus=0.
        n = NewNode(cloud="aws", enabled=False)
        assert n.ip == ""
        assert n.ncpus == 0
        assert n.username == "root"
        assert n.port == 22
        assert n.enabled is False
        assert n.cloud == "aws"

    def test_explicit_ip_ncpus_override_defaults(self) -> None:
        # Explicit ip/ncpus override the new defaults.
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
        # original unchanged
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
        # original unchanged
        assert m.state == MachineState.BUSY
        assert m.free_since is None


# START_CONTRACT: test_with_context
#   PURPOSE: Verify Task.with_context wholesale context replacement, immutability, event preservation, no-status-validation, and chaining with with_event/fail/complete.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: Task.with_context, Task.with_event, Task.fail, Task.complete]
# END_CONTRACT: test_with_context
class TestTaskWithContext:
    def make_task(self, **overrides: object) -> Task:
        ctx = TaskContext(engine="fleur")
        base: dict[str, object] = dict(task_id=TaskId(1), label="test", context=ctx)
        base.update(overrides)
        return Task(**base)  # type: ignore[arg-type]

    def test_with_context_replaces_context_wholesale(self) -> None:
        task = self.make_task(status=TaskStatus.RUNNING)
        new_context = TaskContext(engine="cp2k", remote_folder="/r")
        result = task.with_context(new_context)
        assert result.context is new_context
        assert result.task_id == task.task_id
        assert result.label == task.label
        assert result.status == task.status
        assert result.allocated_node_id == task.allocated_node_id
        assert result._events == task._events

    def test_with_context_preserves_allocated_node_id(self) -> None:
        # task-allocated-node-id: with_context preserves allocated_node_id
        # alongside the other non-context fields.
        task = self.make_task(allocated_node_id=NodeId(5))
        new_context = TaskContext(engine="cp2k")
        result = task.with_context(new_context)
        assert result.allocated_node_id == NodeId(5)

    def test_with_context_preserves_events(self) -> None:
        task = self.make_task()
        event = TaskCreated(
            task_id=TaskId(1),
            webhook_url=None,
            webhook_custom_params={},
            engine_name="fleur",
        )
        task = task.record_event(event)
        new_context = TaskContext(engine="cp2k")
        result = task.with_context(new_context)
        assert result._events == task._events
        assert result._events == (event,)

    def test_with_context_leaves_original_unchanged(self) -> None:
        task = self.make_task()
        original_context = task.context
        new_context = TaskContext(engine="cp2k")
        result = task.with_context(new_context)
        assert result.context is new_context
        assert task.context is original_context
        assert task.context is not new_context
        with pytest.raises(FrozenInstanceError):
            task.context = new_context  # type: ignore[misc]

    @pytest.mark.parametrize("status", list(TaskStatus))
    def test_with_context_no_status_validation(self, status: TaskStatus) -> None:
        task = self.make_task(status=status)
        new_context = TaskContext(engine="cp2k")
        result = task.with_context(new_context)
        assert result.context is new_context
        assert result.status == status

    def test_with_context_chains_with_with_event(self) -> None:
        task = self.make_task()
        new_context = TaskContext(
            engine="cp2k",
            remote_folder="/r",
            webhook_url="https://hook.example.com",
            webhook_custom_params={"k": "v"},
        )
        result = task.with_context(new_context).with_event(
            TaskCreated, engine_name=new_context.engine
        )
        assert result.context is new_context
        assert len(result._events) == 1
        evt = result._events[0]
        assert isinstance(evt, TaskCreated)
        assert evt.engine_name == new_context.engine
        assert evt.task_id == task.task_id
        assert evt.webhook_url == new_context.webhook_url

    def test_with_context_chains_with_fail(self) -> None:
        task = self.make_task()
        new_context = TaskContext(
            engine="cp2k",
            remote_folder="/r",
            local_folder="/l",
            extra={"inp": "data"},
        )
        running = task.allocate_to(_node()).mark_running()
        result = running.with_context(new_context).fail("reason")
        assert result.status == TaskStatus.DONE
        assert result.context.error == "reason"
        assert result.context.engine == new_context.engine
        assert result.context.remote_folder == new_context.remote_folder
        assert result.context.local_folder == new_context.local_folder
        assert result.context.extra == new_context.extra

    def test_with_context_chains_with_complete(self) -> None:
        task = self.make_task()
        new_context = TaskContext(engine="cp2k", remote_folder="/r")
        running = task.allocate_to(_node()).mark_running()
        result = running.with_context(new_context).complete()
        assert result.status == TaskStatus.DONE
        assert result.context is new_context


# START_CONTRACT: test_replace
#   PURPOSE: Verify TaskContext.replace typed copy-with: single/multi-field overrides, original unchanged, equal copy, drift-lock, fail integration, with_context chain.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: TaskContext.replace, TaskContextOverrides, Task.fail, Task.with_context]
# END_CONTRACT: test_replace
class TestTaskContextReplace:
    def test_replace_single_field_override(self) -> None:
        ctx = TaskContext(engine="fleur")
        new = ctx.replace(remote_folder="/r/new")
        assert new.remote_folder == "/r/new"
        assert new.engine == "fleur"
        assert new.local_folder == ctx.local_folder
        assert new.webhook_url == ctx.webhook_url
        assert new.webhook_custom_params == ctx.webhook_custom_params
        assert new.error == ctx.error
        assert new.extra == ctx.extra

    def test_replace_multi_field_override(self) -> None:
        ctx = TaskContext(engine="fleur")
        new = ctx.replace(local_folder="/l", remote_folder="/r", extra={"k": "v"})
        assert new.local_folder == "/l"
        assert new.remote_folder == "/r"
        assert new.extra == {"k": "v"}
        assert new.engine == ctx.engine
        assert new.webhook_url == ctx.webhook_url
        assert new.webhook_custom_params == ctx.webhook_custom_params
        assert new.error == ctx.error

    def test_replace_leaves_original_unchanged(self) -> None:
        ctx = TaskContext(engine="fleur", error=None)
        new = ctx.replace(error="boom")
        assert new.error == "boom"
        assert ctx.error is None

    def test_replace_no_overrides_returns_equal_copy(self) -> None:
        ctx = TaskContext(engine="fleur", remote_folder="/r")
        new = ctx.replace()
        assert new == ctx
        assert new is not ctx

    def test_replace_error_field_override_chains_into_fail(self) -> None:
        task = Task(task_id=TaskId(1), label="x", context=TaskContext(engine="fleur"))
        running = task.allocate_to(_node()).mark_running()
        result = running.fail("disk full")
        assert result.status == TaskStatus.DONE
        assert result.context.error == "disk full"

    def test_taskcontext_overrides_keys_match_audited_usage(self) -> None:
        assert set(TaskContextOverrides.__annotations__) == {
            "remote_folder",
            "local_folder",
            "error",
            "extra",
        }

    def test_replace_chains_through_with_context(self) -> None:
        task = Task(task_id=TaskId(1), label="x", context=TaskContext(engine="fleur"))
        new_ctx = task.context.replace(remote_folder="/r")
        new_task = task.with_context(new_ctx)
        assert new_task.context is new_ctx
        assert new_task.context.remote_folder == "/r"


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
#   PURPOSE: Verify NewTask dataclass defaults, no task_id, no lifecycle methods.
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: NewTask]
# END_CONTRACT: test_new_task
class TestNewTask:
    def test_constructs_with_defaults(self) -> None:
        ctx = TaskContext(engine="cp2k")
        nt = NewTask(label="x", context=ctx)
        assert nt.label == "x"
        assert nt.context is ctx
        assert nt.status == TaskStatus.TO_DO
        assert nt.allocated_node_id is None
        assert not hasattr(nt, "allocated_ip")
        assert not hasattr(nt, "created_at")
        assert not hasattr(nt, "updated_at")

    def test_has_no_task_id(self) -> None:
        nt = NewTask(label="x", context=TaskContext(engine="cp2k"))
        assert not hasattr(nt, "task_id")

    def test_has_no_events_attribute(self) -> None:
        nt = NewTask(label="x", context=TaskContext(engine="cp2k"))
        assert not hasattr(nt, "_events")

    def test_new_task_has_allocated_node_id_default_none(self) -> None:
        # task-allocated-node-id: NewTask defaults allocated_node_id to None
        # (no node is bound until allocation; written by Task.allocate_to).
        nt = NewTask(label="x", context=TaskContext(engine="cp2k"))
        assert nt.allocated_node_id is None

    def test_has_no_lifecycle_methods(self) -> None:
        nt = NewTask(label="x", context=TaskContext(engine="cp2k"))
        for method in (
            "allocate_to",
            "mark_running",
            "complete",
            "fail",
            "reject",
            "with_context",
            "with_event",
            "pull_events",
            "record_event",
        ):
            assert not hasattr(nt, method)
