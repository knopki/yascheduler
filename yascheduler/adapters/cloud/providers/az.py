# FILE: yascheduler/adapters/cloud/providers/az.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Azure VM creation and deletion using Azure SDK.
#   SCOPE: Azure create/delete node functions.
#   DEPENDS: M-CONFIG-CLOUD, M-CLOUD-PROTOCOLS, M-CLOUD-UTILS
#   LINKS: M-CLOUD-ADAPTERS-NEW, M-CONFIG-CLOUD
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ID_TAG_NAME - Tag name for IP tracking
#   RETRY_AZURE_ERRORS - Retryable Azure error types
#   ALL_AZURE_ERRORS - All Azure error types
#   create_nic - Create network interface for VM
#   create_vm_params - Build VirtualMachine parameter object
#   create_node - Create VM with NIC (internal)
#   az_create_node - Create Azure VM (public entry point)
#   delete_node - Delete VM and NIC (internal)
#   az_delete_node - Delete Azure VM and NIC (public entry point)
#   _fetch_network_resources - Fetch subnet and NSG for NIC creation
#   _render_custom_data - Render custom_data from cloud_config with boot commands
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.1 - Relocated from yascheduler/clouds/az.py; optional SDK imports; updated internal imports.
#   PREVIOUS_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Azure cloud methods"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

from attrs import asdict, evolve

try:
    from azure.core.exceptions import (
        AzureError,
        IncompleteReadError,
        ServiceRequestTimeoutError,
        ServiceResponseError,
        ServiceResponseTimeoutError,
    )
    from azure.identity.aio import ClientSecretCredential
    from azure.mgmt.compute.v2021_07_01.aio import ComputeManagementClient
    from azure.mgmt.compute.v2021_07_01.models import (
        BootDiagnostics,
        DiagnosticsProfile,
        DiskCreateOptionTypes,
        DiskDeleteOptionTypes,
        HardwareProfile,
        ImageReference,
        LinuxConfiguration,
        NetworkProfile,
        OSDisk,
        OSProfile,
        SshConfiguration,
        SshPublicKey,
        StorageProfile,
        VirtualMachine,
    )
    from azure.mgmt.network.v2020_06_01.aio import NetworkManagementClient
    from azure.mgmt.network.v2020_06_01.models import (
        IPAllocationMethod,
        NetworkInterface,
        NetworkInterfaceIPConfiguration,
        TagsObject,
    )

    _AZURE_AVAILABLE = True
except ImportError:
    _AZURE_AVAILABLE = False

from ..utils import get_rnd_name

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey
    from azure.core.credentials_async import AsyncTokenCredential

    from ....config.cloud import AzureImageReference, ConfigCloudAzure
    from ..protocols import PCloudConfig

# Azure SDK is too noisy
for logger_name in [
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity.aio._internal.get_token_mixin",
    "msrest.serialization",
]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)


ID_TAG_NAME = "yascheduler_ip"

if _AZURE_AVAILABLE:
    RETRY_AZURE_ERRORS = (
        ServiceResponseError,
        ServiceRequestTimeoutError,
        ServiceResponseTimeoutError,
        IncompleteReadError,
    )
    ALL_AZURE_ERRORS = (AzureError,)
else:
    RETRY_AZURE_ERRORS = ()
    ALL_AZURE_ERRORS = ()


# START_CONTRACT: _fetch_network_resources
#   PURPOSE: Fetch subnet and NSG for NIC creation
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudAzure - Azure config, client: NetworkManagementClient - Azure network client }
#   OUTPUTS: { tuple - subnet and NSG }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-AZ
# END_CONTRACT: _fetch_network_resources
async def _fetch_network_resources(
    log: logging.Logger,
    cfg: ConfigCloudAzure,
    client: NetworkManagementClient,
) -> tuple:
    """Fetch subnet and network security group for NIC creation"""
    # START_BLOCK_FETCH_RESOURCES
    subnet = await client.subnets.get(
        resource_group_name=cfg.resource_group,
        virtual_network_name=cfg.vnet,
        subnet_name=cfg.subnet,
    )
    log.debug("[Azure][_fetch_network_resources] subnet=%s", subnet.name)
    nsg = await client.network_security_groups.get(cfg.resource_group, cfg.nsg)
    log.debug("[Azure][_fetch_network_resources] nsg=%s", nsg.name)
    # END_BLOCK_FETCH_RESOURCES
    return subnet, nsg


