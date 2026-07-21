"""LogFormatter with extra-diff trace discriminator for stdlib structured DEBUG tracing."""
# region MODULE_CONTRACT
# PURPOSE: Make internal trace flow observable via structured DEBUG logs without polluting user-facing output.
# SCOPE: LogFormatter only — renders trace records (DEBUG + in-package + extra-diff) as [module][funcName]:lineno msg sorted k=v; regular records as LEVEL name: message.
# INVARIANTS:
# - every `extra={...}` callsite uses flat user-supplied keys — no nested sentinel container such as `extra={"trace": {...}}`
# - every `extra={...}` callsite uses keys that do NOT collide with native `LogRecord` attribute names (enforced by the static guard in `tests/unit/test_log_scope_discipline.py`)
# KEYWORDS: logging, formatter, trace, structured logging, debug, discriminator
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging

__all__ = ["LogFormatter"]

# _NATIVE_KEYS: set of attribute names present on a freshly constructed
# LogRecord. Derived by introspection once at import time so that
# version-specific attributes (e.g. taskName in 3.12) are auto-included.
_NATIVE_KEYS = frozenset(
    logging.LogRecord("ref", logging.DEBUG, "<ref>", 0, "", (), None).__dict__.keys(),
)

# _PACKAGE: the top segment of this module's __name__ (e.g. "yascheduler"
# when imported as yascheduler.shared.log). Used both for the in-package
# gate and for the shortname strip — no hardcoded package literal.
_PACKAGE = __name__.split(".", 1)[0]


# region CLASS_LogFormatter
# PURPOSE: Let developers observe internal execution flow at DEBUG level while keeping production output clean.
class LogFormatter(logging.Formatter):
    """Formatter with two rendering branches rooted on the extra-diff discriminator.

    A record is a trace record iff ALL THREE hold:
      (a) record.levelno == logging.DEBUG, AND
      (b) set(record.__dict__) - _NATIVE_KEYS is non-empty, AND
      (c) record.name is in-package (record.name == _PACKAGE or starts with _PACKAGE + ".").

    Trace records render as:
        [<shortname>][<funcName>]:<lineno> <message> <k=v> <k=v>

    Regular records render as:
        <LEVEL> <name>: <message>
    """

    # region METHOD_format
    # PURPOSE: Route log records to trace or user-facing format based on the extra-diff discriminator.
    def format(self, record: logging.LogRecord) -> str:
        """Format a log record; trace records get the structured format."""
        if self._is_trace(record):
            return self._format_trace(record)
        return self._format_user(record)

    # endregion METHOD_format

    def _is_trace(self, record: logging.LogRecord) -> bool:
        """Check all three trace discriminator conditions."""
        # Condition 1: in-package logger name
        if record.name != _PACKAGE and not record.name.startswith(_PACKAGE + "."):
            return False
        # Condition 2: DEBUG level
        if record.levelno != logging.DEBUG:
            return False
        # Condition 3: carries extra attributes beyond native keys
        return bool(set(record.__dict__) - _NATIVE_KEYS)

    def _format_trace(self, record: logging.LogRecord) -> str:
        """Render a trace record: [shortname][funcName]:lineno msg k=v ..."""
        shortname = record.name.removeprefix(_PACKAGE + ".")
        extra_keys = sorted(set(record.__dict__) - _NATIVE_KEYS)
        kv = " ".join(f"{k}={record.__dict__[k]!r}" for k in extra_keys)
        return f"[{shortname}][{record.funcName}]:{record.lineno} {record.getMessage()} {kv}"

    def _format_user(self, record: logging.LogRecord) -> str:
        """Render a user-facing record: LEVEL name: message."""
        return f"{record.levelname} {record.name}: {record.getMessage()}"


# endregion CLASS_LogFormatter
