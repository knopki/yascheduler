"""Clouds helper utilities."""
# region MODULE_CONTRACT
# PURPOSE: Generate unique resource names (VMs, NICs, SSH keys) so cloud providers that require distinct identifiers never collide within a project.
# SCOPE: Random naming utility.
# KEYWORDS: random, name generation, utility
# endregion MODULE_CONTRACT

import random
import string

__all__ = [
    "get_rnd_name",
]


def get_rnd_name(prefix: str) -> str:
    """Create random string with prefix."""
    return (
        prefix
        + "-"
        + "".join(
            [random.choice(string.ascii_lowercase) for _ in range(8)],  # noqa: S311
        )  # non-crypto jitter, not for secrets
    )
