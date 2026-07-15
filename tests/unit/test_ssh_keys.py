# FILE: tests/unit/test_ssh_keys.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for list_private_keys pure-function SSH key discovery.
#   SCOPE: list_private_keys scans a keys directory and returns the file paths it contains.
#   DEPENDS: M-SSH-KEYS
#   LINKS: M-SSH-KEYS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_list_private_keys_returns_file_paths - returns file paths from a populated keys_dir
#   test_list_private_keys_skips_subdirectories - subdirectories are filtered out (is_file() == False)
#   test_list_private_keys_empty_dir_returns_empty - empty keys_dir yields an empty sequence
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial list_private_keys unit tests (ssh-keys-extraction-vastai-parser-fix).
# END_CHANGE_SUMMARY

from pathlib import Path, PurePath

from yascheduler.infra.ssh.keys import list_private_keys


# START_CONTRACT: test_list_private_keys_returns_file_paths
#   PURPOSE: Verify list_private_keys returns the file paths in a populated keys_dir
#   INPUTS: { None - uses tmp_path fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Creates files under tmp_path
#   LINKS: M-SSH-KEYS
# END_CONTRACT: test_list_private_keys_returns_file_paths
def test_list_private_keys_returns_file_paths(tmp_path: Path) -> None:
    """Returns the file paths present in keys_dir"""
    (tmp_path / "id_rsa").write_text("PRIVATE")
    (tmp_path / "id_ed25519").write_text("PRIVATE")

    result = list_private_keys(tmp_path)

    names = sorted(p.name for p in result)
    assert names == ["id_ed25519", "id_rsa"]
    for p in result:
        assert isinstance(p, PurePath)


# START_CONTRACT: test_list_private_keys_skips_subdirectories
#   PURPOSE: Verify list_private_keys filters out subdirectories (only is_file() entries)
#   INPUTS: { None - uses tmp_path fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: Creates a file and a subdir under tmp_path
#   LINKS: M-SSH-KEYS
# END_CONTRACT: test_list_private_keys_skips_subdirectories
def test_list_private_keys_skips_subdirectories(tmp_path: Path) -> None:
    """Subdirectories are filtered out (is_file() is False)"""
    (tmp_path / "id_rsa").write_text("PRIVATE")
    (tmp_path / "subdir").mkdir()

    result = list_private_keys(tmp_path)

    assert [p.name for p in result] == ["id_rsa"]


# START_CONTRACT: test_list_private_keys_empty_dir_returns_empty
#   PURPOSE: Verify list_private_keys returns an empty sequence for an empty keys_dir
#   INPUTS: { None - uses tmp_path fixture }
#   OUTPUTS: { None - assertion-based test }
#   SIDE_EFFECTS: None
#   LINKS: M-SSH-KEYS
# END_CONTRACT: test_list_private_keys_empty_dir_returns_empty
def test_list_private_keys_empty_dir_returns_empty(tmp_path: Path) -> None:
    """An empty keys_dir yields an empty list"""
    result = list_private_keys(tmp_path)
    assert list(result) == []
