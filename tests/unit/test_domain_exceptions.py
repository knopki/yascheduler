# FILE: tests/unit/test_domain_exceptions.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain exception hierarchy.
#   SCOPE: Test all 15 exception classes for inheritance, field access, and message format.
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
#   test_machine_connection_error_fields - ip and reason stored; message contains both
#   test_machine_connection_error_is_domain_error - catchable as DomainError and Exception
#   test_scheduling_error_hierarchy - SchedulingError inherits from DomainError
#   test_no_compatible_node_error - task_id + platforms stored
#   test_cloud_capacity_exhausted_error - task_id stored
#   test_cloud_capacity_exhausted_error_stays_under_scheduling - not a CloudError, is a SchedulingError
#   test_cloud_error_is_domain_error - CloudError is a DomainError, not a SchedulingError
#   test_cloud_allocate_error_under_cloud_error - CloudAllocateError catchable as CloudError/DomainError/Exception
#   test_cloud_setup_error_under_cloud_error - CloudSetupError catchable as CloudError/DomainError/Exception
#   test_cloud_errors_no_custom_init - leaf classes have no __init__ (free-form str)
#   test_cloud_error_free_form_message - str(CloudAllocateError(msg)) == msg
#   test_cloud_allocate_error_is_exception - CloudAllocateError is catchable as Exception
#   test_cloud_setup_error_is_exception - CloudSetupError is catchable as Exception
#   test_cloud_errors_importable_from_domain - CloudAllocateError/CloudSetupError importable from domain
#   test_cloud_errors_reexported_from_adapters - CloudAllocateError/CloudSetupError re-exported from adapters
#   test_cloud_error_importable_from_domain_exceptions - CloudError importable from yascheduler.domain.exceptions
#   test_cloud_error_importable_from_domain_package - CloudError importable from yascheduler.domain and in __all__
#   test_cloud_error_not_reexported_from_adapters - CloudError NOT importable from adapters.cloud
#   test_all_exceptions_importable - verify all 15 exceptions import from yascheduler.domain.exceptions
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Add CloudError hierarchy tests (cloud-error-hierarchy).
#   PREVIOUS_CHANGE: v1.1.0 - Add MachineConnectionError tests (gateway-port-cleanup).
# END_CHANGE_SUMMARY

import pytest

from yascheduler.domain.exceptions import (
    CloudAllocateError,
    CloudCapacityExhaustedError,
    CloudError,
    CloudSetupError,
    DomainError,
    MachineBusyError,
    MachineConnectionError,
    MissingInputFileError,
    NoCompatibleNodeError,
    SchedulingError,
    TaskAlreadyAllocatedError,
    TaskError,
    TaskNotAllocatedError,
    UnsupportedEngineError,
    ValidationError,
)
from yascheduler.domain.model import TaskId


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
    exc = TaskAlreadyAllocatedError(task_id=TaskId(42))
    assert exc.task_id == TaskId(42)
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
    exc = TaskNotAllocatedError(task_id=TaskId(99))
    assert exc.task_id == TaskId(99)
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


# START_CONTRACT: test_machine_connection_error_fields
#   PURPOSE: Verify MachineConnectionError stores ip and reason; message contains both.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_connection_error_fields
def test_machine_connection_error_fields() -> None:
    exc = MachineConnectionError(ip="10.0.0.1", reason="Connection refused")
    assert exc.ip == "10.0.0.1"
    assert exc.reason == "Connection refused"
    assert "10.0.0.1" in str(exc)
    assert "Connection refused" in str(exc)


