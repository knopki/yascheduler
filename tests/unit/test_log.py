# FILE: tests/unit/test_log.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for YaLogger and LogFormatter in yascheduler.shared.log.
#   SCOPE: YaLogger.trace() behavior, LogFormatter rendering, get_logger factory.
#   DEPENDS: none
#   LINKS: M-LOGGING
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_trace_emits_debug_record_with_block_and_fields - trace() emits DEBUG record with block and fields
#   test_trace_with_no_fields - trace() with no kwargs yields empty fields dict
#   test_trace_funcname_reflects_caller - trace() captures caller's funcName via stacklevel=2
#   test_get_logger_factory - get_logger returns YaLogger, namespaced name, trace works, idempotent
#   test_user_facing_methods_carry_no_grace_markers - info/warning/error emit records without block/fields
#   test_trace_is_debug_only - trace() at INFO threshold suppresses DEBUG record
#   test_log_formatter_trace_record - LogFormatter renders trace record with [M-ID][funcName][BLOCK] + sorted kv
#   test_log_formatter_user_facing_record - LogFormatter renders user-facing record as plain narrative
#   test_log_formatter_sets_shortname - LogFormatter sets record.shortname from name minus yascheduler. prefix
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Replace setLoggerClass tests with get_logger factory test; remove setLoggerClass-reliant tests.
#   PREVIOUS_CHANGE: v1.0.0 - Initial: YaLogger and LogFormatter unit tests.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.shared.log import YaLogger


class _RecordCollector(logging.Handler):
    """Handler that collects emitted LogRecords for test assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_logger(name: str = "test_logger") -> tuple[YaLogger, _RecordCollector]:
    """Create a YaLogger with a RecordCollector handler at DEBUG level."""
    from yascheduler.shared.log import YaLogger

    logger = YaLogger(name)
    collector = _RecordCollector()
    logger.addHandler(collector)
    logger.setLevel(logging.DEBUG)
    return logger, collector


def test_trace_emits_debug_record_with_block_and_fields() -> None:
    """trace() emits a DEBUG-level LogRecord carrying block and fields as programmatic attributes."""
    logger, collector = _make_logger()

    logger.trace("TEST_BLOCK", k=1)

    assert len(collector.records) == 1
    record = collector.records[0]
    assert record.levelno == logging.DEBUG
    assert record.block == "TEST_BLOCK"  # type: ignore[attr-defined]
    assert record.fields == {"k": 1}  # type: ignore[attr-defined]


def test_trace_with_no_fields() -> None:
    """trace() with no keyword arguments yields an empty fields dict."""
    logger, collector = _make_logger()

    logger.trace("BLOCK")

    assert len(collector.records) == 1
    record = collector.records[0]
    assert record.block == "BLOCK"  # type: ignore[attr-defined]
    assert record.fields == {}  # type: ignore[attr-defined]


def test_trace_funcname_reflects_caller() -> None:
    """trace() captures the caller's funcName, not 'trace' itself, via stacklevel=2."""
    logger, collector = _make_logger()

    logger.trace("BLOCK")

    assert len(collector.records) == 1
    record = collector.records[0]
    assert record.funcName == "test_trace_funcname_reflects_caller"


def test_get_logger_factory() -> None:
    """get_logger returns a YaLogger with namespaced name, .trace() works, idempotent."""
    from yascheduler.shared.log import YaLogger, get_logger

    log1 = get_logger("M-TEST")
    assert isinstance(log1, YaLogger)
    assert log1.name == "yascheduler.M-TEST"
    assert callable(log1.trace)

    # Capture trace record
    collector = _RecordCollector()
    log1.addHandler(collector)
    log1.setLevel(logging.DEBUG)

    log1.trace("TEST_BLOCK", k=1)

    assert len(collector.records) == 1
    record = collector.records[0]
    assert record.block == "TEST_BLOCK"  # type: ignore[attr-defined]
    assert record.fields == {"k": 1}  # type: ignore[attr-defined]
    assert record.funcName == "test_get_logger_factory"

    # Idempotent: second call returns same object
    log2 = get_logger("M-TEST")
    assert log2 is log1
    assert isinstance(log2, YaLogger)


def test_user_facing_methods_carry_no_grace_markers() -> None:
    """info/warning/error emit records without block or fields attributes."""
    logger, collector = _make_logger()

    logger.warning("webhook retry to %s", "http://example.com")

    assert len(collector.records) == 1
    record = collector.records[0]
    assert not hasattr(record, "block")
    assert not hasattr(record, "fields")


def test_trace_is_debug_only() -> None:
    """trace() at INFO threshold suppresses the DEBUG record (no propagation)."""
    from yascheduler.shared.log import YaLogger

    logger = YaLogger("test_logger")
    collector = _RecordCollector()
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)

    logger.trace("BLOCK", k=1)

    assert len(collector.records) == 0


def test_log_formatter_trace_record() -> None:
    """LogFormatter renders a trace record as [M-ID][funcName][BLOCK] + sorted key=value pairs."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    record = logging.LogRecord(
        name="yascheduler.M-APPLICATION-ALLOCATE",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="ALLOCATED",
        args=(),
        exc_info=None,
    )
    record.funcName = "allocate_task"
    record.block = "ALLOCATED"  # type: ignore[attr-defined]
    record.fields = {"ip": "10.0.0.1", "task_id": 7}  # type: ignore[attr-defined]

    output = formatter.format(record)

    assert "[M-APPLICATION-ALLOCATE]" in output
    assert "[allocate_task]" in output
    assert "[ALLOCATED]" in output
    # Fields sorted alphabetically: ip=... task_id=...
    assert "ip='10.0.0.1'" in output
    assert "task_id=7" in output
    # ip comes before task_id alphabetically
    assert output.index("ip=") < output.index("task_id=")


def test_log_formatter_user_facing_record() -> None:
    """LogFormatter renders a user-facing record as plain narrative without grace markers."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    record = logging.LogRecord(
        name="yascheduler.M-APPLICATION-ALLOCATE",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="webhook retry to %s",
        args=("http://example.com",),
        exc_info=None,
    )
    record.funcName = "send_webhook"

    output = formatter.format(record)

    assert "WARNING" in output
    assert "yascheduler.M-APPLICATION-ALLOCATE" in output
    assert "webhook retry to http://example.com" in output
    # No grace markers
    assert "[" not in output
    assert "=" not in output


def test_log_formatter_sets_shortname() -> None:
    """LogFormatter sets record.shortname from record.name minus 'yascheduler.' prefix."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    record = logging.LogRecord(
        name="yascheduler.M-APPLICATION-ALLOCATE",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="ALLOCATED",
        args=(),
        exc_info=None,
    )
    record.funcName = "allocate_task"
    record.block = "ALLOCATED"  # type: ignore[attr-defined]
    record.fields = {}  # type: ignore[attr-defined]

    formatter.format(record)

    assert record.shortname == "M-APPLICATION-ALLOCATE"  # type: ignore[attr-defined]
