# FILE: yascheduler/adapters/cloud/utils.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Cloud helpers: random name generation and SSH key name extraction.
#   SCOPE: Random naming and SSH key name utilities.
#   DEPENDS: none
#   LINKS: M-CLOUD-API
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   get_rnd_name - Create random string with prefix
#   get_key_name - Get SSHKey's name
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Relocated from yascheduler/clouds/utils.py; no internal import changes.
# END_CHANGE_SUMMARY

"""Clouds helper utilities"""

import random
import string
from pathlib import PurePath
from typing import TypeVar

from asyncssh.public_key import SSHKey

T = TypeVar("T")


def get_rnd_name(prefix: str) -> str:
    """Create random string with prefix"""
    return (
        prefix
        + "-"
        + "".join([random.choice(string.ascii_lowercase) for _ in range(8)])
    )


def get_key_name(key: SSHKey) -> str:
    """Get SSHKey's name"""
    fname_opt = key.get_filename()
    key_filename = fname_opt.decode("utf-8") if fname_opt else None
    if key_filename:
        key_filename = PurePath(key_filename).name
    key_fingerprint = key.get_fingerprint("md5").split(":", maxsplit=1)[1]
    return key_filename or key.get_comment() or key_fingerprint
