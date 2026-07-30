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
# tests cleanly when the SDK is absent. vastai and hetzner only need aiohttp
# (core dep), so they always run. Mirrors the pytest.importorskip pattern but
# scoped per provider so aiohttp-only providers stay runnable.
requires_az = pytest.mark.skipif(
    importlib.util.find_spec("azure.identity") is None,
    reason="azure SDK not installed",
)
requires_upcloud = pytest.mark.skipif(
    importlib.util.find_spec("upcloud_api") is None, reason="upcloud_api not installed"
)


def _make_mock_resp(status: int, json_data: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def _make_mock_session_with_queue(
    responses: list[MagicMock],
) -> MagicMock:
    """Session whose .request pops responses in order."""
    session = MagicMock()
    session.request = MagicMock(side_effect=list(responses))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _hetz_ssh_key(key_id: int = 1, name: str = "yakey-abc") -> dict:
    return {"id": key_id, "name": name, "fingerprint": "aa:bb:cc:dd:ee"}


def _hetz_err(code: str, message: str = "err", status: int = 400) -> dict:
    return {"error": {"code": code, "message": message}}


def _hetz_ssh_key_stream(items: list):
    """Build an async generator mimicking HetznerClient.get_ssh_keys."""

    async def gen():
        for key in items:
            yield key

    return gen()


def _patch_hetzner_client(mock_client: MagicMock):
    """Patch HetznerClient so ``async with HetznerClient(...)`` yields mock_client."""
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = None
    return patch(
        "yascheduler.infra.cloud.providers.hetzner.HetznerClient",
        return_value=mock_cm,
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


@pytest.mark.asyncio
async def test_hetzner_create_node_returns_dto() -> None:
    """hetzner_create_node returns CloudCreateNodeDTO with server ID as external_id and IP as hostname."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

    cfg = ConfigCloudHetzner(username="testuser", token="test-token")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    mock_client = MagicMock()
    mock_client.get_ssh_keys = MagicMock(return_value=_hetz_ssh_key_stream([]))
    mock_client.create_ssh_key = AsyncMock(return_value=_hetz_ssh_key(123, "yakey-abc"))
    mock_client.create_server = AsyncMock(
        return_value={
            "id": 42,
            "name": "node-1",
            "public_net": {"ipv4": {"ip": "1.2.3.4"}},
        }
    )

    with (
        _patch_hetzner_client(mock_client),
        patch(
            "yascheduler.infra.cloud.providers.hetzner.get_key_name",
            return_value="yakey-abc",
        ),
    ):
        result = await hetzner_create_node(cfg, mock_key)

    assert isinstance(result, CloudCreateNodeDTO)
    assert result.external_id == "42"
    assert result.hostname == "1.2.3.4"


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

    mock_client = MagicMock()
    mock_client.get_ssh_keys = MagicMock(return_value=_hetz_ssh_key_stream([]))
    mock_client.create_ssh_key = AsyncMock(return_value=_hetz_ssh_key(123, "yakey-abc"))
    mock_client.create_server = AsyncMock(
        return_value={
            "id": 42,
            "name": "node-1",
            "public_net": {"ipv4": {"ip": "5.6.7.8"}},
        }
    )

    with (
        _patch_hetzner_client(mock_client),
        patch(
            "yascheduler.infra.cloud.providers.hetzner.get_key_name",
            return_value="yakey-abc",
        ),
    ):
        result = await hetzner_create_node(cfg, mock_key)

    assert result.username == "testuser"
    assert result.port == 22  # default, not in ConfigCloudHetzner
    assert result.jump_host == "jump.example.com"
    assert result.jump_port == 2222
    assert result.jump_username == "jumper"


@pytest.mark.asyncio
async def test_hetzner_delete_node_accepts_external_id() -> None:
    """hetzner_delete_node deletes by numeric server ID via client.delete_server."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import (
        HetznerError,
        hetzner_delete_node,
    )

    cfg = ConfigCloudHetzner(token="test-del-accept")
    mock_client = MagicMock()
    mock_client.delete_server = AsyncMock()
    # Accepted DELETE is verified gone via GET /servers/{id} → 404.
    mock_client.get_server = AsyncMock(side_effect=HetznerError("gone", status=404))

    with _patch_hetzner_client(mock_client):
        await hetzner_delete_node(cfg, external_id="42")

    mock_client.delete_server.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_hetzner_delete_node_api_not_found() -> None:
    """hetzner_delete_node handles 404 not_found from DELETE gracefully."""
    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import (
        HetznerError,
        hetzner_delete_node,
    )

    cfg = ConfigCloudHetzner(token="test-del-api404")
    mock_client = MagicMock()
    mock_client.delete_server = AsyncMock(
        side_effect=HetznerError("not found", status=404)
    )

    with _patch_hetzner_client(mock_client):
        # Should not raise — 404 is idempotent.
        await hetzner_delete_node(cfg, external_id="152213839")

    mock_client.delete_server.assert_awaited_once_with(152213839)


def test_hetzner_find_srv_removed() -> None:
    """find_srv no longer exists in hetzner provider module."""
    from yascheduler.infra.cloud.providers import hetzner as hetzner_mod

    assert not hasattr(hetzner_mod, "find_srv")


@pytest.mark.asyncio
async def test_hetzner_create_node_user_data_has_root_users() -> None:
    """hetzner_create_node injects a cloud-init `users` section with root + the SSH key."""
    import json

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

    cfg = ConfigCloudHetzner(token="test-users")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    mock_client = MagicMock()
    mock_client.get_ssh_keys = MagicMock(return_value=_hetz_ssh_key_stream([]))
    mock_client.create_ssh_key = AsyncMock(return_value=_hetz_ssh_key(123, "yakey-abc"))
    mock_client.create_server = AsyncMock(
        return_value={
            "id": 42,
            "name": "node-1",
            "public_net": {"ipv4": {"ip": "1.2.3.4"}},
        }
    )

    with (
        _patch_hetzner_client(mock_client),
        patch(
            "yascheduler.infra.cloud.providers.hetzner.get_key_name",
            return_value="yakey-abc",
        ),
    ):
        await hetzner_create_node(cfg, mock_key)

    user_data = mock_client.create_server.call_args.kwargs["user_data"]
    assert user_data.startswith("#cloud-config\n")
    payload = json.loads(user_data[len("#cloud-config\n") :])
    assert payload["users"] == [
        {"name": "root", "ssh_authorized_keys": ["ssh-rsa AAAAB3..."]}
    ]


@pytest.mark.asyncio
async def test_hetzner_create_node_non_root_user_in_user_data() -> None:
    """Non-root cfg.username is created via cloud-init users (no sudo)."""
    import json

    from yascheduler.infra.cloud.cloud_configs import ConfigCloudHetzner
    from yascheduler.infra.cloud.providers.hetzner import hetzner_create_node

    cfg = ConfigCloudHetzner(username="compute", token="test-users-nr")
    mock_key = MagicMock()
    mock_key.export_public_key.return_value = b"ssh-rsa AAAAB3..."

    mock_client = MagicMock()
    mock_client.get_ssh_keys = MagicMock(return_value=_hetz_ssh_key_stream([]))
    mock_client.create_ssh_key = AsyncMock(return_value=_hetz_ssh_key(123, "yakey-abc"))
    mock_client.create_server = AsyncMock(
        return_value={
            "id": 42,
            "name": "node-1",
            "public_net": {"ipv4": {"ip": "1.2.3.4"}},
        }
    )

    with (
        _patch_hetzner_client(mock_client),
        patch(
            "yascheduler.infra.cloud.providers.hetzner.get_key_name",
            return_value="yakey-abc",
        ),
    ):
        await hetzner_create_node(cfg, mock_key)

    user_data = mock_client.create_server.call_args.kwargs["user_data"]
    payload = json.loads(user_data[len("#cloud-config\n") :])
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
