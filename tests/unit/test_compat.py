# FILE: tests/unit/test_compat.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yascheduler.shared.compat version-branch re-exports.
#   SCOPE: StrEnum, Self, Unpack importability and __all__ membership.
#   DEPENDS: none
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_strenum_is_importable - StrEnum is importable from shared.compat on any supported Python version
#   test_strenum_in_all - StrEnum is listed in compat.__all__
#   test_self_in_all - Self is in __all__
#   test_unpack_in_all - Unpack is in __all__
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial: StrEnum re-export tests for node-rename-and-fields change.
#   PREVIOUS_CHANGE: N/A
# END_CHANGE_SUMMARY

from yascheduler.shared import compat


def test_strenum_is_importable() -> None:
    """StrEnum can be imported from yascheduler.shared.compat."""
    from yascheduler.shared.compat import StrEnum

    # Verify it's a class that can be subclassed for string enums
    class _TestEnum(StrEnum):
        A = "a"

    assert _TestEnum.A == "a"
    assert isinstance(_TestEnum.A, str)


def test_strenum_in_all() -> None:
    """StrEnum is listed in compat.__all__."""
    assert "StrEnum" in compat.__all__


def test_self_in_all() -> None:
    """Self is listed in compat.__all__."""
    assert "Self" in compat.__all__


def test_unpack_in_all() -> None:
    """Unpack is listed in compat.__all__."""
    assert "Unpack" in compat.__all__
