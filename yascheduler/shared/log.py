"""LogFormatter with extra-diff trace discriminator for stdlib structured DEBUG tracing."""
# FILE: yascheduler/shared/log.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: LogFormatter with extra-diff trace discriminator for stdlib structured DEBUG tracing.
#   SCOPE: LogFormatter only — renders trace records (DEBUG + in-package + extra-diff) as [module][funcName]:lineno msg sorted k=v; regular records as LEVEL name: message.
#   DEPENDS: none
#   LINKS: M-LOGGING
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   LogFormatter - Formatter with extra-diff discriminator: trace records vs regular narrative
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Rewrite: remove YaLogger/get_logger; new trace discriminator (DEBUG + extra diff + in-package); _NATIVE_KEYS via introspection; _PACKAGE from __name__; no record.shortname mutation.
#   PREVIOUS_CHANGE: v1.1.0 - Add get_logger factory; reclasses cached Logger to YaLogger for static type correctness.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging

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

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record; trace records get the structured format."""
        if self._is_trace(record):
            return self._format_trace(record)
        return self._format_user(record)

    def _is_trace(self, record: logging.LogRecord) -> bool:
        """Check all three trace discriminator conditions."""
        # Condition 1: in-package logger name
        if record.name != _PACKAGE and not record.name.startswith(_PACKAGE + "."):
            return False
        # Condition 2: DEBUG level
        if record.levelno != logging.DEBUG:
            return False
        # Condition 3: carries extra attributes beyond native keys
        return set(record.__dict__) - _NATIVE_KEYS

    def _format_trace(self, record: logging.LogRecord) -> str:
        """Render a trace record: [shortname][funcName]:lineno msg k=v ..."""
        shortname = record.name.removeprefix(_PACKAGE + ".")
        extra_keys = sorted(set(record.__dict__) - _NATIVE_KEYS)
        kv = " ".join(f"{k}={record.__dict__[k]!r}" for k in extra_keys)
        return f"[{shortname}][{record.funcName}]:{record.lineno} {record.getMessage()} {kv}"

    def _format_user(self, record: logging.LogRecord) -> str:
        """Render a user-facing record: LEVEL name: message."""
        return f"{record.levelname} {record.name}: {record.getMessage()}"
