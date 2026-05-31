# FILE: tests/unit/test_domain_model.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain entities: TaskStatus, MachineState, ProcessResult, TaskContext, Engine, Task, Node, ConnectedMachine.
#   SCOPE: Enum values, dataclass defaults/frozen semantics, Engine validation, Task lifecycle methods, ConnectedMachine state transitions.
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS
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
#   test_task_allocate_to - returns new Task with ip
#   test_task_allocate_to_already_allocated - raises TaskAlreadyAllocatedError
#   test_task_mark_running - transitions to RUNNING
#   test_task_complete - transitions RUNNING->DONE
#   test_task_complete_not_running - raises TaskNotAllocatedError
#   test_task_fail - transitions to DONE with context.error set
#   test_task_fail_not_running - raises TaskNotRunningError
#   test_node_defaults - username, port, cloud, enabled defaults
#   test_node_full_construction - all positional args
#   test_connected_machine_is_compatible - FREE+match, BUSY regardless, no match
#   test_connected_machine_occupy - FREE->BUSY
#   test_connected_machine_occupy_busy - raises MachineBusyError
#   test_connected_machine_release - FREE + free_since
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Domain model entity unit tests
# END_CHANGE_SUMMARY

import time
from dataclasses import FrozenInstanceError

import pytest

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
    Node,
    ProcessResult,
    Task,
    TaskContext,
    TaskStatus,
)


# START_CONTRACT: test_task_status_values
#   PURPOSE: Verify TaskStatus enum values and int compatibility
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: TaskStatus]
# END_CONTRACT: test_task_status_values
class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.TO_DO == 0
        assert TaskStatus.RUNNING == 1
        assert TaskStatus.DONE == 2

    def test_is_int(self):
        assert isinstance(TaskStatus.TO_DO, int)

    def test_members(self):
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
    def test_free_not_equal_busy(self):
        assert MachineState.FREE != MachineState.BUSY

    def test_members(self):
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
    def test_defaults(self):
        r = ProcessResult(exit_code=0)
        assert r.exit_code == 0
        assert r.stdout == ""
        assert r.stderr == ""

    def test_all_fields(self):
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
    def test_known_fields(self):
        ctx = TaskContext(engine="cp2k", remote_folder="/r", local_folder="/l")
        assert ctx.engine == "cp2k"
        assert ctx.remote_folder == "/r"
        assert ctx.local_folder == "/l"
        assert ctx.webhook_url is None
        assert ctx.webhook_custom_params == {}
        assert ctx.error is None

    def test_extra_defaults_to_empty_dict(self):
        ctx = TaskContext(engine="cp2k")
        assert ctx.extra == {}

    def test_extra_preserves_arbitrary_keys(self):
        ctx = TaskContext(engine="cp2k", extra={"input_xyz": "mol.xyz", "nproc": 4})
        assert ctx.extra["input_xyz"] == "mol.xyz"
        assert ctx.extra["nproc"] == 4

    def test_to_metadata_roundtrip(self):
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

    def test_to_metadata_known_fields(self):
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

    def test_from_metadata_extra_keys(self):
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

    def test_to_metadata_omits_none_values(self):
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
    def test_to_metadata_preserves_webhook_custom_params(self):
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
    def test_to_metadata_preserves_empty_webhook_custom_params(self):
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
    def test_validate_inputs_passes_when_all_present(self):
        engine = Engine(name="cp2k", spawn="cp2k", input_files=("inp", "xyz"))
        ctx = TaskContext(engine="cp2k", extra={"inp": "content", "xyz": "content"})
        engine.validate_inputs(ctx)  # no exception

    def test_validate_inputs_raises_when_file_missing(self):
        engine = Engine(name="cp2k", spawn="cp2k", input_files=("inp", "xyz"))
        ctx = TaskContext(engine="cp2k", extra={"inp": "content"})
        with pytest.raises(MissingInputFileError) as exc_info:
            engine.validate_inputs(ctx)
        assert "xyz" in str(exc_info.value)
        assert "cp2k" in str(exc_info.value)

    def test_validate_inputs_no_input_files(self):
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
    def make_task(self, **overrides):
        ctx = TaskContext(engine="cp2k")
        base = dict(task_id=1, label="test", context=ctx)
        base.update(overrides)
        return Task(**base)  # type: ignore[arg-type]

    def test_construction_default_status(self):
        task = self.make_task()
        assert task.task_id == 1
        assert task.label == "test"
        assert task.context.engine == "cp2k"
        assert task.status == TaskStatus.TO_DO
        assert task.allocated_ip is None

    def test_immutability(self):
        task = self.make_task()
        with pytest.raises(FrozenInstanceError):
            task.status = TaskStatus.RUNNING  # type: ignore[misc]

    def test_allocate_to(self):
        task = self.make_task()
        allocated = task.allocate_to("10.0.0.1")
        assert allocated.allocated_ip == "10.0.0.1"
        assert allocated.task_id == task.task_id
        assert allocated.status == task.status
        # original unchanged
        assert task.allocated_ip is None

    def test_allocate_to_already_allocated(self):
        task = self.make_task(allocated_ip="10.0.0.1")
        with pytest.raises(TaskAlreadyAllocatedError) as exc_info:
            task.allocate_to("10.0.0.2")
        assert "1" in str(exc_info.value)

    def test_mark_running(self):
        task = self.make_task()
        running = task.allocate_to("1.2.3.4").mark_running()
        assert running.status == TaskStatus.RUNNING
        assert running.task_id == task.task_id

    def test_complete_on_running(self):
        task = self.make_task()
        running = task.allocate_to("1.2.3.4").mark_running()
        done = running.complete()
        assert done.status == TaskStatus.DONE
        assert done.context.error is None

    def test_complete_on_todo_raises(self):
        task = self.make_task()
        with pytest.raises(TaskNotRunningError) as exc_info:
            task.complete()
        assert "1" in str(exc_info.value)

    def test_fail_on_running(self):
        task = self.make_task()
        running = task.allocate_to("1.2.3.4").mark_running()
        failed = running.fail("out of memory")
        assert failed.status == TaskStatus.DONE
        assert failed.context.error == "out of memory"

    def test_fail_on_todo_raises(self):
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
    def test_defaults(self):
        node = Node(ip="10.0.0.1", ncpus=4)
        assert node.ip == "10.0.0.1"
        assert node.ncpus == 4
        assert node.enabled is True
        assert node.cloud is None
        assert node.username == "root"
        assert node.port == 22

    def test_full_construction(self):
        node = Node(
            ip="10.0.0.1",
            ncpus=8,
            enabled=False,
            cloud="hetzner",
            username="admin",
            port=2222,
        )
        assert node.ip == "10.0.0.1"
        assert node.ncpus == 8
        assert node.enabled is False
        assert node.cloud == "hetzner"
        assert node.username == "admin"
        assert node.port == 2222


