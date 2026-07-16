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
# ENSURES: Returns is_file() entries only; keys_dir is a Path in production but tests may pass MagicMock.
def list_private_keys(keys_dir: Path) -> Sequence[PurePath]:
    """List private key file paths."""
    # region BLOCK_scan_keys_dir
    # Call iterdir() directly on keys_dir rather than Path(keys_dir).iterdir():
    # tests pass a MagicMock whose __fspath__ is intentionally absent, so Path(keys_dir)
    # would raise TypeError. keys_dir is expected to be a Path in production.
    filepaths = filter(lambda x: x.is_file(), keys_dir.iterdir())
    # endregion BLOCK_scan_keys_dir
    return list(filepaths)


# endregion FUNC_list_private_keys
