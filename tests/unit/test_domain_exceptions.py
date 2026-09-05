# region MODULE_CONTRACT
# PURPOSE: Unit tests for domain exception hierarchy.
# SCOPE: Test all 13 exception classes for inheritance, field access, and message format.
# KEYWORDS: domain exception hierarchy, inheritance, message format
# endregion MODULE_CONTRACT

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
    TaskError,
    UnsupportedEngineError,
    ValidationError,
)
from yascheduler.domain.model import NodeId, TaskId


def test_domain_error_is_exception() -> None:
    assert issubclass(DomainError, Exception)
    try:
        raise DomainError("test")
    except Exception as e:
        assert isinstance(e, DomainError)
        assert str(e) == "test"


def test_validation_error_hierarchy() -> None:
    assert issubclass(ValidationError, DomainError)
    assert issubclass(ValidationError, Exception)
    # ValidationError should NOT be a direct subclass of Exception
    assert ValidationError.__mro__[1] is DomainError, (
        "ValidationError must inherit from DomainError, not Exception directly"
    )


def test_unsupported_engine_error_fields() -> None:
    exc = UnsupportedEngineError(engine_name="gromacs")
    assert exc.engine_name == "gromacs"
    assert "unsupported engine" in str(exc)
    assert "gromacs" in str(exc)


def test_missing_input_file_error_fields() -> None:
    exc = MissingInputFileError(engine_name="gromacs", filename="topol.top")
    assert exc.engine_name == "gromacs"
    assert exc.filename == "topol.top"
    assert "missing input file" in str(exc)
    assert "topol.top" in str(exc)
    assert "gromacs" in str(exc)


def test_task_error_hierarchy() -> None:
    assert issubclass(TaskError, DomainError)
    assert issubclass(TaskError, Exception)
    assert TaskError.__mro__[1] is DomainError, (
        "TaskError must inherit from DomainError, not Exception directly"
    )


def test_machine_busy_error() -> None:
    exc = MachineBusyError(NodeId(1))
    assert exc.node_id == NodeId(1)
    assert not hasattr(exc, "hostname")
    assert str(exc) == "machine (1) is busy"


def test_machine_connection_error_fields() -> None:
    exc = MachineConnectionError(NodeId(1), "10.0.0.1", "Connection refused")
    assert exc.node_id == NodeId(1)
    assert exc.hostname == "10.0.0.1"
    assert exc.reason == "Connection refused"
    assert "10.0.0.1" in str(exc)
    assert "Connection refused" in str(exc)
    assert "1" in str(exc)


def test_machine_connection_error_is_domain_error() -> None:
    assert issubclass(MachineConnectionError, DomainError)
    try:
        raise MachineConnectionError(NodeId(1), "10.0.0.1", "boom")
    except DomainError as e:
        assert isinstance(e, MachineConnectionError)
        assert e.node_id == NodeId(1)
        assert e.hostname == "10.0.0.1"


def test_scheduling_error_hierarchy() -> None:
    assert issubclass(SchedulingError, DomainError)
    assert issubclass(SchedulingError, Exception)
    assert SchedulingError.__mro__[1] is DomainError, (
        "SchedulingError must inherit from DomainError, not Exception directly"
    )


def test_no_compatible_node_error() -> None:
    platforms = ["linux", "gpu"]
    exc = NoCompatibleNodeError(task_id=TaskId(7), platforms=platforms)
    assert exc.task_id == TaskId(7)
    assert exc.platforms == platforms
    assert "no compatible node" in str(exc)


def test_cloud_capacity_exhausted_error() -> None:
    exc = CloudCapacityExhaustedError(task_id=TaskId(5))
    assert exc.task_id == TaskId(5)
    assert "capacity exhausted" in str(exc)
    assert "5" in str(exc)


def test_cloud_capacity_exhausted_error_stays_under_scheduling() -> None:
    assert issubclass(CloudCapacityExhaustedError, SchedulingError)
    assert not issubclass(CloudCapacityExhaustedError, CloudError)


