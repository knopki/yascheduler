# FILE: yascheduler/entrypoints/_config_utils.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Parser-side config helpers — warning for unknown INI keys and optional-string coercion.
#   SCOPE: ConfigWarning, warn_unknown_fields, opt_str_val; consumed only by entrypoints.config_parser.
#   DEPENDS: none
#   LINKS: M-ENTRYPOINTS-CONFIG-PARSER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ConfigWarning - Warning class for config issues (unknown keys etc.)
#   warn_unknown_fields - Emit ConfigWarning for unrecognized config section keys
#   opt_str_val - Coerce a value to Optional[str] (None or str); parser-side helper
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Relocate ConfigWarning, warn_unknown_fields, opt_str_val from yascheduler.config.utils to entrypoints/_config_utils.py and migrate to stdlib (config-aggregate-to-entrypoints / P4); drop attrs dependency. make_default_field and config_repr dropped (attrs-specific / unused).
# END_CHANGE_SUMMARY

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from configparser import SectionProxy


class ConfigWarning(Warning):
    """Warning about config (e.g. unknown INI keys)."""


def warn_unknown_fields(known_fields: Sequence[str], sec: SectionProxy) -> None:
    """Emit a ConfigWarning for keys in sec that are not in known_fields."""
    unknown_fields = list(set(sec.keys()) - set(known_fields))
    if unknown_fields:
        warnings.warn(
            f"Config section {sec.name} unknown fields: {', '.join(unknown_fields)}",
            ConfigWarning,
            3,
        )


def opt_str_val(value: object) -> str | None:
    """Coerce value to Optional[str]: None stays None, str passes through, else raise.

    Replaces the former attrs optional-str validator for parser-side use.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError(f"expected Optional[str], got {type(value).__name__}")