# START_CONTRACT: test_connected_machine
#   PURPOSE: Verify ConnectedMachine compatibility check, occupy, and release
#   INPUTS: { None }
#   OUTPUTS: { None - assertions }
#   SIDE_EFFECTS: None
#   LINKS: [M-DOMAIN-MODEL: ConnectedMachine, MachineBusyError]
# END_CONTRACT: test_connected_machine
class TestConnectedMachine:
    def make_machine(self, **overrides):
        defaults = dict(ip="10.0.0.1", platform="linux", ncpus=4)
        defaults.update(overrides)
        return ConnectedMachine(**defaults)  # type: ignore[arg-type]

    def test_is_compatible_free_and_match(self):
        m = self.make_machine(state=MachineState.FREE, platform="linux")
        assert m.is_compatible(("linux", "windows")) is True

    def test_is_compatible_busy_not_match(self):
        m = self.make_machine(state=MachineState.BUSY, platform="linux")
        assert m.is_compatible(("linux",)) is False

    def test_is_compatible_platform_no_match(self):
        m = self.make_machine(state=MachineState.FREE, platform="windows")
        assert m.is_compatible(("linux",)) is False

    def test_is_compatible_empty_platforms(self):
        m = self.make_machine(state=MachineState.FREE, platform="linux")
        assert m.is_compatible(()) is False

    def test_occupy_transitions_to_busy(self):
        m = self.make_machine(state=MachineState.FREE)
        occupied = m.occupy()
        assert occupied.state == MachineState.BUSY
        # original unchanged
        assert m.state == MachineState.FREE

    def test_occupy_when_already_busy(self):
        m = self.make_machine(state=MachineState.BUSY)
        with pytest.raises(MachineBusyError) as exc_info:
            m.occupy()
        assert "10.0.0.1" in str(exc_info.value)

    def test_release_sets_free_and_timestamp(self):
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
