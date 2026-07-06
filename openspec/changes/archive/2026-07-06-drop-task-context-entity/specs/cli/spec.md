# Spec Delta: cli

## MODIFIED Requirements

### Requirement: yastatus queries task status

The `yastatus` command SHALL query and display task status, optionally with
remote machine output (verbose mode) and convergence info, resolving nodes via
`get_by_ids` (batch lookup by `allocated_node_id`). The command is implemented
as `check_status()` in `yascheduler/entrypoints/cli/check_status.py`, a
synchronous entry point that calls `asyncio.run(_check_status_async(argv))`
and accepts `argv: list[str] | None = None` for testability.

In view/json mode, the command SHALL open a single query-phase UoW, read
tasks via `_query_tasks(uow, args)`, and read nodes via
`uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if
t.allocated_node_id])` (a single batch round-trip), building
`nodes_by_id: dict[NodeId, Node]`. The UoW is closed before any SSH work
in the view path.

The renderers SHALL look up nodes via `nodes_by_id.get(task.allocated_node_id)`.
The `_render_json` output object SHALL emit a nested `node` object (see the
"yastatus --json output format" requirement) built from the resolved `Node`,
and SHALL NOT emit flat `allocated_ip`/`port`/`cloud` fields (those are
removed in favor of the nested `node`). The `_render_info` renderer SHALL emit
`node_id={task.allocated_node_id}` (was `ip={task.allocated_ip}`) as the
placement field, because the `Task` entity no longer carries `allocated_ip`.

The `_render_json` output object SHALL read `engine`, `local_folder`, and
`remote_folder` from the typed `Task` fields directly (`task.engine`,
`task.local_folder`, `task.remote_folder` — was `task.context.engine`,
`task.context.local_folder`, `task.context.remote_folder`). No `TaskContext`
indirection; the `task.context` accessor is removed (see the `domain-entities`
delta).

The `_display_remote_output` helper SHALL read `task.remote_folder` (was
`task.context.remote_folder`) for the remote output directory path, resolve
the node via `nodes_by_id.get(task.allocated_node_id)`, build `_ConnParams`
from the node (via `_resolve_conn_params(node, config)`), and connect via
`SSHMachineRepository().connect(node, ...)` (passing the `Node` so the
session registers under `node.node_id`). The finally block SHALL call
`repository.disconnect(session.machine.node_id)`. The verbose renderer
(`_render_view`) SHALL use `node.ip` (the resolved `Node`'s transport
address) in its display line, NOT `task.allocated_ip` (which is removed).

#### Scenario: yastatus queries tasks via CLIDeps

- **WHEN** yastatus is invoked (default mode, `-i`, `--json`, or `-v`)
- **THEN** make_cli_deps() is called, tasks are read via `uow.tasks.list_by_status({RUNNING, TO_DO})` (default) or `uow.tasks.list_by_jobs(job_ids)` (with `-j`), and the selected renderer prints the result

#### Scenario: yastatus view/json resolves nodes via get_by_ids

- **WHEN** yastatus is invoked with `--view` or `--json` and tasks have `allocated_node_id` set
- **THEN** the query-phase UoW calls `uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if t.allocated_node_id])` (a single batch round-trip); the resulting `nodes_by_id: dict[NodeId, Node]` is closed over for the render phase

#### Scenario: yastatus does not read allocated_ip

- **WHEN** the `check_status.py` implementation is inspected
- **THEN** no code reads `task.allocated_ip` (the field is removed from `Task`); node transport address is obtained from the resolved `Node.ip` via `nodes_by_id`

#### Scenario: yastatus _render_json reads typed fields not task.context
- **WHEN** `_render_json` is inspected for `task.context` references
- **THEN** none are present; the renderer reads `task.engine`, `task.local_folder`, `task.remote_folder` (was `task.context.engine`, `task.context.local_folder`, `task.context.remote_folder`)

#### Scenario: yastatus _display_remote_output reads task.remote_folder
- **WHEN** `_display_remote_output` is inspected for the remote folder read
- **THEN** it reads `task.remote_folder` (was `task.context.remote_folder`); no `task.context` reference

#### Scenario: yastatus _display_remote_output connects via Node

- **WHEN** `_display_remote_output` is called for a running task
- **THEN** it resolves the node via `nodes_by_id.get(task.allocated_node_id)`, builds `_ConnParams` from the node, connects via `SSHMachineRepository().connect(node, ...)` (the session registers under `node.node_id`), and disconnects via `repository.disconnect(session.machine.node_id)` in the finally block