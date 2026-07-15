# FILE: tests/unit/test_hetzner_ssh_key.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for hetzner.get_ssh_key_id duplicate-key recovery (uniqueness_error code path).
#   SCOPE: get_ssh_key_id with mocked hcloud client and APIException; no network.
#   DEPENDS: M-CLOUD-PROVIDER-HETZNER
#   LINKS: M-CLOUD-PROVIDER-HETZNER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestGetSshKeyIdUniqueness - create() duplicate-key recovery branches
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - fix-hetzner-ssh-key-uniqueness: cover the recovery branch in get_ssh_key_id triggered by Hetzner's `uniqueness_error` API code (wording "SSH key not unique"), which the legacy "already" substring match failed to detect.
# END_CHANGE_SUMMARY

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

hcloud = pytest.importorskip("hcloud")
from hcloud import APIException

from yascheduler.infra.cloud.providers.hetzner import get_ssh_key_id


@pytest.fixture(autouse=True)
def _clear_ssh_key_cache() -> None:
    """get_ssh_key_id is @cache-decorated; clear between tests so mocks re-run."""
    get_ssh_key_id.cache_clear()


def _make_key(key_name: str = "yakey-abc") -> MagicMock:
    """Mock ASSHKey with the surface get_ssh_key_id touches."""
    key = MagicMock()
    key.export_public_key.return_value = b"ssh-rsa AAAA test"
    # get_fingerprint("md5") -> "MD5:aa:bb:cc"; .split(":", 1)[1] -> "aa:bb:cc"
    key.get_fingerprint.return_value = "MD5:aa:bb:cc"
    return key


class TestGetSshKeyIdUniqueness:
    """get_ssh_key_id() — duplicate-key recovery via uniqueness_error code."""

    def test_recovers_via_fingerprint_on_uniqueness_error(self) -> None:
        """create() raising uniqueness_error resolves the existing key by fingerprint."""
        client = MagicMock()
        client.ssh_keys.create.side_effect = APIException(
            code="uniqueness_error",
            message="SSH key not unique",
            details={},
        )
        existing = MagicMock()
        existing.id = 4242
        client.ssh_keys.get_by_fingerprint.return_value = existing

        key = _make_key()
        with patch(
            "yascheduler.infra.cloud.providers.hetzner.get_key_name",
            return_value="yakey-abc",
        ):
            result = get_ssh_key_id(client, key)

        assert result == 4242
        client.ssh_keys.create.assert_called_once()
        # fingerprint passed without the "MD5" prefix
        client.ssh_keys.get_by_fingerprint.assert_called_once_with("aa:bb:cc")
        client.ssh_keys.get_by_name.assert_not_called()

    def test_recovers_via_name_when_fingerprint_missing(self) -> None:
        """Falls back to get_by_name when fingerprint lookup returns None."""
        client = MagicMock()
        client.ssh_keys.create.side_effect = APIException(
            code="uniqueness_error",
            message="SSH key not unique",
            details={},
        )
        client.ssh_keys.get_by_fingerprint.return_value = None
        by_name = MagicMock()
        by_name.id = 99
        client.ssh_keys.get_by_name.return_value = by_name

        key = _make_key()
        with patch(
            "yascheduler.infra.cloud.providers.hetzner.get_key_name",
            return_value="yakey-abc",
        ):
            result = get_ssh_key_id(client, key)

        assert result == 99

    def test_recovers_via_scan_when_lookups_miss(self) -> None:
        """Falls back to scanning all yakey-* keys when fingerprint and name miss."""
        client = MagicMock()
        client.ssh_keys.create.side_effect = APIException(
            code="uniqueness_error",
            message="SSH key not unique",
            details={},
        )
        client.ssh_keys.get_by_fingerprint.return_value = None
        client.ssh_keys.get_by_name.return_value = None

        match = MagicMock()
        match.name = "yakey-xyz"
        match.id = 7
        other = MagicMock()
        other.name = "deploy-key"
        other.id = 8
        client.ssh_keys.get_all.return_value = [other, match]

        key = _make_key()
        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_key_name",
                return_value="yakey-abc",
            ),
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_rnd_name",
                return_value="yakey-xyz",
            ),
        ):
            result = get_ssh_key_id(client, key)

        assert result == 7

    def test_legacy_already_wording_still_recovers(self) -> None:
        """Older API wording containing 'already' still triggers recovery."""
        client = MagicMock()
        client.ssh_keys.create.side_effect = APIException(
            code="conflict",
            message="name already exists",
            details={},
        )
        existing = MagicMock()
        existing.id = 13
        client.ssh_keys.get_by_fingerprint.return_value = existing

        key = _make_key()
        with patch(
            "yascheduler.infra.cloud.providers.hetzner.get_key_name",
            return_value="yakey-abc",
        ):
            result = get_ssh_key_id(client, key)

        assert result == 13

    def test_unrelated_api_error_reraised(self) -> None:
        """A non-uniqueness APIException is re-raised, not swallowed."""
        client = MagicMock()
        client.ssh_keys.create.side_effect = APIException(
            code="invalid_input",
            message="bad token",
            details={},
        )

        key = _make_key()
        with (
            patch(
                "yascheduler.infra.cloud.providers.hetzner.get_key_name",
                return_value="yakey-abc",
            ),
            pytest.raises(APIException),
        ):
            get_ssh_key_id(client, key)

        client.ssh_keys.get_by_fingerprint.assert_not_called()
