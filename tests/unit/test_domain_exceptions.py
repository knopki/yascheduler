# FILE: tests/unit/test_domain_exceptions.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain exception hierarchy.
#   SCOPE: Test all 11 exception classes for inheritance, field access, and message format.
#   DEPENDS: none
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_domain_error_is_exception - DomainError is catchable as Exception
#   test_validation_error_hierarchy - ValidationError inherits from DomainError, not Exception directly
#   test_unsupported_engine_error_fields - engine_name stored, message contains it
#   test_missing_input_file_error_fields - engine_name + filename stored, message format
#   test_task_error_hierarchy - TaskError inherits from DomainError
#   test_task_already_allocated_error - task_id stored, message format
#   test_task_not_allocated_error - task_id stored, message format
#   test_machine_busy_error - ip stored, message contains it
#   test_scheduling_error_hierarchy - SchedulingError inherits from DomainError
#   test_no_compatible_node_error - task_id + platforms stored
#   test_cloud_capacity_exhausted_error - task_id stored
#   test_all_exceptions_importable - verify all 11 import from yascheduler.domain.exceptions
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial domain exception tests
# END_CHANGE_SUMMARY

from yascheduler.domain.exceptions import (
    CloudCapacityExhaustedError,
    DomainError,
    MachineBusyError,
    MissingInputFileError,
    NoCompatibleNodeError,
    SchedulingError,
    TaskAlreadyAllocatedError,
    TaskError,
    TaskNotAllocatedError,
    UnsupportedEngineError,
    ValidationError,
)


# START_CONTRACT: test_domain_error_is_exception
#   PURPOSE: Verify DomainError is a subclass of Exception and can be caught as such.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_domain_error_is_exception
def test_domain_error_is_exception() -> None:
    assert issubclass(DomainError, Exception)
    try:
        raise DomainError("test")
    except Exception as e:
        assert isinstance(e, DomainError)
        assert str(e) == "test"


# START_CONTRACT: test_validation_error_hierarchy
#   PURPOSE: Verify ValidationError inherits from DomainError, not directly from Exception.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_validation_error_hierarchy
def test_validation_error_hierarchy() -> None:
    assert issubclass(ValidationError, DomainError)
    assert issubclass(ValidationError, Exception)
    # ValidationError should NOT be a direct subclass of Exception
    assert ValidationError.__mro__[1] is DomainError, (
        "ValidationError must inherit from DomainError, not Exception directly"
    )


# START_CONTRACT: test_unsupported_engine_error_fields
#   PURPOSE: Verify UnsupportedEngineError stores engine_name and message contains it.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_unsupported_engine_error_fields
def test_unsupported_engine_error_fields() -> None:
    exc = UnsupportedEngineError(engine_name="gromacs")
    assert exc.engine_name == "gromacs"
    assert "unsupported engine" in str(exc)
    assert "gromacs" in str(exc)


# START_CONTRACT: test_missing_input_file_error_fields
#   PURPOSE: Verify MissingInputFileError stores engine_name and filename; message mentions both.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_missing_input_file_error_fields
def test_missing_input_file_error_fields() -> None:
    exc = MissingInputFileError(engine_name="gromacs", filename="topol.top")
    assert exc.engine_name == "gromacs"
    assert exc.filename == "topol.top"
    assert "missing input file" in str(exc)
    assert "topol.top" in str(exc)
    assert "gromacs" in str(exc)


# START_CONTRACT: test_task_error_hierarchy
#   PURPOSE: Verify TaskError inherits from DomainError.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_task_error_hierarchy
def test_task_error_hierarchy() -> None:
    assert issubclass(TaskError, DomainError)
    assert issubclass(TaskError, Exception)
    assert TaskError.__mro__[1] is DomainError, (
        "TaskError must inherit from DomainError, not Exception directly"
    )


# START_CONTRACT: test_task_already_allocated_error
#   PURPOSE: Verify TaskAlreadyAllocatedError stores task_id and message mentions it.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_task_already_allocated_error
def test_task_already_allocated_error() -> None:
    exc = TaskAlreadyAllocatedError(task_id=42)
    assert exc.task_id == 42
    assert "already allocated" in str(exc)
    assert "42" in str(exc)


# START_CONTRACT: test_task_not_allocated_error
#   PURPOSE: Verify TaskNotAllocatedError stores task_id and message mentions it.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_task_not_allocated_error
def test_task_not_allocated_error() -> None:
    exc = TaskNotAllocatedError(task_id=99)
    assert exc.task_id == 99
    assert "not allocated" in str(exc)
    assert "99" in str(exc)


# START_CONTRACT: test_machine_busy_error
#   PURPOSE: Verify MachineBusyError stores ip and message contains it.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_busy_error
def test_machine_busy_error() -> None:
    exc = MachineBusyError(ip="10.0.0.1")
    assert exc.ip == "10.0.0.1"
    assert "busy" in str(exc)
    assert "10.0.0.1" in str(exc)


# START_CONTRACT: test_scheduling_error_hierarchy
#   PURPOSE: Verify SchedulingError inherits from DomainError.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_scheduling_error_hierarchy
def test_scheduling_error_hierarchy() -> None:
    assert issubclass(SchedulingError, DomainError)
    assert issubclass(SchedulingError, Exception)
    assert SchedulingError.__mro__[1] is DomainError, (
        "SchedulingError must inherit from DomainError, not Exception directly"
    )


# START_CONTRACT: test_no_compatible_node_error
#   PURPOSE: Verify NoCompatibleNodeError stores task_id and platforms.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_no_compatible_node_error
def test_no_compatible_node_error() -> None:
    platforms = ["linux", "gpu"]
    exc = NoCompatibleNodeError(task_id=7, platforms=platforms)
    assert exc.task_id == 7
    assert exc.platforms == platforms
    assert "no compatible node" in str(exc)


# START_CONTRACT: test_cloud_capacity_exhausted_error
#   PURPOSE: Verify CloudCapacityExhaustedError stores task_id and message mentions it.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_capacity_exhausted_error
def test_cloud_capacity_exhausted_error() -> None:
    exc = CloudCapacityExhaustedError(task_id=5)
    assert exc.task_id == 5
    assert "capacity exhausted" in str(exc)
    assert "5" in str(exc)


# START_CONTRACT: test_all_exceptions_importable
#   PURPOSE: Verify all 11 exception classes are importable from yascheduler.domain.exceptions.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_all_exceptions_importable
def test_all_exceptions_importable() -> None:
    """Verify all 11 exception classes import correctly by instantiating each once."""
    instances = [
        DomainError(),
        ValidationError(),
        UnsupportedEngineError(engine_name="x"),
        MissingInputFileError(engine_name="x", filename="f"),
        TaskError(),
        TaskAlreadyAllocatedError(task_id=1),
        TaskNotAllocatedError(task_id=2),
        MachineBusyError(ip="0.0.0.0"),
        SchedulingError(),
        NoCompatibleNodeError(task_id=3, platforms=["a"]),
        CloudCapacityExhaustedError(task_id=4),
    ]
    assert len(instances) == 11
    for inst in instances:
        assert isinstance(inst, Exception)
