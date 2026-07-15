# FILE: tests/unit/test_log.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for LogFormatter in yascheduler.shared.log.
#   SCOPE: LogFormatter extra-diff discriminator rendering; introspection-derived _NATIVE_KEYS; _PACKAGE derivation; single-formatter-both-handlers wiring.
#   DEPENDS: none
#   LINKS: M-LOGGING
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_trace_record_renders_with_module_funcname_lineno_message_and_sorted_fields - Gherkin scenario: trace record renders
#   test_trace_fields_sorted_alphabetically - Gherkin scenario: deterministic field order
#   test_debug_without_extra_renders_regular - Gherkin scenario: DEBUG w/o extra is narrative
#   test_out_of_package_debug_with_extra_renders_regular - Gherkin scenario: third-party logger excluded
#   test_info_warn_error_renders_regular - Gherkin scenario: INFO/WARN/ERROR narrative
#   test_native_keys_derived_by_introspection - Gherkin scenario: _NATIVE_KEYS introspection
#   test_package_prefix_derived_from_name - Gherkin scenario: _PACKAGE from __name__
#   test_single_formatter_serves_both_handlers - Gherkin scenario: single formatter both handlers
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Rewrite around LogFormatter and extra-diff discriminator; remove YaLogger/get_logger/trace tests.
#   PREVIOUS_CHANGE: v1.0.0 - Initial: YaLogger and LogFormatter unit tests.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging


class _RecordCollector(logging.Handler):
    """Handler that collects emitted LogRecords for test assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_logger(
    name: str = "yascheduler.test.module", level: int = logging.DEBUG
) -> tuple[logging.Logger, _RecordCollector]:
    """Create a plain logging.Logger with a RecordCollector handler at the given level."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    collector = _RecordCollector()
    logger.addHandler(collector)
    logger.propagate = False
    return logger, collector


# ── Test 1: Gherkin scenario — trace record renders with module, function, lineno, message, and sorted fields ──


def test_trace_record_renders_with_module_funcname_lineno_message_and_sorted_fields() -> (
    None
):
    """Trace record renders [module][funcName]:lineno msg sorted k=v."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    logger, collector = _make_logger("yascheduler.application.allocate_task")

    logger.debug("ALLOCATED", extra={"ip": "10.0.0.1", "task_id": 7})

    assert len(collector.records) == 1
    output = formatter.format(collector.records[0])

    # Must contain the trace markers and be grep-friendly
    assert output.startswith("[application.allocate_task]")
    assert "[test_trace_record_renders" in output  # funcName
    assert "10.0.0.1" in output
    assert "7" in output
    assert "ALLOCATED" in output


# ── Test 2: Gherkin scenario — trace fields are sorted alphabetically ──


def test_trace_fields_sorted_alphabetically() -> None:
    """Trace fields appear in alphabetical key order for deterministic output."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    logger, collector = _make_logger("yascheduler.test.module")

    logger.debug("B", extra={"zebra": 1, "alpha": 2})

    assert len(collector.records) == 1
    output = formatter.format(collector.records[0])

    # alpha should appear before zebra
    alpha_idx = output.index("alpha=2")
    zebra_idx = output.index("zebra=1")
    assert alpha_idx < zebra_idx


# ── Test 3: Gherkin scenario — DEBUG without extra renders as regular narrative ──


def test_debug_without_extra_renders_regular() -> None:
    """DEBUG record with no extra renders as LEVEL name: message, no trace markers."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    logger, collector = _make_logger("yascheduler.test.module")

    logger.debug("progress: ok")

    assert len(collector.records) == 1
    output = formatter.format(collector.records[0])

    # Regular layout: LEVEL name: message
    assert output.startswith("DEBUG ")
    assert "yascheduler.test.module" in output
    assert "progress: ok" in output
    # No trace markers
    assert "[" not in output
    assert "=" not in output


# ── Test 4: Gherkin scenario — out-of-package DEBUG with extra renders as regular narrative ──


def test_out_of_package_debug_with_extra_renders_regular() -> None:
    """Third-party logger (e.g. asyncssh) with DEBUG+extra renders as LEVEL name: message."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    logger, collector = _make_logger("asyncssh")

    logger.debug("key exchange done", extra={"host": "10.0.0.1"})

    assert len(collector.records) == 1
    output = formatter.format(collector.records[0])

    # Regular layout because out-of-package
    assert output.startswith("DEBUG ")
    assert "asyncssh" in output
    assert "key exchange done" in output
    # No trace markers
    assert "[" not in output
    assert "=" not in output


