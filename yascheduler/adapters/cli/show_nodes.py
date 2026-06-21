# FILE: yascheduler/adapters/cli/show_nodes.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: yanodes CLI command — display enabled nodes and their running tasks.
#   SCOPE: show_nodes command.
#   DEPENDS: M-DI, M-CONFIG, M-DOMAIN-MODEL, M-VARIABLES
#   LINKS: M-CLI-COMMANDS, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   show_nodes - Show enabled nodes and running tasks
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from adapters/cli/commands.py per-command split.
# END_CHANGE_SUMMARY
# FIXME: split adapter and applicacation layer (business logic)

from yascheduler.client import to_sync
from yascheduler.config import Config
from yascheduler.di import make_cli_deps
from yascheduler.domain import TaskStatus
from yascheduler.variables import CONFIG_FILE


# START_CONTRACT: show_nodes
#   PURPOSE: Display all enabled nodes and their currently running tasks
#   INPUTS: { None - reads config from CONFIG_FILE }
#   OUTPUTS: { None - prints node info to stdout }
#   SIDE_EFFECTS: Connects to DB via UoW, reads node and task records
#   LINKS: M-CLI-COMMANDS, M-DI, M-APPLICATION-UOW
# END_CONTRACT: show_nodes
@to_sync
async def show_nodes() -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)

    async with deps.uow_factory() as uow:
        tasks = await uow.tasks.list_by_status(statuses={TaskStatus.RUNNING})
        nodes = await uow.nodes.list_all()
        for node in nodes:
            tmpl = "ip={ip}{port} ncpus={ncpus} enabled={enabled} occupied_by={occ} (task_id={tid}) {cloud}"
            node_tasks = [t for t in tasks if t.allocated_ip == node.ip]
            node_label = "-"
            task_id = "-"
            for x in node_tasks:
                node_label = x.label
                task_id = x.task_id
            msg = tmpl.format(
                ip=node.ip,
                port=f":{node.port}" if node.port != 22 else "",
                ncpus=node.ncpus or "MAX",
                enabled=node.enabled,
                occ=node_label,
                tid=task_id,
                cloud=node.cloud or "",
            )
            print(msg)
