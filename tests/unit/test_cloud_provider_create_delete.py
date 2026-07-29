"""Tests for cloud provider create/delete DTO integration."""
# region MODULE_CONTRACT
# PURPOSE: Verify each provider's create_node returns CloudCreateNodeDTO and delete_node accepts external_id.
# SCOPE: az, hetzner, upcloud, vastai provider functions.
# KEYWORDS: cloud, provider, dto, create, delete, acceptance
# endregion MODULE_CONTRACT

from __future__ import annotations

import importlib.util
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.infra.cloud.dto import CloudCreateNodeDTO

# Provider submodules pull in optional cloud SDKs at import time; skip their
# tests cleanly when the SDK is absent. vastai only needs aiohttp (core dep),
# so it always runs. Mirrors the pytest.importorskip pattern in
# test_hetzner_ssh_key.py but scoped per provider so vastai stays runnable.
requires_hetzner = pytest.mark.skipif(
    importlib.util.find_spec("hcloud") is None, reason="hcloud not installed"
)
requires_az = pytest.mark.skipif(
    importlib.util.find_spec("azure.identity") is None,
    reason="azure SDK not installed",
)
requires_upcloud = pytest.mark.skipif(
    importlib.util.find_spec("upcloud_api") is None, reason="upcloud_api not installed"
)


class _AsyncIter:
    """Helper: wrap an iterable into an async iterable."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration from None


# =============================================================================
# Hetzner
# =============================================================================


@requires_hetzner
@pytest.mark.asyncio
async def test_hetzner_create_node_returns_dto() -> None:
    """hetzner_create_node returns CloudCreateNodeDTO with server ID as external_id and IP as hostname."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

    cfg = ConfigCloudHetzner(username="testuser", token="test-token")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    mock_server = MagicMock()
    mock_server.id = 42
    mock_server.public_net.ipv4.ip = "1.2.3.4"

    mock_client = MagicMock()
    mock_client.ssh_keys.create.return_value = MagicMock(id=123)
    mock_client.servers.create.return_value = MagicMock(server=mock_server)

    with patch(
        "yascheduler.infra.cloud.providers.hetzner.HClient",
        return_value=mock_client,
    ):
        result = await hetzner_create_node(cfg, mock_key)

    assert isinstance(result, CloudCreateNodeDTO)
    assert result.external_id == "42"
    assert result.hostname == "1.2.3.4"