# START_CONTRACT: create_nic
#   PURPOSE: Create network interface for VM and tag with IP address
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudAzure - Azure config, client: NetworkManagementClient - Azure network client, vm_name: str - VM name }
#   OUTPUTS: { tuple[NetworkInterface, str] - NIC and assigned IP address }
#   SIDE_EFFECTS: Creates Azure NIC resource and tags it
#   LINKS: M-CLOUD-AZ
# END_CONTRACT: create_nic
async def create_nic(
    log: logging.Logger,
    cfg: ConfigCloudAzure,
    client: NetworkManagementClient,
    vm_name: str,
) -> tuple[NetworkInterface, str]:
    "Create network interface"
    nic_name = f"{vm_name}-nic"
    ip_config_name = f"{nic_name}-ip-config"
    subnet, nsg = await _fetch_network_resources(log, cfg, client)
    nic_ip_config_params = NetworkInterfaceIPConfiguration(
        name=ip_config_name,
        subnet=subnet,
        private_ip_allocation_method=IPAllocationMethod.DYNAMIC,
    )
    nic_params = NetworkInterface(
        name=nic_name,
        location=cfg.location,
        ip_configurations=[nic_ip_config_params],
        network_security_group=nsg,
    )
    poller = await client.network_interfaces.begin_create_or_update(
        resource_group_name=cfg.resource_group,
        network_interface_name=nic_name,
        parameters=nic_params,
    )
    await poller.wait()
    nic = await poller.result()
    log.debug("[Azure][create_nic] nic=%s", nic.name)
    ip_addr = None
    if nic.ip_configurations:
        for ip_conf in nic.ip_configurations:
            ip_addr = ip_conf.private_ip_address
    if not ip_addr:
        raise RuntimeError("Azure VM created but no IP is assigned")
    await client.network_interfaces.update_tags(
        cfg.resource_group,
        cast("str", nic.name),
        parameters=TagsObject(tags={ID_TAG_NAME: ip_addr}),
    )
    return nic, ip_addr


# START_CONTRACT: _render_custom_data
#   PURPOSE: Render custom_data from cloud_config with boot commands
#   INPUTS: { cloud_config: Optional[PCloudConfig] - optional cloud-config }
#   OUTPUTS: { Optional[str] - base64-encoded cloud-config or None }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-AZ
# END_CONTRACT: _render_custom_data
def _render_custom_data(
    cloud_config: PCloudConfig | None = None,
) -> str | None:
    """Render cloud-config custom data with Azure-specific boot commands"""
    # START_BLOCK_RENDER_CUSTOM_DATA
    custom_data = None
    if cloud_config:
        my_boot_cmds = [
            # see https://github.com/MicrosoftDocs/azure-docs/issues/82500
            "systemctl mask waagent-apt.service",
        ]
        custom_data = evolve(
            cloud_config, bootcmd=[*my_boot_cmds, *cloud_config.bootcmd]
        ).render_base64()
    # END_BLOCK_RENDER_CUSTOM_DATA
    return custom_data


