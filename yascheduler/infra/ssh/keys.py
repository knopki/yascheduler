"""Pure-function SSH private-key discovery from a keys directory."""
# FILE: yascheduler/infra/ssh/keys.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Pure-function SSH private-key discovery from a keys directory.
#   SCOPE: list_private_keys(keys_dir) — scan a directory and return the file paths it contains.
#   DEPENDS: none
#   LINKS: M-SSH-KEYS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   list_private_keys - List private-key file paths from a keys directory
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extract ConfigLocal.get_private_keys() into this pure module-level function. Same scan + is_file() filtering; takes an explicit keys_dir argument instead of reading instance state.
# END_CHANGE_SUMMARY

from collections.abc import Sequence
from pathlib import Path, PurePath


# START_CONTRACT: list_private_keys
#   PURPOSE: List private-key file paths from the given keys directory.
#   INPUTS: { keys_dir: Path - directory to scan for private-key files }
#   OUTPUTS: { Sequence[PurePath] - file paths (is_file() entries) found in keys_dir }
#   SIDE_EFFECTS: Reads the filesystem (iterdir + is_file on each entry).
#   LINKS: M-SSH-KEYS
# END_CONTRACT: list_private_keys
def list_private_keys(keys_dir: Path) -> Sequence[PurePath]:
    """List private key file paths."""
    # START_BLOCK_SCAN_KEYS_DIR
    # Call iterdir() directly on keys_dir rather than Path(keys_dir).iterdir():
    # tests pass a MagicMock whose __fspath__ is intentionally absent, so Path(keys_dir)
    # would raise TypeError. keys_dir is expected to be a Path in production.
    filepaths = filter(lambda x: x.is_file(), keys_dir.iterdir())
    # END_BLOCK_SCAN_KEYS_DIR
    return list(filepaths)
