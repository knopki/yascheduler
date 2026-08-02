# region MODULE_CONTRACT
# PURPOSE: Unit tests for yascheduler.shared.compat version-branch re-exports.
# SCOPE: StrEnum, Self, Unpack importability and __all__ membership.
# KEYWORDS: StrEnum, Self, Unpack, re-exports, Python compat
# endregion MODULE_CONTRACT

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


def test_typeis_in_all() -> None:
    """TypeIs is listed in compat.__all__."""
    assert "TypeIs" in compat.__all__


def test_typeis_importable_from_shared() -> None:
    """TypeIs is re-exported from yascheduler.shared."""
    from yascheduler.shared import TypeIs

    assert TypeIs is not None