# START_CONTRACT: create_vm_params
#   PURPOSE: Build VirtualMachine parameter object with SSH key and cloud-config
#   INPUTS: { location: str - Azure region, vm_name: str - VM name, vm_image: AzureImageReference - image reference, vm_size: str - VM size, nic: NetworkInterface - network interface, username: str - admin username, ssh_key: SSHKey - SSH key, tags: dict[str,str] - resource tags, cloud_config: Optional[PCloudConfig] - optional cloud-config }
#   OUTPUTS: { VirtualMachine - Azure VirtualMachine parameters }
#   SIDE_EFFECTS: None
#   LINKS: M-CLOUD-AZ
# END_CONTRACT: create_vm_params
def create_vm_params(
    location: str,
    vm_name: str,
    vm_image: AzureImageReference,
    vm_size: str,
    nic: NetworkInterface,
    username: str,
    ssh_key: SSHKey,
    tags: dict[str, str],
    cloud_config: PCloudConfig | None = None,
) -> VirtualMachine:
    """Create VirtualMachine params"""
    img_ref = ImageReference.from_dict(asdict(vm_image))  # type: ignore[arg-type]
    pub_key = SshPublicKey(
        path=str(PurePosixPath("/home", username, ".ssh/authorized_keys")),
        key_data=ssh_key.export_public_key("openssh").decode("utf-8"),
    )
    custom_data = _render_custom_data(cloud_config)

    return VirtualMachine(
        location=location,
        tags=tags,
        hardware_profile=HardwareProfile(vm_size=vm_size),
        storage_profile=StorageProfile(
            image_reference=img_ref,
            os_disk=OSDisk(
                create_option=DiskCreateOptionTypes.FROM_IMAGE,
                delete_option=DiskDeleteOptionTypes.DELETE,
            ),
        ),
        network_profile=NetworkProfile(network_interfaces=[nic]),
        os_profile=OSProfile(
            computer_name=vm_name[:15],  # max length 15
            admin_username=username,
            custom_data=custom_data,
            linux_configuration=LinuxConfiguration(
                disable_password_authentication=True,
                ssh=SshConfiguration(public_keys=[pub_key]),
            ),
        ),
        diagnostics_profile=DiagnosticsProfile(
            boot_diagnostics=BootDiagnostics(enabled=True)
        ),
    )


# START_CONTRACT: create_node
#   PURPOSE: Create Azure VM with NIC, private IP, and SSH key (internal)
#   INPUTS: { nmc: NetworkManagementClient - network client, cmc: ComputeManagementClient - compute client, log: logging.Logger - logger, cfg: ConfigCloudAzure - Azure config, key: SSHKey - SSH key, cloud_config: Optional[PCloudConfig] - optional cloud-config }
#   OUTPUTS: { str - private IP address of created VM }
#   SIDE_EFFECTS: Creates Azure VM and NIC resources
#   LINKS: M-CLOUD-AZ, create_nic, create_vm_params
# END_CONTRACT: create_node
async def create_node(
    nmc: NetworkManagementClient,
    cmc: ComputeManagementClient,
    log: logging.Logger,
    cfg: ConfigCloudAzure,
    key: SSHKey,
    cloud_config: PCloudConfig | None = None,
) -> str:
    """Create virtual machine with nic"""
    vm_name = get_rnd_name("yascheduler-vm")
    nic, ip_addr = await create_nic(log=log, cfg=cfg, client=nmc, vm_name=vm_name)
    vm_params = create_vm_params(
        location=cfg.location,
        vm_name=vm_name,
        vm_image=cfg.vm_image,
        vm_size=cfg.vm_size,
        nic=nic,
        username=cfg.username,
        ssh_key=key,
        tags={ID_TAG_NAME: ip_addr},
        cloud_config=cloud_config,
    )

    poller = await cmc.virtual_machines.begin_create_or_update(
        resource_group_name=cfg.resource_group,
        vm_name=get_rnd_name("yascheduler-vm"),
        parameters=vm_params,
    )
    await poller.wait()
    vm_res = await poller.result()
    log.debug("[Azure][az_create_node] vm=%s", vm_res.name)
    return ip_addr