# START_CONTRACT: test_machine_connection_error_is_domain_error
#   PURPOSE: Verify MachineConnectionError is catchable as DomainError and Exception.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_machine_connection_error_is_domain_error
def test_machine_connection_error_is_domain_error() -> None:
    assert issubclass(MachineConnectionError, DomainError)
    try:
        raise MachineConnectionError("10.0.0.1", "boom")
    except DomainError as e:
        assert isinstance(e, MachineConnectionError)
        assert e.ip == "10.0.0.1"


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
    exc = NoCompatibleNodeError(task_id=TaskId(7), platforms=platforms)
    assert exc.task_id == TaskId(7)
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
    exc = CloudCapacityExhaustedError(task_id=TaskId(5))
    assert exc.task_id == TaskId(5)
    assert "capacity exhausted" in str(exc)
    assert "5" in str(exc)


# START_CONTRACT: test_cloud_capacity_exhausted_error_stays_under_scheduling
#   PURPOSE: Verify CloudCapacityExhaustedError is a SchedulingError and NOT a CloudError (locks D2).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_capacity_exhausted_error_stays_under_scheduling
def test_cloud_capacity_exhausted_error_stays_under_scheduling() -> None:
    assert issubclass(CloudCapacityExhaustedError, SchedulingError)
    assert not issubclass(CloudCapacityExhaustedError, CloudError)


# START_CONTRACT: test_cloud_error_is_domain_error
#   PURPOSE: Verify CloudError is a DomainError and NOT a SchedulingError (locks D2 negative guard).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_error_is_domain_error
def test_cloud_error_is_domain_error() -> None:
    assert issubclass(CloudError, DomainError)
    assert not issubclass(CloudError, SchedulingError)
    try:
        raise CloudError("boom")
    except DomainError as e:
        assert isinstance(e, CloudError)
        assert str(e) == "boom"


# START_CONTRACT: test_cloud_allocate_error_under_cloud_error
#   PURPOSE: Verify CloudAllocateError subclasses CloudError and is catchable as CloudError/DomainError/Exception.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_allocate_error_under_cloud_error
def test_cloud_allocate_error_under_cloud_error() -> None:
    assert issubclass(CloudAllocateError, CloudError)
    assert issubclass(CloudAllocateError, DomainError)
    err = CloudAllocateError("create failed")
    with pytest.raises(CloudError):
        raise err
    with pytest.raises(DomainError):
        raise err
    with pytest.raises(Exception):  # noqa: PT011
        raise err


# START_CONTRACT: test_cloud_setup_error_under_cloud_error
#   PURPOSE: Verify CloudSetupError subclasses CloudError and is catchable as CloudError/DomainError/Exception.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_setup_error_under_cloud_error
def test_cloud_setup_error_under_cloud_error() -> None:
    assert issubclass(CloudSetupError, CloudError)
    assert issubclass(CloudSetupError, DomainError)
    err = CloudSetupError("setup failed")
    with pytest.raises(CloudError):
        raise err
    with pytest.raises(DomainError):
        raise err
    with pytest.raises(Exception):  # noqa: PT011
        raise err


# START_CONTRACT: test_cloud_errors_no_custom_init
#   PURPOSE: Verify the leaf cloud classes have no custom __init__ (free-form str contract).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_errors_no_custom_init
def test_cloud_errors_no_custom_init() -> None:
    assert "__init__" not in CloudAllocateError.__dict__
    assert "__init__" not in CloudSetupError.__dict__


# START_CONTRACT: test_cloud_error_free_form_message
#   PURPOSE: Verify the free-form str message is preserved verbatim on cloud exceptions.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_error_free_form_message
def test_cloud_error_free_form_message() -> None:
    assert str(CloudAllocateError("Unknown provider: foo")) == "Unknown provider: foo"
    assert str(CloudSetupError("Unknown provider: foo")) == "Unknown provider: foo"


# START_CONTRACT: test_cloud_allocate_error_is_exception
#   PURPOSE: Verify CloudAllocateError is catchable as Exception.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_allocate_error_is_exception
def test_cloud_allocate_error_is_exception() -> None:
    err = CloudAllocateError("provider unreachable")
    assert isinstance(err, Exception)
    assert "provider unreachable" in str(err)