@requires_hetzner
@pytest.mark.asyncio
async def test_hetzner_create_node_dto_carries_config_derived_params() -> None:
    """hetzner_create_node DTO carries config-derived connection parameters."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

    cfg = ConfigCloudHetzner(
        username="testuser",
        token="test-token",
        jump_host="jump.example.com",
        jump_port=2222,
        jump_username="jumper",
    )
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    mock_server = MagicMock()
    mock_server.public_net.ipv4.ip = "5.6.7.8"

    mock_client = MagicMock()
    mock_client.ssh_keys.create.return_value = MagicMock(id=123)
    mock_client.servers.create.return_value = MagicMock(server=mock_server)

    with patch(
        "yascheduler.infra.cloud.providers.hetzner.HClient",
        return_value=mock_client,
    ):
        result = await hetzner_create_node(cfg, mock_key)

    assert result.username == "testuser"
    assert result.port == 22  # default, not in ConfigCloudHetzner
    assert result.jump_host == "jump.example.com"
    assert result.jump_port == 2222
    assert result.jump_username == "jumper"


@requires_hetzner
@pytest.mark.asyncio
async def test_hetzner_delete_node_accepts_external_id() -> None:
    """hetzner_delete_node deletes by numeric server ID via DomainServer, not by iteration."""
    from hcloud import APIException

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_delete_node

    cfg = ConfigCloudHetzner(token="test-del-accept")
    mock_client = MagicMock()
    # DELETE succeeds; verify loop polls get_by_id until not_found.
    mock_client.servers.delete.return_value = MagicMock()
    mock_client.servers.get_by_id.side_effect = APIException(
        code="not_found",
        message="server not found",
        details={},
    )

    with (
        patch(
            "yascheduler.infra.cloud.providers.hetzner.HClient",
            return_value=mock_client,
        ),
        patch(
            "yascheduler.infra.cloud.providers.hetzner.time.sleep",
            return_value=None,
        ),
    ):
        await hetzner_delete_node(cfg, external_id="42")

    # Delete called directly with a domain Server carrying id=42 (no pre-GET).
    mock_client.servers.delete.assert_called_once()
    deleted_server = mock_client.servers.delete.call_args.args[0]
    assert deleted_server.id == 42
    mock_client.servers.get_all.assert_not_called()


@requires_hetzner
@pytest.mark.asyncio
async def test_hetzner_delete_node_api_not_found() -> None:
    """hetzner_delete_node handles APIException not_found from DELETE gracefully."""
    from hcloud import APIException

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_delete_node

    cfg = ConfigCloudHetzner(token="test-del-api404")
    mock_client = MagicMock()
    # DELETE itself raises not_found (server already gone) — idempotent no-op.
    mock_client.servers.delete.side_effect = APIException(
        code="not_found",
        message="server not found",
        details={},
    )

    with patch(
        "yascheduler.infra.cloud.providers.hetzner.HClient",
        return_value=mock_client,
    ):
        # Should not raise — APIException not_found is caught
        await hetzner_delete_node(cfg, external_id="152213839")

    mock_client.servers.delete.assert_called_once()
    deleted_server = mock_client.servers.delete.call_args.args[0]
    assert deleted_server.id == 152213839
    # No verify polling when DELETE itself reports not_found.
    mock_client.servers.get_by_id.assert_not_called()


@requires_hetzner
def test_hetzner_find_srv_removed() -> None:
    """find_srv no longer exists in hetzner provider module."""
    from yascheduler.infra.cloud.providers import hetzner as hetzner_mod

    assert not hasattr(hetzner_mod, "find_srv")


@requires_hetzner
@pytest.mark.asyncio
async def test_hetzner_create_node_user_data_has_root_users() -> None:
    """hetzner_create_node injects a cloud-init `users` section with root + the SSH key."""
    import json

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

    cfg = ConfigCloudHetzner(token="test-users")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    captured = {}

    mock_server = MagicMock()
    mock_server.id = 42
    mock_server.public_net.ipv4.ip = "1.2.3.4"

    mock_client = MagicMock()
    mock_client.ssh_keys.create.return_value = MagicMock(id=123)

    def _capture(**kwargs):
        captured.update(kwargs)
        return MagicMock(server=mock_server)

    mock_client.servers.create.side_effect = _capture

    with patch(
        "yascheduler.infra.cloud.providers.hetzner.HClient",
        return_value=mock_client,
    ):
        await hetzner_create_node(cfg, mock_key)

    user_data = captured["user_data"]
    assert user_data.startswith("#cloud-config\n")
    payload = json.loads(user_data[len("#cloud-config\n") :])
    assert payload["users"] == [
        {"name": "root", "ssh_authorized_keys": ["ssh-rsa AAAAB3..."]}
    ]


@requires_hetzner
@pytest.mark.asyncio
async def test_hetzner_create_node_non_root_user_in_user_data() -> None:
    """Non-root cfg.username is created via cloud-init users (no sudo)."""
    import json

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

    cfg = ConfigCloudHetzner(username="compute", token="test-users-nr")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    captured = {}

    mock_server = MagicMock()
    mock_server.id = 42
    mock_server.public_net.ipv4.ip = "1.2.3.4"

    mock_client = MagicMock()
    mock_client.ssh_keys.create.return_value = MagicMock(id=123)

    def _capture(**kwargs):
        captured.update(kwargs)
        return MagicMock(server=mock_server)

    mock_client.servers.create.side_effect = _capture

    with patch(
        "yascheduler.infra.cloud.providers.hetzner.HClient",
        return_value=mock_client,
    ):
        await hetzner_create_node(cfg, mock_key)

    payload = json.loads(captured["user_data"][len("#cloud-config\n") :])
    assert payload["users"] == [
        {"name": "root", "ssh_authorized_keys": ["ssh-rsa AAAAB3..."]},
        {"name": "compute", "ssh_authorized_keys": ["ssh-rsa AAAAB3..."]},
    ]
    for entry in payload["users"]:
        assert "sudo" not in entry


# =============================================================================
# Azure
# =============================================================================


@requires_az
@pytest.mark.asyncio
async def test_az_create_node_returns_dto() -> None:
    """az_create_node returns CloudCreateNodeDTO with IP-based identity."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudAzure
    from yascheduler.infra.cloud.providers.az import az_create_node

    cfg = ConfigCloudAzure(
        username="azuser",
        tenant_id="test-tid",
        client_id="test-cid",
        client_secret="test-secret",
        subscription_id="test-sub",
    )
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    mock_cred = MagicMock()
    mock_cred.__aenter__ = AsyncMock(return_value=mock_cred)
    mock_cred.__aexit__ = AsyncMock()

    mock_nmc = MagicMock()
    mock_nmc.__aenter__ = AsyncMock(return_value=mock_nmc)
    mock_nmc.__aexit__ = AsyncMock()

    mock_cmc = MagicMock()
    mock_cmc.__aenter__ = AsyncMock(return_value=mock_cmc)
    mock_cmc.__aexit__ = AsyncMock()

    with (
        patch(
            "yascheduler.infra.cloud.providers.az.ClientSecretCredential",
            return_value=mock_cred,
        ),
        patch(
            "yascheduler.infra.cloud.providers.az.NetworkManagementClient",
            return_value=mock_nmc,
        ),
        patch(
            "yascheduler.infra.cloud.providers.az.ComputeManagementClient",
            return_value=mock_cmc,
        ),
        patch(
            "yascheduler.infra.cloud.providers.az.create_node",
            new=AsyncMock(
                return_value=CloudCreateNodeDTO(
                    external_id="10.0.0.1",
                    hostname="10.0.0.1",
                    username=cfg.username,
                ),
            ),
        ),
    ):
        result = await az_create_node(cfg, mock_key)

    assert isinstance(result, CloudCreateNodeDTO)
    assert result.external_id == "10.0.0.1"
    assert result.hostname == "10.0.0.1"
    assert result.username == "azuser"


