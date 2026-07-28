"""Azure cloud methods."""
# region MODULE_CONTRACT
# PURPOSE: Provision and decommission Azure VMs so the scheduler can run compute workloads on Azure through the generic CloudAdapter contract.
# SCOPE: Azure create/delete node functions.
# DEPENDENCIES: USES API: azure-mgmt-compute, azure-mgmt-network, azure-identity (ClientSecretCredential); WRITES: HTTP to Azure Resource Manager (VM/NIC create/delete)
# KEYWORDS: azure, vm, create, delete, sdk, nic, network, compute
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from dataclasses import asdict as dataclass_asdict
from dataclasses import replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

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

from yascheduler.infra.cloud import CloudCreateNodeDTO, get_rnd_name

if TYPE_CHECKING:
    from asyncssh.public_key import SSHKey
    from azure.core.credentials_async import AsyncTokenCredential

    from yascheduler.infra.cloud import (
        AzureImageReference,
        CloudInitConfig,
        ConfigCloudAzure,
    )

__all__ = ["az_create_node", "az_delete_node"]
logger = logging.getLogger(__name__)

# Azure SDK is too noisy
for logger_name in [
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity.aio._internal.get_token_mixin",
    "msrest.serialization",
]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

ID_TAG_NAME = "yascheduler_ip"


# region FUNC__fetch_network_resources
# PURPOSE: Fetch subnet and NSG handles so NIC creation has the network topology references it needs.
async def _fetch_network_resources(
    cfg: ConfigCloudAzure,
    client: NetworkManagementClient,
) -> tuple:
    """Fetch subnet and network security group for NIC creation."""
    # region BLOCK_fetch_resources
    subnet = await client.subnets.get(
        resource_group_name=cfg.resource_group,
        virtual_network_name=cfg.vnet,
        subnet_name=cfg.subnet,
    )
    logger.debug("FETCH_SUBNET", extra={"subnet": subnet.name})
    nsg = await client.network_security_groups.get(cfg.resource_group, cfg.nsg)
    logger.debug("FETCH_NSG", extra={"nsg": nsg.name})
    # endregion BLOCK_fetch_resources
    return subnet, nsg


# endregion FUNC__fetch_network_resources


# region FUNC_create_nic
# PURPOSE: Provision a network interface in the target subnet and tag it with the VM's IP so network connectivity exists before the VM is created.
async def create_nic(
    cfg: ConfigCloudAzure,
    client: NetworkManagementClient,
    vm_name: str,
) -> tuple[NetworkInterface, str]:
    """Create network interface."""
    nic_name = f"{vm_name}-nic"
    ip_config_name = f"{nic_name}-ip-config"
    subnet, nsg = await _fetch_network_resources(cfg, client)
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
    logger.debug("CREATE_NIC", extra={"nic": nic.name})
    ip_addr = None
    if nic.ip_configurations:
        for ip_conf in nic.ip_configurations:
            ip_addr = ip_conf.private_ip_address
    if not ip_addr:
        msg = "Azure VM created but no IP is assigned"
        raise RuntimeError(msg)
    await client.network_interfaces.update_tags(
        cfg.resource_group,
        cast("str", nic.name),
        parameters=TagsObject(tags={ID_TAG_NAME: ip_addr}),
    )
    return nic, ip_addr


# endregion FUNC_create_nic


# region FUNC__render_custom_data
# PURPOSE: Inject cloud-config and Azure-specific boot commands so the VM self-configures on first boot before SSH becomes available.
def _render_custom_data(
    cloud_config: CloudInitConfig | None = None,
) -> str | None:
    """Render cloud-config custom data with Azure-specific boot commands."""
    # region BLOCK_render_custom_data
    custom_data = None
    if cloud_config:
        my_boot_cmds = [
            # see https://github.com/MicrosoftDocs/azure-docs/issues/82500
            "systemctl mask waagent-apt.service",
        ]
        custom_data = replace(
            cloud_config,
            bootcmd=(*my_boot_cmds, *cloud_config.bootcmd),
        ).render_base64()
    # endregion BLOCK_render_custom_data
    return custom_data


# endregion FUNC__render_custom_data


# region FUNC_create_vm_params
# PURPOSE: Assemble the full Azure VirtualMachine parameter object (OS profile, SSH key, cloud-config, disk) so the SDK call is a single clean invocation.
def create_vm_params(
    location: str,
    vm_name: str,
    vm_image: AzureImageReference,
    vm_size: str,
    nic: NetworkInterface,
    username: str,
    ssh_key: SSHKey,
    tags: dict[str, str],
    cloud_config: CloudInitConfig | None = None,
) -> VirtualMachine:
    """Create VirtualMachine params."""
    img_ref = ImageReference.from_dict(
        dataclass_asdict(vm_image),  # type: ignore[arg-type]
    )
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
            boot_diagnostics=BootDiagnostics(enabled=True),
        ),
    )