# START_CONTRACT: test_cloud_setup_error_is_exception
#   PURPOSE: Verify CloudSetupError is catchable as Exception.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_setup_error_is_exception
def test_cloud_setup_error_is_exception() -> None:
    err = CloudSetupError("cloud-init failed")
    assert isinstance(err, Exception)
    assert "cloud-init failed" in str(err)


# START_CONTRACT: test_cloud_errors_importable_from_domain
#   PURPOSE: Verify CloudAllocateError and CloudSetupError are importable from domain.exceptions.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_errors_importable_from_domain
def test_cloud_errors_importable_from_domain() -> None:
    from yascheduler.domain.exceptions import (
        CloudAllocateError as DomainCAE,
    )
    from yascheduler.domain.exceptions import (
        CloudSetupError as DomainCSE,
    )

    assert DomainCAE is CloudAllocateError
    assert DomainCSE is CloudSetupError


# START_CONTRACT: test_cloud_errors_reexported_from_adapters
#   PURPOSE: Verify CloudAllocateError and CloudSetupError are re-exported from yascheduler.infra.cloud.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_errors_reexported_from_adapters
def test_cloud_errors_reexported_from_adapters() -> None:
    from yascheduler.infra.cloud import (
        CloudAllocateError as AdapterCAE,
    )
    from yascheduler.infra.cloud import (
        CloudSetupError as AdapterCSE,
    )

    assert AdapterCAE is CloudAllocateError
    assert AdapterCSE is CloudSetupError


# START_CONTRACT: test_cloud_error_importable_from_domain_exceptions
#   PURPOSE: Verify CloudError is importable from yascheduler.domain.exceptions.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_error_importable_from_domain_exceptions
def test_cloud_error_importable_from_domain_exceptions() -> None:
    from yascheduler.domain.exceptions import CloudError as ImportedCE

    assert ImportedCE is CloudError


# START_CONTRACT: test_cloud_error_importable_from_domain_package
#   PURPOSE: Verify CloudError is importable from yascheduler.domain and listed in __all__.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_error_importable_from_domain_package
def test_cloud_error_importable_from_domain_package() -> None:
    import yascheduler.domain as domain_pkg
    from yascheduler.domain import CloudError as PackageCE

    assert PackageCE is CloudError
    assert "CloudError" in domain_pkg.__all__


# START_CONTRACT: test_cloud_error_not_reexported_from_adapters
#   PURPOSE: Verify CloudError is NOT importable from yascheduler.infra.cloud.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_cloud_error_not_reexported_from_adapters
def test_cloud_error_not_reexported_from_adapters() -> None:
    with pytest.raises(ImportError):
        from yascheduler.infra.cloud import (  # noqa: F401
            CloudError,
        )


# START_CONTRACT: test_all_exceptions_importable
#   PURPOSE: Verify all 15 exception classes are importable from yascheduler.domain.exceptions.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS:
# END_CONTRACT: test_all_exceptions_importable
def test_all_exceptions_importable() -> None:
    """Verify all 15 exception classes import correctly by instantiating each once."""
    instances = [
        DomainError(),
        ValidationError(),
        UnsupportedEngineError(engine_name="x"),
        MissingInputFileError(engine_name="x", filename="f"),
        TaskError(),
        TaskAlreadyAllocatedError(task_id=TaskId(1)),
        TaskNotAllocatedError(task_id=TaskId(2)),
        MachineBusyError(ip="0.0.0.0"),
        MachineConnectionError(ip="0.0.0.0", reason="x"),
        SchedulingError(),
        NoCompatibleNodeError(task_id=TaskId(3), platforms=["a"]),
        CloudCapacityExhaustedError(task_id=TaskId(4)),
        CloudError("test"),
        CloudAllocateError("test"),
        CloudSetupError("test"),
    ]
    assert len(instances) == 15
    for inst in instances:
        assert isinstance(inst, Exception)