def test_cloud_error_is_domain_error() -> None:
    assert issubclass(CloudError, DomainError)
    assert not issubclass(CloudError, SchedulingError)
    try:
        raise CloudError("boom")
    except DomainError as e:
        assert isinstance(e, CloudError)
        assert str(e) == "boom"


def test_cloud_allocate_error_under_cloud_error() -> None:
    assert issubclass(CloudAllocateError, CloudError)
    assert issubclass(CloudAllocateError, DomainError)
    err = CloudAllocateError("create failed")
    with pytest.raises(CloudError):
        raise err
    with pytest.raises(DomainError):
        raise err
    with pytest.raises(Exception):
        raise err


def test_cloud_setup_error_under_cloud_error() -> None:
    assert issubclass(CloudSetupError, CloudError)
    assert issubclass(CloudSetupError, DomainError)
    err = CloudSetupError("setup failed")
    with pytest.raises(CloudError):
        raise err
    with pytest.raises(DomainError):
        raise err
    with pytest.raises(Exception):
        raise err


def test_cloud_errors_no_custom_init() -> None:
    assert "__init__" not in CloudAllocateError.__dict__
    assert "__init__" not in CloudSetupError.__dict__


def test_cloud_error_free_form_message() -> None:
    assert str(CloudAllocateError("Unknown provider: foo")) == "Unknown provider: foo"
    assert str(CloudSetupError("Unknown provider: foo")) == "Unknown provider: foo"


def test_cloud_allocate_error_is_exception() -> None:
    err = CloudAllocateError("provider unreachable")
    assert isinstance(err, Exception)
    assert "provider unreachable" in str(err)


def test_cloud_setup_error_is_exception() -> None:
    err = CloudSetupError("cloud-init failed")
    assert isinstance(err, Exception)
    assert "cloud-init failed" in str(err)


def test_cloud_errors_importable_from_domain() -> None:
    from yascheduler.domain.exceptions import (
        CloudAllocateError as DomainCAE,
    )
    from yascheduler.domain.exceptions import (
        CloudSetupError as DomainCSE,
    )

    assert DomainCAE is CloudAllocateError
    assert DomainCSE is CloudSetupError


def test_cloud_errors_reexported_from_adapters() -> None:
    from yascheduler.infra.cloud import (
        CloudAllocateError as AdapterCAE,
    )
    from yascheduler.infra.cloud import (
        CloudSetupError as AdapterCSE,
    )

    assert AdapterCAE is CloudAllocateError
    assert AdapterCSE is CloudSetupError


def test_cloud_error_importable_from_domain_exceptions() -> None:
    from yascheduler.domain.exceptions import CloudError as ImportedCE

    assert ImportedCE is CloudError


def test_cloud_error_importable_from_domain_package() -> None:
    import yascheduler.domain as domain_pkg
    from yascheduler.domain import CloudError as PackageCE

    assert PackageCE is CloudError
    assert "CloudError" in domain_pkg.__all__


def test_cloud_error_not_reexported_from_adapters() -> None:
    with pytest.raises(ImportError):
        from yascheduler.infra.cloud import CloudError  # noqa: F401


def test_all_exceptions_importable() -> None:
    """Verify all 13 exception classes import correctly by instantiating each once."""
    instances = [
        DomainError(),
        ValidationError(),
        UnsupportedEngineError(engine_name="x"),
        MissingInputFileError(engine_name="x", filename="f"),
        TaskError(),
        MachineBusyError(NodeId(1)),
        MachineConnectionError(NodeId(1), "0.0.0.0", "x"),
        SchedulingError(),
        NoCompatibleNodeError(task_id=TaskId(3), platforms=["a"]),
        CloudCapacityExhaustedError(task_id=TaskId(4)),
        CloudError("test"),
        CloudAllocateError("test"),
        CloudSetupError("test"),
    ]
    assert len(instances) == 13
    for inst in instances:
        assert isinstance(inst, Exception)