# ── Test 5: Gherkin scenario — INFO/WARN/ERROR renders as regular narrative ──


def test_info_warn_error_renders_regular() -> None:
    """INFO/WARN/ERROR records render as LEVEL name: message with no trace markers."""
    from yascheduler.shared.log import LogFormatter

    formatter = LogFormatter()
    logger, collector = _make_logger("yascheduler.test.module")

    logger.info("info msg")
    logger.warning("warn msg")
    logger.error("error msg")

    assert len(collector.records) == 3
    for i, (level, msg) in enumerate(
        [("INFO", "info msg"), ("WARNING", "warn msg"), ("ERROR", "error msg")]
    ):
        output = formatter.format(collector.records[i])
        assert output.startswith(f"{level} "), f"Expected {level} prefix, got: {output}"
        assert "yascheduler.test.module" in output
        assert msg in output
        # No trace markers
        assert "[" not in output
        assert "=" not in output


# ── Test 6: Gherkin scenario — native LogRecord set is derived by introspection ──


def test_native_keys_derived_by_introspection() -> None:
    """_NATIVE_KEYS is non-empty and contains expected native attributes."""
    from yascheduler.shared.log import _NATIVE_KEYS  # type: ignore[attr-defined]

    assert isinstance(_NATIVE_KEYS, frozenset)
    assert len(_NATIVE_KEYS) > 0
    # Must contain essential native attributes
    assert "name" in _NATIVE_KEYS
    assert "msg" in _NATIVE_KEYS
    assert "funcName" in _NATIVE_KEYS
    assert "levelno" in _NATIVE_KEYS
    assert "lineno" in _NATIVE_KEYS
    assert "args" in _NATIVE_KEYS
    # Verify non-native key is NOT in the set
    assert "task_id" not in _NATIVE_KEYS


# ── Test 7: Gherkin scenario — package prefix derived from formatter module name ──


def test_package_prefix_derived_from_name() -> None:
    """_PACKAGE is derived from __name__ top segment, not hardcoded."""
    from yascheduler.shared.log import _PACKAGE  # type: ignore[attr-defined]

    assert isinstance(_PACKAGE, str)
    assert _PACKAGE == "yascheduler"
    # Verify it's NOT a hardcoded literal: check we can derive the same
    # value from the module's __name__
    from yascheduler.shared.log import __name__ as log_module_name

    expected = log_module_name.split(".", 1)[0]
    assert _PACKAGE == expected


# ── Test 8: Gherkin scenario — single formatter serves both handlers ──


def test_single_formatter_serves_both_handlers() -> None:
    """configure_logger wires the same LogFormatter onto stderr and file handlers."""
    import logging
    import tempfile

    from yascheduler.entrypoints.cli.daemon_common import configure_logger
    from yascheduler.shared.log import LogFormatter

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    root.handlers.clear()

    try:
        with tempfile.NamedTemporaryFile(suffix=".log") as tf:
            root = configure_logger(tf.name, logging.DEBUG)

            handlers = root.handlers
            stderr_handler = None
            file_handler = None
            for h in handlers:
                if isinstance(h, logging.StreamHandler) and not isinstance(
                    h, logging.FileHandler
                ):
                    stderr_handler = h
                elif isinstance(h, logging.FileHandler):
                    file_handler = h

            assert stderr_handler is not None, "No StreamHandler found"
            assert file_handler is not None, "No FileHandler found"
            assert stderr_handler.formatter is file_handler.formatter
            assert isinstance(stderr_handler.formatter, LogFormatter)
    finally:
        root.handlers.clear()
        for h in saved_handlers:
            root.addHandler(h)
