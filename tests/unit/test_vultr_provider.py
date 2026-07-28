"""Tests for Vultr provider module."""
# region MODULE_CONTRACT
# PURPOSE: Unit tests for Vultr provider: exception hierarchy, fingerprint,
#          cloud-init user-data, SSH key registration, SSH readiness polling,
#          create/delete orchestration, and log-marker emission.
# SCOPE: vultr.py module-level behavior; VultrClient and SSH helpers via mocks.
# KEYWORDS: vultr, provider, unit, exceptions, fingerprint, cloud-init, ssh
# endregion MODULE_CONTRACT

from __future__ import annotations

import base64
import hashlib
import json
import logging
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.shared.log import _NATIVE_KEYS


class LogCaptureHandler(logging.Handler):
    """Capture log records for assertion."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)


@pytest.fixture
def log_records() -> Generator[list[logging.LogRecord], None, None]:
    """Capture log records from the vultr provider logger."""
    logger = logging.getLogger("yascheduler.infra.cloud.providers.vultr")
    records: list[logging.LogRecord] = []
    handler = LogCaptureHandler(records)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def extra_fields(record: logging.LogRecord) -> dict[str, object]:
    """Reconstruct structured fields from a log record."""
    return {k: getattr(record, k) for k in record.__dict__ if k not in _NATIVE_KEYS}


# =============================================================================
# Exception hierarchy
# =============================================================================


class TestExceptionHierarchy:
    """Vultr exception hierarchy: APIError subclass relationship."""

    def test_api_error_is_exception(self) -> None:
        """APIError subclasses Exception."""
        from yascheduler.infra.cloud.providers.vultr import APIError

        assert issubclass(APIError, Exception)

    def test_api_error_carries_message(self) -> None:
        """str(APIError(msg)) == msg."""
        from yascheduler.infra.cloud.providers.vultr import APIError

        assert str(APIError("boom")) == "boom"

    def test_api_error_default_status_is_none(self) -> None:
        """APIError without explicit status has status=None (transport-level)."""
        from yascheduler.infra.cloud.providers.vultr import APIError

        err = APIError("boom")
        assert err.status is None

    def test_api_error_5xx_is_transient(self) -> None:
        """5xx APIError is transient — worth retrying."""
        from yascheduler.infra.cloud.providers.vultr import APIError

        assert APIError("HTTP 500", status=500).transient is True
        assert APIError("HTTP 503", status=503).transient is True

    def test_api_error_4xx_is_not_transient(self) -> None:
        """4xx APIError is permanent — not retried."""
        from yascheduler.infra.cloud.providers.vultr import APIError

        assert APIError("HTTP 404", status=404).transient is False
        assert APIError("HTTP 400", status=400).transient is False

    def test_api_error_transport_failure_is_transient(self) -> None:
        """APIError with status=None (transport failure) is transient."""
        from yascheduler.infra.cloud.providers.vultr import APIError

        assert APIError("HTTP request failed: timeout").transient is True


# =============================================================================
# ssh_key_fingerprint_md5
# =============================================================================


class TestSshKeyFingerprint:
    """ssh_key_fingerprint_md5: empty input + valid pubkey MD5 fingerprint."""

    def test_empty_string_returns_empty(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import ssh_key_fingerprint_md5

        assert ssh_key_fingerprint_md5("") == ""

    def test_single_token_returns_empty(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import ssh_key_fingerprint_md5

        assert ssh_key_fingerprint_md5("ssh-rsa") == ""

    def test_valid_pubkey_returns_colon_hex(self) -> None:
        """A valid pubkey string yields colon-separated MD5 hex of the base64-decoded key material."""
        from yascheduler.infra.cloud.providers.vultr import ssh_key_fingerprint_md5

        key_material = b"\x00\x01\x02\x03\x04"
        b64 = base64.b64encode(key_material).decode()
        pubkey = f"ssh-rsa {b64} comment"
        result = ssh_key_fingerprint_md5(pubkey)
        expected_hex = hashlib.md5(key_material).hexdigest()
        expected = ":".join(
            expected_hex[i : i + 2] for i in range(0, len(expected_hex), 2)
        )
        assert result == expected

    def test_case_insensitive_match(self) -> None:
        """Fingerprint is lowercase hex; callers compare case-insensitively."""
        from yascheduler.infra.cloud.providers.vultr import ssh_key_fingerprint_md5

        result = ssh_key_fingerprint_md5("ssh-rsa AAAAB3NzaC1yc2E= test")
        assert all(c in "0123456789abcdef:" for c in result)


# =============================================================================
# build_baremetal_user_data
# =============================================================================


class TestBuildBaremetalUserData:
    """build_baremetal_user_data: cloud-init payload shape per need_raid + cloud_config."""

    PUB = "ssh-rsa AAAAB3NzaC1yc2E= test"

    def test_returns_cloud_config_prefix(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("root", self.PUB, None, need_raid=True)
        assert out.startswith("#cloud-config\n")

    def test_strips_to_valid_json(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("root", self.PUB, None, need_raid=True)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert "runcmd" in data
        assert "packages" in data

    def test_need_raid_true_includes_mdadm_commands(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("root", self.PUB, None, need_raid=True)
        assert "mdadm" in out
        assert "mdadm --create" in out
        assert "/dev/shm" in out

    def test_need_raid_false_skips_raid(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("root", self.PUB, None, need_raid=False)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert "mdadm" not in data["packages"]
        runcmd_str = " ".join(data["runcmd"])
        assert "mdadm --create" not in runcmd_str
        assert "/dev/shm" not in runcmd_str

    def test_none_cloud_config_no_package_upgrade(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("root", self.PUB, None, need_raid=True)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert data["package_upgrade"] is False

    def test_cloud_config_packages_merged(self) -> None:
        from yascheduler.infra.cloud.cloud_init import CloudInitConfig
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        cc = CloudInitConfig(packages=["foo", "bar"], package_upgrade=True)
        out = build_baremetal_user_data("root", self.PUB, cc, need_raid=True)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert "foo" in data["packages"]
        assert "bar" in data["packages"]
        assert data["package_upgrade"] is True

    def test_engine_packages_deduped_after_base(self) -> None:
        from yascheduler.infra.cloud.cloud_init import CloudInitConfig
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        # "git" is already in base packages; passing it via cloud_config must not duplicate.
        cc = CloudInitConfig(packages=["git", "custom-pkg"])
        out = build_baremetal_user_data("root", self.PUB, cc, need_raid=True)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert data["packages"].count("git") == 1
        assert "custom-pkg" in data["packages"]

    def test_engine_bootcmd_propagated(self) -> None:
        """cloud_config.bootcmd is rendered (previously vultr ignored it)."""
        from yascheduler.infra.cloud.cloud_init import CloudInitConfig
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        cc = CloudInitConfig(bootcmd=(["echo", "engine-boot"],))
        out = build_baremetal_user_data("root", self.PUB, cc, need_raid=False)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert data["bootcmd"] == [["echo", "engine-boot"]]

    def test_root_username_adds_root_authorized_keys(self) -> None:
        """username='root' → users has root with the key."""
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("root", self.PUB, None, need_raid=False)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert data["users"] == [{"name": "root", "ssh_authorized_keys": [self.PUB]}]

    def test_non_root_username_adds_root_and_user(self) -> None:
        """username!='root' → users has root AND the custom user, both with the key."""
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("myuser", self.PUB, None, need_raid=False)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        assert data["users"] == [
            {"name": "root", "ssh_authorized_keys": [self.PUB]},
            {"name": "myuser", "ssh_authorized_keys": [self.PUB]},
        ]

    def test_non_root_user_has_no_sudo(self) -> None:
        """Custom user must NOT have sudo (operator said no privilege escalation)."""
        from yascheduler.infra.cloud.providers.vultr import build_baremetal_user_data

        out = build_baremetal_user_data("myuser", self.PUB, None, need_raid=False)
        data = json.loads(out.removeprefix("#cloud-config\n"))
        for entry in data["users"]:
            assert "sudo" not in entry


# =============================================================================
# get_ssh_key_id
# =============================================================================


class TestGetSshKeyId:
    """get_ssh_key_id: fingerprint match reuses key, miss uploads new one."""

    @pytest.mark.asyncio
    async def test_fingerprint_match_returns_existing_id_no_post(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import (
            get_ssh_key_id,
            ssh_key_fingerprint_md5,
        )

        key_material = b"\x00\x01\x02"
        b64 = base64.b64encode(key_material).decode()
        pubkey = f"ssh-rsa {b64} test"
        fp = ssh_key_fingerprint_md5(pubkey)

        mock_key = MagicMock()
        mock_key.export_public_key.return_value = pubkey.encode()

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            return_value={"ssh_keys": [{"id": "existing-id", "fingerprint": fp}]},
        )

        result = await get_ssh_key_id(mock_client, mock_key)
        assert result == "existing-id"
        # Only GET happened — no POST
        assert mock_client.request.call_count == 1
        call_args = mock_client.request.call_args
        assert call_args.args[0] == "GET"

    @pytest.mark.asyncio
    async def test_no_match_uploads_and_returns_new_id(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import get_ssh_key_id

        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"ssh_keys": []},  # GET: no existing keys
                {"ssh_key": {"id": "new-id"}},  # POST: uploaded
            ],
        )

        result = await get_ssh_key_id(mock_client, mock_key)
        assert result == "new-id"
        assert mock_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_post_without_id_raises_apierror(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import APIError, get_ssh_key_id

        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"ssh_keys": []},
                {"ssh_key": {}},  # POST: no id in response
            ],
        )

        with pytest.raises(APIError):
            await get_ssh_key_id(mock_client, mock_key)


# =============================================================================
# _wait_ssh_port
# =============================================================================


class TestWaitSshPort:
    """_wait_ssh_port: success on first connect, retry on refusal, timeout raises."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_connect(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import _wait_ssh_port

        writer = MagicMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()
        loop = MagicMock()
        loop.time = MagicMock(return_value=0)

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.open_connection",
                AsyncMock(return_value=(MagicMock(), writer)),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
        ):
            await _wait_ssh_port("inst-1", "1.2.3.4")

        writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_refused_then_succeeds(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import _wait_ssh_port

        writer = MagicMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()
        loop = MagicMock()
        # deadline = 0 + 1200 = 1200; while checks: 0 < 1200 (enter), 0 < 1200 (enter), then exit
        loop.time = MagicMock(return_value=0)

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.open_connection",
                AsyncMock(
                    side_effect=[ConnectionRefusedError, (MagicMock(), writer)],
                ),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
        ):
            await _wait_ssh_port("inst-1", "1.2.3.4")

        # First connect refused, second succeeded → writer.close called once
        writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_raises_apierror(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import (
            POLL_TIMEOUT,
            APIError,
            _wait_ssh_port,
        )

        loop = MagicMock()
        # First call sets deadline = 0 + POLL_TIMEOUT; second call (while check) exceeds it.
        loop.time = MagicMock(side_effect=[0, POLL_TIMEOUT + 1])

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.open_connection",
                AsyncMock(side_effect=ConnectionRefusedError),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
            pytest.raises(APIError),
        ):
            await _wait_ssh_port("inst-1", "1.2.3.4")