@requires_az
@pytest.mark.asyncio
async def test_az_delete_node_accepts_external_id() -> None:
    """az_delete_node accepts external_id parameter to locate the resource."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudAzure
    from yascheduler.infra.cloud.providers.az import az_delete_node

    cfg = ConfigCloudAzure(
        tenant_id="test-tid",
        client_id="test-cid",
        client_secret="test-secret",
        subscription_id="test-sub",
    )

    mock_cred = MagicMock()
    mock_cred.__aenter__ = AsyncMock(return_value=mock_cred)
    mock_cred.__aexit__ = AsyncMock()

    mock_cmc = MagicMock()
    mock_cmc.virtual_machines.list = MagicMock(return_value=_AsyncIter([]))

    mock_nmc = MagicMock()
    mock_nmc.network_interfaces.list = MagicMock(return_value=_AsyncIter([]))

    # __aenter__ must return self for async with to bind correctly
    mock_cmc.__aenter__ = AsyncMock(return_value=mock_cmc)
    mock_nmc.__aenter__ = AsyncMock(return_value=mock_nmc)
    mock_cmc.__aexit__ = AsyncMock()
    mock_nmc.__aexit__ = AsyncMock()

    with (
        patch(
            "yascheduler.infra.cloud.providers.az.ClientSecretCredential",
            return_value=mock_cred,
        ),
        patch(
            "yascheduler.infra.cloud.providers.az.NetworkManagementClient",
            return_value=mock_nmc,
        ),
        patch(
            "yascheduler.infra.cloud.providers.az.ComputeManagementClient",
            return_value=mock_cmc,
        ),
    ):
        # Should not raise — external_id is accepted as keyword
        await az_delete_node(cfg, external_id="10.0.0.1")


# =============================================================================
# UpCloud
# =============================================================================


@requires_upcloud
@pytest.mark.asyncio
async def test_upcloud_create_node_returns_dto() -> None:
    """upcloud_create_node returns CloudCreateNodeDTO with IP-based identity."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudUpcloud
    from yascheduler.infra.cloud.providers.upcloud import upcloud_create_node

    cfg = ConfigCloudUpcloud(login="test", password="test", username="ucuser")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    mock_server = MagicMock()
    mock_server.get_public_ip.return_value = "10.0.0.2"

    mock_client = MagicMock()
    mock_client.create_server.return_value = mock_server

    with (
        patch(
            "yascheduler.infra.cloud.providers.upcloud.get_client",
            return_value=mock_client,
        ),
    ):
        result = await upcloud_create_node(cfg, mock_key)

    assert isinstance(result, CloudCreateNodeDTO)
    assert result.external_id == "10.0.0.2"
    assert result.hostname == "10.0.0.2"
    assert result.username == "ucuser"