# START_CONTRACT: az_create_node
#   PURPOSE: Create Azure VM with NIC (public entry point for adapter)
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudAzure - Azure config, key: SSHKey - SSH key, cloud_config: Optional[PCloudConfig] - optional cloud-config }
#   OUTPUTS: { str - IP address of created VM }
#   SIDE_EFFECTS: Creates Azure VM, NIC, and credentials; acquires cloud resources
#   LINKS: M-CLOUD-AZ, create_node
# END_CONTRACT: az_create_node
async def az_create_node(
    log: logging.Logger,
    cfg: ConfigCloudAzure,
    key: SSHKey,
    cloud_config: PCloudConfig | None = None,
) -> str:
    """Create virtual machine with network interface"""
    if not _AZURE_AVAILABLE:
        raise ImportError(
            "Azure SDK not installed. Install azure-identity and azure-mgmt-* packages."
        )
    async with ClientSecretCredential(
        cfg.tenant_id, cfg.client_id, cfg.client_secret
    ) as cred:
        cred = cast("AsyncTokenCredential", cred)  # fix library type errors
        async with NetworkManagementClient(cred, cfg.subscription_id) as nmc:
            async with ComputeManagementClient(cred, cfg.subscription_id) as cmc:
                return await create_node(nmc, cmc, log, cfg, key, cloud_config)


# START_CONTRACT: delete_node
#   PURPOSE: Delete Azure VM and NIC by host IP address (internal)
#   INPUTS: { nmc: NetworkManagementClient - network client, cmc: ComputeManagementClient - compute client, log: logging.Logger - logger, cfg: ConfigCloudAzure - Azure config, host: str - IP address of VM to delete }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Deletes Azure VM and NIC resources
#   LINKS: M-CLOUD-AZ
# END_CONTRACT: delete_node
async def delete_node(
    nmc: NetworkManagementClient,
    cmc: ComputeManagementClient,
    log: logging.Logger,
    cfg: ConfigCloudAzure,
    host: str,
) -> None:
    """Delete virtual machine with network interface"""
    async for result in cmc.virtual_machines.list(cfg.resource_group):
        vm_res = cast("VirtualMachine", result)
        tag_ip = (vm_res.tags or {}).get(ID_TAG_NAME)
        if tag_ip == host:
            poller = await cmc.virtual_machines.begin_power_off(
                cfg.resource_group, cast("str", vm_res.name)
            )
            await poller.wait()

            poller = await cmc.virtual_machines.begin_delete(
                cfg.resource_group, cast("str", vm_res.name)
            )
            await poller.wait()
            log.debug("[Azure][az_delete_node] vm=%s deleted", vm_res.name)
            break

    nic = None
    async for result in nmc.network_interfaces.list(cfg.resource_group):
        nic = cast("NetworkInterface", result)
        tag_ip = (nic.tags or {}).get(ID_TAG_NAME)
        if tag_ip == host:
            poller = await nmc.network_interfaces.begin_delete(
                cfg.resource_group, cast("str", nic.name)
            )
            await poller.wait()
            log.debug("[Azure][az_delete_node] nic=%s deleted", nic.name)
            break


# START_CONTRACT: az_delete_node
#   PURPOSE: Delete Azure VM and NIC by host IP (public entry point for adapter)
#   INPUTS: { log: logging.Logger - logger, cfg: ConfigCloudAzure - Azure config, host: str - IP address of VM to delete }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates Azure credentials, deletes VM and NIC resources
#   LINKS: M-CLOUD-AZ, delete_node
# END_CONTRACT: az_delete_node
async def az_delete_node(
    log: logging.Logger,
    cfg: ConfigCloudAzure,
    host: str,
) -> None:
    """Delete virtual machine with network interface"""
    if not _AZURE_AVAILABLE:
        raise ImportError(
            "Azure SDK not installed. Install azure-identity and azure-mgmt-* packages."
        )
    async with ClientSecretCredential(
        cfg.tenant_id, cfg.client_id, cfg.client_secret
    ) as cred:
        cred = cast("AsyncTokenCredential", cred)  # fix library type errors
        async with NetworkManagementClient(cred, cfg.subscription_id) as nmc:
            async with ComputeManagementClient(cred, cfg.subscription_id) as cmc:
                return await delete_node(nmc, cmc, log, cfg, host)
