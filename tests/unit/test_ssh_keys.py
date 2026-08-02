# region MODULE_CONTRACT
# PURPOSE: Unit tests for list_private_keys pure-function SSH key discovery.
# SCOPE: list_private_keys scans a keys directory and returns the file paths it contains.
# KEYWORDS: list_private_keys, SSH key discovery, pure function
# endregion MODULE_CONTRACT

from pathlib import Path, PurePath

from yascheduler.infra.ssh.keys import list_private_keys


def test_list_private_keys_returns_file_paths(tmp_path: Path) -> None:
    """Returns the file paths present in keys_dir"""
    (tmp_path / "id_rsa").write_text("PRIVATE")
    (tmp_path / "id_ed25519").write_text("PRIVATE")

    result = list_private_keys(tmp_path)

    names = sorted(p.name for p in result)
    assert names == ["id_ed25519", "id_rsa"]
    for p in result:
        assert isinstance(p, PurePath)


def test_list_private_keys_skips_subdirectories(tmp_path: Path) -> None:
    """Subdirectories are filtered out (is_file() is False)"""
    (tmp_path / "id_rsa").write_text("PRIVATE")
    (tmp_path / "subdir").mkdir()

    result = list_private_keys(tmp_path)

    assert [p.name for p in result] == ["id_rsa"]


def test_list_private_keys_skips_public_keys(tmp_path: Path) -> None:
    """Public keys (.pub) are filtered out — keys_dir must hold private keys only."""
    (tmp_path / "id_rsa").write_text("PRIVATE")
    (tmp_path / "id_rsa.pub").write_text("PUBLIC")
    (tmp_path / "id_ed25519").write_text("PRIVATE")
    (tmp_path / "id_ed25519.pub").write_text("PUBLIC")

    result = list_private_keys(tmp_path)

    names = sorted(p.name for p in result)
    assert names == ["id_ed25519", "id_rsa"]


def test_list_private_keys_empty_dir_returns_empty(tmp_path: Path) -> None:
    """An empty keys_dir yields an empty list"""
    result = list_private_keys(tmp_path)
    assert list(result) == []