# =============================================================================
# _check_ssh_auth
# =============================================================================


class TestCheckSshAuth:
    """_check_ssh_auth: success closes conn, failure exhausts attempts."""

    @pytest.mark.asyncio
    async def test_success_returns_true_and_closes(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import _check_ssh_auth

        conn = MagicMock()
        conn.close = MagicMock()

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncssh.connect",
                AsyncMock(return_value=conn),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            result = await _check_ssh_auth(
                "inst-1",
                "1.2.3.4",
                MagicMock(),
                "root",
                attempts=2,
                interval=0,
            )

        assert result is True
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_returns_false_after_attempts(
        self,
        log_records: list,
    ) -> None:
        from yascheduler.infra.cloud.providers.vultr import _check_ssh_auth

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncssh.connect",
                AsyncMock(side_effect=OSError("refused")),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            result = await _check_ssh_auth(
                "inst-1",
                "1.2.3.4",
                MagicMock(),
                "root",
                attempts=2,
                interval=0,
            )

        assert result is False
        # Each failed attempt emits a SSH_AUTH_RETRY debug marker
        retries = [r for r in log_records if r.getMessage() == "SSH_AUTH_RETRY"]
        assert len(retries) == 2
        fields = extra_fields(retries[0])
        assert fields["instance_id"] == "inst-1"
        assert fields["attempt"] == 1
        assert fields["attempts"] == 2


# =============================================================================
# vultr_create_node
# =============================================================================


class TestVultrCreateNode:
    """vultr_create_node: full orchestration with mocked client and SSH helpers."""

    @pytest.mark.asyncio
    async def test_returns_dto_with_correct_fields(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import vultr_create_node

        cfg = ConfigCloudVultr(
            api_key="test-key",
            jump_host="jump.example.com",
            jump_port=2222,
            jump_username="jumpuser",
        )
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"bare_metal": {"id": "inst-1"}},  # POST /bare-metals
                {  # GET poll — active immediately
                    "bare_metal": {
                        "id": "inst-1",
                        "status": "active",
                        "main_ip": "1.2.3.4",
                    },
                },
            ],
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._wait_ssh_port",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._check_ssh_auth",
                AsyncMock(return_value=True),
            ),
        ):
            result = await vultr_create_node(cfg, mock_key)

        assert result.external_id == "1.2.3.4"
        assert result.hostname == "1.2.3.4"
        assert result.username == "root"
        assert result.jump_host == "jump.example.com"
        assert result.jump_port == 2222
        assert result.jump_username == "jumpuser"

    @pytest.mark.asyncio
    async def test_post_without_instance_id_raises_apierror(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import APIError, vultr_create_node

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"
        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value={})  # POST: no id

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            pytest.raises(APIError),
        ):
            await vultr_create_node(cfg, mock_key)

        # Instance was never created (no id in POST response) → no cleanup.
        delete_calls = [
            c for c in mock_client.request.call_args_list if c.args[0] == "DELETE"
        ]
        assert delete_calls == []

    @pytest.mark.asyncio
    async def test_never_active_raises_apierror(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import (
            POLL_TIMEOUT,
            APIError,
            vultr_create_node,
        )

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"bare_metal": {"id": "inst-1"}},  # POST
                {  # GET: always pending
                    "bare_metal": {
                        "id": "inst-1",
                        "status": "pending",
                        "main_ip": "0.0.0.0",
                    },
                },
                {},  # DELETE cleanup accepted
                APIError("HTTP 404", status=404),  # GET verify: gone
            ],
        )

        loop = MagicMock()
        # create-poll consumes 3 (deadline, while-check, while-check-exit);
        # verify consumes 2 (deadline, while-check) then 404 returns.
        loop.time = MagicMock(side_effect=[0, 0, POLL_TIMEOUT + 1, 0, 1])

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
            pytest.raises(APIError),
        ):
            await vultr_create_node(cfg, mock_key)

        # Instance was created → cleanup MUST have deleted it (BUG-1 regression).
        delete_calls = [
            c for c in mock_client.request.call_args_list if c.args[0] == "DELETE"
        ]
        assert len(delete_calls) == 1
        assert delete_calls[0].args[1] == "/bare-metals/inst-1"

    @pytest.mark.asyncio
    async def test_ssh_auth_failure_raises_apierror(self) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import APIError, vultr_create_node

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"bare_metal": {"id": "inst-1"}},
                {
                    "bare_metal": {
                        "id": "inst-1",
                        "status": "active",
                        "main_ip": "1.2.3.4",
                    },
                },
                {},  # DELETE cleanup accepted
                APIError("HTTP 404", status=404),  # GET verify: gone
            ],
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._wait_ssh_port",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._check_ssh_auth",
                AsyncMock(return_value=False),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=MagicMock(time=MagicMock(side_effect=[0, 0, 1, 1])),
            ),
            pytest.raises(APIError),
        ):
            await vultr_create_node(cfg, mock_key)

        # Instance was created → cleanup MUST have deleted it (BUG-1 regression).
        delete_calls = [
            c for c in mock_client.request.call_args_list if c.args[0] == "DELETE"
        ]
        assert len(delete_calls) == 1
        assert delete_calls[0].args[1] == "/bare-metals/inst-1"

    @pytest.mark.asyncio
    async def test_emits_poll_status_marker(
        self,
        log_records: list,
    ) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import vultr_create_node

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"bare_metal": {"id": "inst-1"}},
                {
                    "bare_metal": {
                        "id": "inst-1",
                        "status": "active",
                        "main_ip": "1.2.3.4",
                    },
                },
            ],
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._wait_ssh_port",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._check_ssh_auth",
                AsyncMock(return_value=True),
            ),
        ):
            await vultr_create_node(cfg, mock_key)

        poll_records = [r for r in log_records if r.getMessage() == "POLL_STATUS"]
        assert len(poll_records) >= 1
        fields = extra_fields(poll_records[0])
        assert fields["instance_id"] == "inst-1"
        assert fields["status"] == "active"
        assert fields["ip"] == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_get_poll_retries_transient_500_then_succeeds(self) -> None:
        """A flapping 5xx on GET status must not abort create_node — the
        instance is alive and the poll should recover on the next tick."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import APIError, vultr_create_node

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"
        transient_err = APIError("HTTP 500: Internal server error", status=500)
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"bare_metal": {"id": "inst-1"}},  # POST
                transient_err,  # GET 1: flap
                {  # GET 2: recovered
                    "bare_metal": {
                        "id": "inst-1",
                        "status": "active",
                        "main_ip": "1.2.3.4",
                    },
                },
            ],
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._wait_ssh_port",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._check_ssh_auth",
                AsyncMock(return_value=True),
            ),
        ):
            result = await vultr_create_node(cfg, mock_key)

        assert result.external_id == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_user_data_carries_users_section_and_auth_uses_cfg_username(
        self,
    ) -> None:
        """create_node forwards pub_key to user_data and polls auth as cfg.username.

        Regression for non-root provisioning: Vultr sshkey_id only injects into
        root's authorized_keys, so a non-root user is created via cloud-init
        and the auth poll MUST use cfg.username.
        """
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import vultr_create_node

        cfg = ConfigCloudVultr(api_key="test-key", username="myuser")
        pub = "ssh-rsa AAAAB3NzaC1yc2E= test"
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = pub.encode()

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"bare_metal": {"id": "inst-1"}},
                {
                    "bare_metal": {
                        "id": "inst-1",
                        "status": "active",
                        "main_ip": "1.2.3.4",
                    },
                },
            ],
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._wait_ssh_port",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr._check_ssh_auth",
                AsyncMock(return_value=True),
            ) as auth_mock,
        ):
            result = await vultr_create_node(cfg, mock_key)

        # create-node body MUST contain user_data with a `users` section carrying pub.
        post_call = mock_client.request.call_args_list[0]
        body = post_call.args[2]
        import base64 as b64m

        decoded = b64m.b64decode(body["user_data"]).decode()
        data = json.loads(decoded.removeprefix("#cloud-config\n"))
        assert data["users"] == [
            {"name": "root", "ssh_authorized_keys": [pub]},
            {"name": "myuser", "ssh_authorized_keys": [pub]},
        ]

        # Auth poll MUST use cfg.username, not "root".
        auth_kwargs = auth_mock.call_args
        assert auth_kwargs.kwargs.get("username") == "myuser" or (
            "username" not in auth_kwargs.kwargs
            and auth_mock.call_args.args[-1] == "myuser"
        )
        assert result.username == "myuser"

    @pytest.mark.asyncio
    async def test_get_poll_permanent_4xx_does_not_retry(self) -> None:
        """A 4xx on GET must surface immediately — it is permanent, not a flap."""
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import APIError, vultr_create_node

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_key = MagicMock()
        mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3NzaC1yc2E= test"
        permanent_err = APIError("HTTP 404: Not found", status=404)
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {"bare_metal": {"id": "inst-1"}},  # POST
                permanent_err,  # GET create-poll: 404 — permanent, raise
                {},  # DELETE cleanup accepted
                APIError("HTTP 404", status=404),  # GET verify: gone
            ],
        )

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_ssh_key_id",
                AsyncMock(return_value="key-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_rnd_name",
                return_value="test-node",
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.sleep",
                AsyncMock(),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=MagicMock(time=MagicMock(side_effect=[0, 1, 0, 1])),
            ),
            pytest.raises(APIError) as exc_info,
        ):
            await vultr_create_node(cfg, mock_key)

        # The 404 propagated, not swallowed.
        assert exc_info.value.status == 404
        # Instance was created → cleanup DELETE fired once.
        delete_calls = [
            c for c in mock_client.request.call_args_list if c.args[0] == "DELETE"
        ]
        assert len(delete_calls) == 1


# =============================================================================
# _delete_and_verify
# =============================================================================


class TestDeleteAndVerify:
    """_delete_and_verify: DELETE + verify-poll semantics."""

    @pytest.mark.asyncio
    async def test_delete_accepted_then_verify_404(self) -> None:
        """2xx DELETE → verify GET polls until 404 (confirmed gone)."""
        from yascheduler.infra.cloud.providers.vultr import (
            APIError,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {},  # DELETE accepted (2xx)
                {"bare_metal": {"id": "inst-1"}},  # GET 1: still present
                APIError("HTTP 404", status=404),  # GET 2: gone
            ],
        )

        loop = MagicMock()
        loop.time = MagicMock(side_effect=[0, 0, 1, 1])

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
            patch("yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()),
        ):
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is True

        # 1 DELETE + 2 GETs (present then gone).
        methods = [c.args[0] for c in mock_client.request.call_args_list]
        assert methods == ["DELETE", "GET", "GET"]

    @pytest.mark.asyncio
    async def test_delete_404_means_already_gone_no_verify(self) -> None:
        """DELETE returns 404 → already gone → no verify-poll needed."""
        from yascheduler.infra.cloud.providers.vultr import (
            APIError,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=APIError("HTTP 404", status=404),
        )

        with patch(
            "yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()
        ):
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is True

        # Only the DELETE — no verify GET.
        assert mock_client.request.call_count == 1
        assert mock_client.request.call_args.args[0] == "DELETE"

    @pytest.mark.asyncio
    async def test_delete_500_retried_then_accepted(self) -> None:
        """DELETE 5xx is transient → retry DELETE; then 2xx accepted → verify."""
        from yascheduler.infra.cloud.providers.vultr import (
            APIError,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                APIError("HTTP 500", status=500),  # DELETE 1: transient
                {},  # DELETE 2: accepted
                APIError("HTTP 404", status=404),  # GET: gone
            ],
        )

        loop = MagicMock()
        loop.time = MagicMock(side_effect=[0, 0, 1, 1])

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
            patch("yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()),
        ):
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is True

        methods = [c.args[0] for c in mock_client.request.call_args_list]
        assert methods == ["DELETE", "DELETE", "GET"]

    @pytest.mark.asyncio
    async def test_delete_500_exhausts_retries_no_verify(self) -> None:
        """Persistent 5xx on DELETE exhausts retries → no verify (never accepted)."""
        from yascheduler.infra.cloud.providers.vultr import (
            CLEANUP_DELETE_ATTEMPTS,
            APIError,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=APIError("HTTP 500", status=500),
        )

        with patch(
            "yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()
        ):
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is False

        # All calls are DELETE retries — no verify GET ever issued.
        assert mock_client.request.call_count == CLEANUP_DELETE_ATTEMPTS
        methods = [c.args[0] for c in mock_client.request.call_args_list]
        assert all(m == "DELETE" for m in methods)

    @pytest.mark.asyncio
    async def test_delete_permanent_4xx_no_retry_no_verify(self) -> None:
        """DELETE 4xx (non-404) is permanent → no retry, no verify."""
        from yascheduler.infra.cloud.providers.vultr import (
            APIError,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=APIError("HTTP 403", status=403),
        )

        with patch(
            "yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()
        ):
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is False

        assert mock_client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_verify_timeout_logs_error_still_present(
        self,
        log_records: list,
    ) -> None:
        """DELETE accepted but instance never goes 404 → ERROR log for manual intervention."""
        from yascheduler.infra.cloud.providers.vultr import (
            CLEANUP_VERIFY_TIMEOUT,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {},  # DELETE accepted
                *[{"bare_metal": {"id": "inst-1"}}] * 100,  # GET: always present
            ],
        )

        # Simulate verify-timeout: time() jumps past deadline after first GET.
        call_count = [0]

        def fake_time() -> float:
            call_count[0] += 1
            if call_count[0] <= 2:
                return 0  # deadline = 0 + CLEANUP_VERIFY_TIMEOUT; while: 0 < deadline
            return CLEANUP_VERIFY_TIMEOUT + 1  # expire on second while-check

        loop = MagicMock()
        loop.time = MagicMock(side_effect=fake_time)

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
            patch("yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()),
        ):
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is False

        # Must NOT claim success — escalate to ERROR.
        error_records = [
            r
            for r in log_records
            if r.levelno >= logging.ERROR and "STILL PRESENT" in r.getMessage()
        ]
        assert len(error_records) == 1

    @pytest.mark.asyncio
    async def test_verify_get_transient_error_keeps_polling(self) -> None:
        """Transient GET error during verify → keep polling (uncertain), not abort."""
        from yascheduler.infra.cloud.providers.vultr import (
            APIError,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {},  # DELETE accepted
                APIError("HTTP 500", status=500),  # GET 1: transient
                APIError("HTTP 404", status=404),  # GET 2: gone
            ],
        )

        loop = MagicMock()
        loop.time = MagicMock(side_effect=[0, 0, 1, 1])

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
            patch("yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()),
        ):
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is True

        methods = [c.args[0] for c in mock_client.request.call_args_list]
        assert methods == ["DELETE", "GET", "GET"]

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        """Cleanup must never raise even when everything fails."""
        from yascheduler.infra.cloud.providers.vultr import (
            APIError,
            _delete_and_verify,
        )

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=APIError("HTTP 500", status=500),
        )

        with patch(
            "yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()
        ):
            # Must not raise.
            result = await _delete_and_verify(mock_client, "inst-1")

        assert result is False


# =============================================================================
# find_baremetal
# =============================================================================


class TestFindBaremetal:
    """find_baremetal: IP lookup against the bare-metals list."""

    @pytest.mark.asyncio
    async def test_match_returns_id(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import find_baremetal

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            return_value={
                "bare_metals": [
                    {"id": "bm-1", "main_ip": "1.2.3.4"},
                    {"id": "bm-2", "main_ip": "5.6.7.8"},
                ],
            },
        )

        result = await find_baremetal(mock_client, "1.2.3.4")
        assert result == "bm-1"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import find_baremetal

        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            return_value={
                "bare_metals": [{"id": "bm-1", "main_ip": "1.2.3.4"}],
            },
        )

        result = await find_baremetal(mock_client, "9.9.9.9")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_list_returns_none(self) -> None:
        from yascheduler.infra.cloud.providers.vultr import find_baremetal

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value={"bare_metals": []})

        result = await find_baremetal(mock_client, "1.2.3.4")
        assert result is None


# =============================================================================
# vultr_delete_node
# =============================================================================


class TestVultrDeleteNode:
    """vultr_delete_node: found → DELETE + verify + log; unknown → skip + log."""

    @pytest.mark.asyncio
    async def test_found_calls_delete_and_logs(
        self,
        log_records: list,
    ) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import (
            APIError,
            vultr_delete_node,
        )

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=[
                {},  # DELETE accepted
                APIError("HTTP 404", status=404),  # GET verify: gone
            ],
        )

        loop = MagicMock()
        loop.time = MagicMock(side_effect=[0, 0, 1, 1])

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.find_baremetal",
                AsyncMock(return_value="inst-1"),
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.asyncio.get_running_loop",
                return_value=loop,
            ),
            patch("yascheduler.infra.cloud.providers.vultr.asyncio.sleep", AsyncMock()),
        ):
            await vultr_delete_node(cfg, "1.2.3.4")

        # DELETE was called on the client
        delete_calls = [
            c for c in mock_client.request.call_args_list if c.args[0] == "DELETE"
        ]
        assert len(delete_calls) == 1
        assert delete_calls[0].args[1] == "/bare-metals/inst-1"
        # DELETED info marker emitted only after verify confirms gone
        deleted_records = [r for r in log_records if "DELETED" in r.getMessage()]
        assert len(deleted_records) == 1

    @pytest.mark.asyncio
    async def test_unknown_skips_delete_and_logs(
        self,
        log_records: list,
    ) -> None:
        from yascheduler.infra.cloud.cloud_configs import ConfigCloudVultr
        from yascheduler.infra.cloud.providers.vultr import vultr_delete_node

        cfg = ConfigCloudVultr(api_key="test-key")
        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value={})

        with (
            patch(
                "yascheduler.infra.cloud.providers.vultr.get_client",
                return_value=mock_client,
            ),
            patch(
                "yascheduler.infra.cloud.providers.vultr.find_baremetal",
                AsyncMock(return_value=None),
            ),
        ):
            await vultr_delete_node(cfg, "9.9.9.9")

        # No DELETE call
        delete_calls = [
            c for c in mock_client.request.call_args_list if c.args[0] == "DELETE"
        ]
        assert len(delete_calls) == 0
        # NOT DELETED AS UNKNOWN marker emitted
        unknown_records = [
            r for r in log_records if "NOT DELETED AS UNKNOWN" in r.getMessage()
        ]
        assert len(unknown_records) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
