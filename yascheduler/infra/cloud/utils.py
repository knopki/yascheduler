"""Clouds helper utilities."""
# FILE: yascheduler/infra/cloud/utils.py
# VERSION: 1.1.1
#
# START_MODULE_CONTRACT
#   PURPOSE: Cloud helper: random name generation.
#   SCOPE: Random naming utility.
#   DEPENDS: none
#   LINKS: M-CLOUD-PROVISIONER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   get_rnd_name - Create random string with prefix
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/; no behavioral change.
#   PREVIOUS_CHANGE: v1.1.0 - Move get_key_name to ssh_keys.py.
# END_CHANGE_SUMMARY

import random
import string


def get_rnd_name(prefix: str) -> str:
    """Create random string with prefix."""
    return (
        prefix
        + "-"
        + "".join(
            [random.choice(string.ascii_lowercase) for _ in range(8)],  # noqa: S311
        )  # non-crypto jitter, not for secrets
    )