# endregion FUNC_create_vm_params


# region FUNC_create_node
# PURPOSE: Orchestrate NIC creation then VM provisioning so the caller gets a running VM's IP without managing intermediate resources.
# INVARIANTS:
# - external_id = hostname = VM's private IP
async def create_node(
    nmc: NetworkManagementClient,
    cmc: ComputeManagementClient,
    cfg: ConfigCloudAzure,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create virtual machine with nic."""
    vm_name = get_rnd_name("yascheduler-vm")
    nic, ip_addr = await create_nic(cfg=cfg, client=nmc, vm_name=vm_name)
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
    logger.debug("CREATE_VM", extra={"vm": vm_res.name})
    return CloudCreateNodeDTO(
        external_id=ip_addr,
        hostname=ip_addr,
        username=cfg.username,
        jump_host=cfg.jump_host,
        jump_port=cfg.jump_port,
        jump_username=cfg.jump_username or "root",
    )


# endregion FUNC_create_node


# region FUNC_az_create_node
# PURPOSE: Expose Azure VM creation through the CloudAdapter callable signature so the generic provisioner can launch Azure VMs without Azure-specific imports.
# INVARIANTS:
# - external_id = hostname = VM's private IP
async def az_create_node(
    cfg: ConfigCloudAzure,
    key: SSHKey,
    cloud_config: CloudInitConfig | None = None,
) -> CloudCreateNodeDTO:
    """Create virtual machine with network interface."""
    async with ClientSecretCredential(
        cfg.tenant_id,
        cfg.client_id,
        cfg.client_secret,
    ) as cred:
        cred = cast("AsyncTokenCredential", cred)  # fix library type errors
        async with (
            NetworkManagementClient(cred, cfg.subscription_id) as nmc,
            ComputeManagementClient(cred, cfg.subscription_id) as cmc,
        ):
            return await create_node(nmc, cmc, cfg, key, cloud_config)


# endregion FUNC_az_create_node


# region FUNC_delete_node
# PURPOSE: Tear down a VM and its NIC matched by IP so cloud billing stops and the resource group does not accumulate orphaned resources.
# INVARIANTS:
# - Matches VM by ID_TAG_NAME tag = IP
# - Iterates cmc.virtual_machines.list — IP match is the provider-internal mechanism permitted by the spec
async def delete_node(
    nmc: NetworkManagementClient,
    cmc: ComputeManagementClient,
    cfg: ConfigCloudAzure,
    external_id: str,
) -> None:
    """Delete virtual machine with network interface."""
    async for result in cmc.virtual_machines.list(cfg.resource_group):
        vm_res = cast("VirtualMachine", result)
        tag_ip = (vm_res.tags or {}).get(ID_TAG_NAME)
        if tag_ip == external_id:
            poller = await cmc.virtual_machines.begin_power_off(
                cfg.resource_group,
                cast("str", vm_res.name),
            )
            await poller.wait()

            poller = await cmc.virtual_machines.begin_delete(
                cfg.resource_group,
                cast("str", vm_res.name),
            )
            await poller.wait()
            logger.debug("DELETE_VM", extra={"vm": vm_res.name})
            break

    nic = None
    async for result in nmc.network_interfaces.list(cfg.resource_group):
        nic = cast("NetworkInterface", result)
        tag_ip = (nic.tags or {}).get(ID_TAG_NAME)
        if tag_ip == external_id:
            poller = await nmc.network_interfaces.begin_delete(
                cfg.resource_group,
                cast("str", nic.name),
            )
            await poller.wait()
            logger.debug("DELETE_NIC", extra={"nic": nic.name})
            break


# endregion FUNC_delete_node


# region FUNC_az_delete_node
# PURPOSE: Expose Azure VM deletion through the CloudAdapter callable signature so the generic provisioner can tear down Azure VMs without Azure-specific imports.
# INVARIANTS:
# - Matches VM by ID_TAG_NAME tag = IP
# - Iterates cmc.virtual_machines.list — IP match is the provider-internal mechanism permitted by the spec
async def az_delete_node(
    cfg: ConfigCloudAzure,
    external_id: str,
) -> None:
    """Delete virtual machine with network interface."""
    async with ClientSecretCredential(
        cfg.tenant_id,
        cfg.client_id,
        cfg.client_secret,
    ) as cred:
        cred = cast("AsyncTokenCredential", cred)  # fix library type errors
        async with (
            NetworkManagementClient(cred, cfg.subscription_id) as nmc,
            ComputeManagementClient(cred, cfg.subscription_id) as cmc,
        ):
            return await delete_node(nmc, cmc, cfg, external_id)


# endregion FUNC_az_delete_node
