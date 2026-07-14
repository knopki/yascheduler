# FILE: yascheduler/shared/log.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: YaLogger subclass and LogFormatter for GRACE-lite structured tracing.
#   SCOPE: YaLogger(logging.Logger) with trace(block, /, **fields); LogFormatter with two rendering branches.
#   DEPENDS: none
#   LINKS: M-LOGGING
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   YaLogger - Logger subclass exposing trace(block, /, **fields) for structured DEBUG tracing
#   LogFormatter - Formatter with trace-record and user-facing rendering branches
#   get_logger - Factory: create a YaLogger with yascheduler. namespace prefix, reclassing for type correctness
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Add get_logger factory; reclasses cached Logger to YaLogger for static type correctness.
#   PREVIOUS_CHANGE: v1.0.0 - Initial: YaLogger and LogFormatter for reform-grace-logging.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from typing import Any, cast


def get_logger(name: str) -> YaLogger:
    """Factory: create a YaLogger with yascheduler. namespace prefix.

    Prepends 'yascheduler.' to name, looks up via logging.getLogger,
    and reclasses the returned instance to YaLogger for static type
    correctness.
    """
    logger = logging.getLogger(f"yascheduler.{name}")
    logger.__class__ = YaLogger
    return cast("YaLogger", logger)


class YaLogger(logging.Logger):
    """Logger subclass adding trace(block, /, **fields) for structured DEBUG tracing."""

    # START_CONTRACT: trace
    #   PURPOSE: Emit a DEBUG-level record carrying a block marker and structured fields for GRACE-lite tracing.
    #   INPUTS: { block: str - The block marker string (positional-only), **fields: object - Structured key-value pairs }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Emits a DEBUG LogRecord via self.debug with extra={block, fields} and stacklevel=2.
    #   LINKS: M-LOGGING
    # END_CONTRACT: trace
    def trace(self, block: str, /, **fields: object) -> None:
        self.debug(block, extra={"block": block, "fields": fields}, stacklevel=2)


class LogFormatter(logging.Formatter):
    """Formatter with two rendering branches: trace records and user-facing records.

    Trace records (carrying record.fields) render as:
        [shortname][funcName][block] key=value ...
    User-facing records render as plain:
        LEVEL name: message
    """

    # START_CONTRACT: format
    #   PURPOSE: Render a LogRecord — trace records (with .fields) get structured [shortname][funcName][block] k=v output; user-facing records get plain LEVEL name: message.
    #   INPUTS: { record: logging.LogRecord - The record to format }
    #   OUTPUTS: { str - The formatted log line }
    #   SIDE_EFFECTS: Sets record.shortname as a side-effect for downstream consumers.
    #   LINKS: M-LOGGING
    # END_CONTRACT: format
    def format(self, record: logging.LogRecord) -> str:
        setattr(record, "shortname", record.name.removeprefix("yascheduler."))
        fields: dict[str, Any] | None = getattr(record, "fields", None)

        if fields is not None:
            return self._format_trace(record, fields)
        return self._format_user(record)

    def _format_trace(self, record: logging.LogRecord, fields: dict[str, Any]) -> str:
        """Render a trace record: [shortname][funcName][block] k=v ..."""
        block = record.getMessage()
        kv = " ".join(f"{k}={v!r}" for k, v in sorted(fields.items()))
        shortname = record.shortname  # type: ignore[attr-defined]
        return f"[{shortname}][{record.funcName}][{block}] {kv}"

    def _format_user(self, record: logging.LogRecord) -> str:
        """Render a user-facing record: LEVEL name: message"""
        return f"{record.levelname} {record.name}: {record.getMessage()}"
