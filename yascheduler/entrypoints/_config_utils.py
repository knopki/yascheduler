"""Parser-side config helpers — warning for unknown INI keys and optional-string coercion."""
# region MODULE_CONTRACT
# PURPOSE: Provide parser-side config helpers — warning for unknown INI keys and optional-string coercion — consumed only by entrypoints.config_parser.
# SCOPE: ConfigWarning, warn_unknown_fields, opt_str_val; consumed only by entrypoints.config_parser.
# KEYWORDS: config, parser, warning, ini, validation, helpers
# endregion MODULE_CONTRACT

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
    msg = f"expected Optional[str], got {type(value).__name__}"
    raise ValueError(msg)