@requires_upcloud
@pytest.mark.asyncio
async def test_upcloud_delete_node_accepts_external_id() -> None:
    """upcloud_delete_node accepts external_id parameter to locate the resource."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudUpcloud
    from yascheduler.infra.cloud.providers.upcloud import upcloud_delete_node

    cfg = ConfigCloudUpcloud(login="test", password="test")

    mock_client = MagicMock()
    mock_client.get_servers.return_value = []

    with (
        patch(
            "yascheduler.infra.cloud.providers.upcloud.get_client",
            return_value=mock_client,
        ),
    ):
        # Should not raise — external_id is accepted as keyword
        await upcloud_delete_node(cfg, external_id="10.0.0.2")


@requires_upcloud
def test_upcloud_delete_node_is_renamed() -> None:
    """The UpCloud typo fix: upcload_delete_node is no longer exported, upcloud_delete_node is."""
    # Verify the module's __all__ and the adapter's import point
    from yascheduler.infra.cloud.providers import upcloud as upcloud_mod

    assert hasattr(upcloud_mod, "upcloud_delete_node")
    assert "upcloud_delete_node" in upcloud_mod.__all__
    assert not hasattr(upcloud_mod, "upcload_delete_node")


# =============================================================================
# VastAI
# =============================================================================


@pytest.mark.asyncio
async def test_vastai_create_node_returns_dto() -> None:
    """vastai_create_node returns CloudCreateNodeDTO with instance id as external_id."""
    from unittest.mock import patch

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI

    cfg = ConfigCloudVastAI(api_key="test-key")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAA..."

    from yascheduler.infra.cloud.providers.vastai import vastai_create_node

    def make_mock_resp(status: int, json_data: object) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=json_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    resp1 = make_mock_resp(200, [{"public_key": "ssh-rsa AAAA..."}])
    resp2 = make_mock_resp(200, {"offers": [{"id": 101, "dph_total": 0.5}]})
    resp3 = make_mock_resp(200, {"new_contract": 42})
    resp4 = make_mock_resp(
        200,
        {
            "instances": {
                "id": 42,
                "actual_status": "running",
                "ssh_host": "1.2.3.4",
                "ssh_port": 2222,
            },
        },
    )

    mock_session = MagicMock()
    mock_session.request = MagicMock(side_effect=[resp1, resp2, resp3, resp4])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
        return_value=mock_session,
    ):
        result = await vastai_create_node(cfg, mock_key)

    assert result.external_id == "42"
    assert result.hostname == "1.2.3.4"


@pytest.mark.asyncio
async def test_vastai_delete_node_accepts_external_id() -> None:
    """vastai_delete_node accepts external_id parameter to locate the resource."""
    from unittest.mock import patch

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudVastAI

    cfg = ConfigCloudVastAI(api_key="test-key")

    from yascheduler.infra.cloud.providers.vastai import vastai_delete_node

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"success": True})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.request = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "yascheduler.infra.cloud.providers.vastai.aiohttp.ClientSession",
        return_value=mock_session,
    ):
        await vastai_delete_node(cfg, external_id="10.0.0.3")
