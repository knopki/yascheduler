"""Pure-function SSH private-key discovery from a keys directory."""
# region MODULE_CONTRACT
# PURPOSE: Pure-function SSH private-key discovery — scan a directory and return file paths.
# SCOPE: list_private_keys(keys_dir) — reads filesystem, returns paths.
# KEYWORDS: ssh keys, private keys, discovery, list_private_keys
# endregion MODULE_CONTRACT

from collections.abc import Sequence
from pathlib import Path, PurePath

__all__ = ["list_private_keys"]


# region FUNC_list_private_keys
# PURPOSE: List private-key file paths from the given keys directory.
# ENSURES: Returns is_file() entries only AND excludes .pub files.
def list_private_keys(keys_dir: Path) -> Sequence[PurePath]:
    """List private key file paths, skipping public keys (.pub)."""
    filepaths = (x for x in keys_dir.iterdir() if x.is_file() and x.suffix != ".pub")
    return list(filepaths)


# endregion FUNC_list_private_keys
