# FILE: tests/log_assertions.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Shared helpers for log-driven test assertions against the stdlib `debug(msg, extra=...)` trace contract.
#   SCOPE: extra_fields(rec) — reconstruct the structured trace fields dict from a LogRecord by diffing its attributes against the introspection-derived native LogRecord attribute set.
#   DEPENDS: yascheduler.shared.log (_NATIVE_KEYS)
#   LINKS: M-LOGGING
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   extra_fields - dict of record attributes beyond the native LogRecord key set (the structured trace fields)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial: extract extra-diff helper shared by unit and e2e log-driven assertions (switch-to-standard-logging).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yascheduler.shared.log import _NATIVE_KEYS

if TYPE_CHECKING:
    import logging


def extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {k: getattr(record, k) for k in record.__dict__ if k not in _NATIVE_KEYS}
